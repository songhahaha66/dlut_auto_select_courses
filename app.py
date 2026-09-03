from flask import Flask, render_template, request, jsonify, redirect, session
import json
import threading
import time
import dlut_sso
import requests
import re
import os
import sys

app = Flask(__name__)
app.secret_key = 'dlut_course_select_secret_key_2024'

def get_data_dir():
    """获取数据存储目录（用户目录下）"""
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后
        data_dir = os.path.join(os.path.expanduser('~'), '.dlut-course-select')
    else:
        # 开发环境
        data_dir = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(data_dir, exist_ok=True)
    return data_dir

def get_ilist_path():
    """获取 ilist.json 路径（始终存在用户目录）"""
    cache_dir = os.path.join(os.path.expanduser('~'), '.dlut-course-select')
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, 'ilist.json')

# 全局变量存储登录状态
login_state = {
    'logged_in': False,
    'cookies': None,
    'stu_id': None,
    'turn_id': None,
    'ilist': None
}

# 学生ID缓存 (学号 -> 学生ID)
stu_id_cache = {}
# 轮次缓存 (学号 -> 轮次列表)
turns_cache = {}

def get_stu_id_cache_path():
    """获取学生ID缓存文件路径（始终存在用户目录）"""
    cache_dir = os.path.join(os.path.expanduser('~'), '.dlut-course-select')
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, 'stu_id_cache.json')

def get_turns_cache_path():
    """获取轮次缓存文件路径"""
    cache_dir = os.path.join(os.path.expanduser('~'), '.dlut-course-select')
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, 'turns_cache.json')

def load_stu_id_cache():
    """加载学生ID缓存"""
    global stu_id_cache
    try:
        with open(get_stu_id_cache_path(), 'r') as f:
            stu_id_cache = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        stu_id_cache = {}

def save_stu_id_cache():
    """保存学生ID缓存"""
    with open(get_stu_id_cache_path(), 'w') as f:
        json.dump(stu_id_cache, f)

def load_turns_cache():
    """加载轮次缓存"""
    global turns_cache
    try:
        with open(get_turns_cache_path(), 'r') as f:
            turns_cache = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        turns_cache = {}

def save_turns_cache():
    """保存轮次缓存"""
    with open(get_turns_cache_path(), 'w') as f:
        json.dump(turns_cache, f)

# 启动时加载缓存
load_stu_id_cache()
load_turns_cache()

# ============ 网络请求重试配置 ============

def create_retry_session(retries=3, backoff_factor=0.5, status_forcelist=(500, 502, 503, 504)):
    """创建带重试机制的 requests session"""
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    session = requests.Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        allowed_methods=["HEAD", "GET", "POST", "OPTIONS"]
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

def request_with_retry(method, url, cookies=None, data=None, json_data=None, max_retries=10, timeout=10):
    """带重试的请求函数"""
    for attempt in range(max_retries):
        try:
            session = create_retry_session()
            if method.upper() == 'GET':
                return session.get(url, cookies=cookies, timeout=timeout)
            else:
                if json_data:
                    return session.post(url, json=json_data, cookies=cookies, timeout=timeout)
                else:
                    return session.post(url, data=data, cookies=cookies, timeout=timeout)
        except (requests.exceptions.ConnectionError, 
                requests.exceptions.ChunkedEncodingError,
                requests.exceptions.Timeout) as e:
            print(f"[重试 {attempt + 1}/{max_retries}] {str(e)[:50]}")
            if attempt == max_retries - 1:
                raise e

# ============ 核心功能函数 ============

def jw_login(userid, password):
    """教务系统登录"""
    s = dlut_sso.login(userid, password)
    cookies = {
        "SESSION": s.cookies['SESSION'],
        "INGRESSCOOKIE": s.cookies['INGRESSCOOKIE'],
        "SERVERNAME": s.cookies['SERVERNAME']
    }
    s.get("http://jxgl.dlut.edu.cn/student/for-std/course-select")
    return cookies

def get_student_id(cookies, userid=None):
    """获取学生ID（优先使用缓存）"""
    global stu_id_cache
    
    # 如果有学号且缓存中存在，直接返回
    if userid and userid in stu_id_cache:
        print(f"[缓存命中] 学生ID: {stu_id_cache[userid]}")
        return stu_id_cache[userid]
    
    # 从服务器获取
    url = "http://jxgl.dlut.edu.cn/student/for-std/course-select/single-student/turns"
    r = request_with_retry('GET', url, cookies=cookies)
    html = r.text
    match = re.search(r'studentId\s*:\s*(\d+),', html)
    if match:
        stu_id = int(match.group(1))
        # 缓存结果
        if userid:
            stu_id_cache[userid] = stu_id
            save_stu_id_cache()
            print(f"[缓存保存] 学号 {userid} -> 学生ID {stu_id}")
        return stu_id
    return None

def get_open_turns(cookies, stu_id, userid=None, force_refresh=False):
    """获取所有可用的选课轮次（优先使用缓存）"""
    global turns_cache
    
    # 如果有学号且缓存中存在且不强制刷新，直接返回
    if userid and userid in turns_cache and not force_refresh:
        print(f"[缓存命中] 轮次列表")
        return turns_cache[userid]
    
    url = "http://jxgl.dlut.edu.cn/student/ws/for-std/course-select/open-turns"
    data = {"bizTypeId": "2", "studentId": stu_id}
    r = request_with_retry('POST', url, cookies=cookies, data=data)
    turns = json.loads(r.text)
    
    # 缓存结果
    if userid and turns:
        turns_cache[userid] = turns
        save_turns_cache()
        print(f"[缓存保存] 轮次列表")
    
    return turns

def get_itemList(cookies, turn_id):
    """获取课程列表"""
    url = f"http://jxgl.dlut.edu.cn/student/cache/course-select/version/{turn_id}/version.json"
    r = request_with_retry('GET', url, cookies=cookies)
    data = json.loads(r.text)
    
    all_courses = []
    # 遍历所有分片文件，合并课程数据
    for item_id in data['itemList']:
        url1 = f"http://cdn-dlut.supwisdom.com/student/cache/course-select/addable-lessons/{turn_id}/{item_id}.json"
        resp = json.loads(requests.get(url1, cookies=cookies).text)
        result = resp['data']
        # 如果 data 是字符串，再解析一次
        if isinstance(result, str):
            result = json.loads(result)
        all_courses.extend(result)
    return all_courses

def select_classes(cookies, stu_id, class_id, turn_id, schedule_group_id=None):
    """选课"""
    try:
        url = "http://jxgl.dlut.edu.cn/student/ws/for-std/course-select/add-request"
        data = {"studentAssoc": stu_id, "courseSelectTurnAssoc": turn_id,
                "requestMiddleDtos": [{"lessonAssoc": class_id, "virtualCost": 0, "scheduleGroupAssoc": schedule_group_id}]}
        r1 = requests.post(url, json=data, cookies=cookies, timeout=15)
        uuid1 = r1.text

        url1 = "http://jxgl.dlut.edu.cn/student/ws/for-std/course-select/add-drop-response"
        data1 = {"studentId": stu_id, "requestId": uuid1}
        r2 = requests.post(url1, data=data1, cookies=cookies, timeout=15)

        if r2.status_code != 200:
            return {"error": f"HTTP错误: {r2.status_code}"}

        r2_res = json.loads(r2.text)
        if r2_res is None:
            return {"error": "服务器返回空响应"}

        if r2_res.get('success'):
            return True
        else:
            return r2_res.get('errorMessage', {}).get('textZh', '选课失败')
    except Exception as e:
        return {"error": f"选课请求异常: {str(e)}"}

def drop_classes(cookies, stu_id, class_id, turn_id):
    """退课"""
    try:
        url = "http://jxgl.dlut.edu.cn/student/ws/for-std/course-select/drop-request"
        data = {"studentAssoc": stu_id, "lessonAssocs": [class_id],
                "courseSelectTurnAssoc": turn_id, "coursePackAssoc": None}
        r1 = requests.post(url, json=data, cookies=cookies, timeout=15)
        uuid1 = r1.text
        
        url1 = "http://jxgl.dlut.edu.cn/student/ws/for-std/course-select/add-drop-response"
        data1 = {"studentId": stu_id, "requestId": uuid1}
        r2 = requests.post(url1, data=data1, cookies=cookies, timeout=15)
        
        if r2.status_code != 200:
            return {"error": f"HTTP错误: {r2.status_code}"}
        
        r2_res = json.loads(r2.text)
        if r2_res is None:
            return {"error": "服务器返回空响应"}
        
        if r2_res.get('success'):
            return True
        else:
            return r2_res.get('errorMessage', {}).get('textZh', '退课失败')
    except Exception as e:
        return {"error": f"退课请求异常: {str(e)}"}

def _result_error_text(result):
    return str(result.get('error', result)) if isinstance(result, dict) else str(result)

def select_classes_with_drop(cookies, stu_id, class_id, turn_id, drop_class_id, schedule_group_id=None):
    """先退课再选课。退课失败不中断；选课失败且已退课时尝试选回原课。
    返回 (success: bool, message: str)
    """
    if not class_id:
        return False, '缺少目标课程ID'
    if not drop_class_id:
        return False, '缺少要退的课程ID'
    if str(class_id) == str(drop_class_id):
        return False, '要退的课程与目标课程相同'

    drop_result = drop_classes(cookies, stu_id, drop_class_id, turn_id)
    dropped = drop_result is True

    select_result = select_classes(cookies, stu_id, class_id, turn_id, schedule_group_id)
    if select_result is True:
        if dropped:
            return True, '退课并选课成功'
        return True, f'选课成功（退课未执行: {_result_error_text(drop_result)}）'

    error_msg = _result_error_text(select_result)
    if not dropped:
        return False, f'选课失败: {error_msg}'

    restore_result = select_classes(cookies, stu_id, drop_class_id, turn_id)
    if restore_result is True:
        return False, f'退课后选课失败，已选回原课程: {error_msg}'
    return False, (
        f'退课后选课失败，且选回原课程失败: {error_msg}'
        f'（选回失败原因: {_result_error_text(restore_result)}）'
    )

def get_selected_classes(cookies, stu_id, turn_id):
    """获取已选课程"""
    url = "http://jxgl.dlut.edu.cn/student/ws/for-std/course-select/selected-lessons"
    data = {"studentId": stu_id, "turnId": turn_id}
    r = requests.post(url, data=data, cookies=cookies, timeout=15)
    return json.loads(r.text)

def get_selected_numbers(cookies, lesson_ids):
    """获取选课人数"""
    url = "http://jxgl.dlut.edu.cn/student/ws/for-std/course-select/std-count"
    data = [("lessonIds[]", lid) for lid in lesson_ids]
    r = requests.post(url, data=data, cookies=cookies, timeout=15)
    return json.loads(r.text)

# ============ 路由 ============

@app.route('/login')
def login_page():
    """登录页面"""
    return render_template('login.html')

@app.route('/api/login', methods=['POST'])
def api_login():
    """登录API - 使用前端传来的 cookies，不再重复登录"""
    global login_state
    
    try:
        data = request.get_json()
        userid = data.get('userid')
        turn_id = data.get('turn_id')
        cookies = data.get('cookies')  # 从 get_turns 缓存的 cookies
        stu_id = data.get('stu_id')    # 从 get_turns 缓存的 stu_id
        
        # 如果没有传 cookies，说明是直接登录（跳过轮次选择）
        if not cookies:
            password = data.get('password')
            cookies = jw_login(userid, password)
            stu_id = get_student_id(cookies, userid)
            
            if not stu_id:
                return jsonify({'success': False, 'message': '获取学生ID失败'})
            
            if not turn_id:
                turns = get_open_turns(cookies, stu_id, userid)
                if not turns:
                    return jsonify({'success': False, 'message': '没有可用的选课轮次'})
                turn_id = turns[0]['id']
        
        # 获取课程列表
        try:
            with open(get_ilist_path(), "r", encoding="utf-8") as f:
                ilist = json.load(f)
        except FileNotFoundError:
            ilist = get_itemList(cookies, turn_id)
            with open(get_ilist_path(), "w", encoding="utf-8") as f:
                json.dump(ilist, f, ensure_ascii=False, indent=4)
        
        # 换账号/重新登录时，上一轮遗留的队列与监控列表已失效
        reset_background_tasks()

        # 保存登录状态
        login_state = {
            'logged_in': True,
            'cookies': cookies,
            'stu_id': stu_id,
            'turn_id': turn_id,
            'ilist': ilist
        }
        
        return jsonify({'success': True, 'message': '登录成功'})
    
    except Exception as e:
        return jsonify({'success': False, 'message': f'登录失败: {str(e)}'})

@app.route('/api/get_turns', methods=['POST'])
def api_get_turns():
    """获取可用的选课轮次（登录后调用）"""
    try:
        data = request.get_json()
        userid = data.get('userid')
        password = data.get('password')
        force_refresh = data.get('force_refresh', False)
        cookies = data.get('cookies')  # 刷新时复用已有 cookies
        stu_id = data.get('stu_id')
        
        # 如果没有传 cookies，需要登录
        if not cookies:
            try:
                cookies = jw_login(userid, password)
            except Exception as e:
                return jsonify({'success': False, 'message': f'SSO登录失败: {str(e)[:100]}'})
            
            try:
                stu_id = get_student_id(cookies, userid)
            except Exception as e:
                return jsonify({'success': False, 'message': f'获取学生ID失败: {str(e)[:100]}'})
            
            if not stu_id:
                return jsonify({'success': False, 'message': '获取学生ID失败，请检查账号密码'})
        
        # 获取可用轮次
        try:
            turns = get_open_turns(cookies, stu_id, userid, force_refresh)
        except Exception as e:
            return jsonify({'success': False, 'message': f'获取轮次列表失败: {str(e)[:100]}'})
        
        # 格式化返回
        turn_list = []
        for turn in turns:
            turn_list.append({
                'id': turn['id'],
                'name': turn.get('name', ''),
                'nameZh': turn.get('nameZh', turn.get('name', f"轮次 {turn['id']}"))
            })
        
        return jsonify({
            'success': True,
            'turns': turn_list,
            'cookies': cookies,
            'stu_id': stu_id
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取轮次失败: {str(e)}'})

@app.route('/api/logout', methods=['POST'])
def api_logout():
    """登出"""
    global login_state
    # 先停掉后台任务，否则它们会继续拿着失效的 cookies 空转
    reset_background_tasks()
    login_state = {
        'logged_in': False,
        'cookies': None,
        'stu_id': None,
        'turn_id': None,
        'ilist': None
    }
    return jsonify({'success': True})

def require_login(f):
    """登录检查装饰器"""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not login_state['logged_in']:
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'success': False, 'message': '请先登录', 'redirect': '/login'})
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
@require_login
def index():
    return render_template('index.html')

@app.route('/auto_select')
@require_login
def auto_select():
    return render_template('auto_select.html')

@app.route('/monitor')
@require_login
def monitor():
    return render_template('monitor.html')

@app.route('/search_course', methods=['POST'])
@require_login
def search_course():
    try:
        data = request.get_json()
        course_name = data.get('course_name', '')
        campus = data.get('campus', '')
        course_code = data.get('course_code', '')
        class_name = data.get('class_name', '')
        teacher = data.get('teacher', '')
        course_type = data.get('course_type', '')
        course_property = data.get('course_property', '')
        admin_class = data.get('admin_class', '')
        compulsory = data.get('compulsory', '')
        only_available = data.get('only_available', False)

        ilist = login_state['ilist']
        cookies = login_state['cookies']

        result = []
        lesson_ids = []
        for i in ilist:
            course_campus = i.get('campus', {}).get('nameZh', '') if 'campus' in i else ''

            # 课程名称筛选（已有）
            if course_name and course_name not in i['course']['nameZh']:
                continue
            # 校区筛选（已有）
            if campus and campus != course_campus:
                continue
            # 课程代码/教学班代码筛选
            if course_code:
                lesson_code = i.get('code', '')
                course_code_val = i.get('course', {}).get('code', '')
                if course_code not in lesson_code and course_code not in course_code_val:
                    continue
            # 教学班名称筛选
            if class_name and class_name not in i.get('nameZh', ''):
                continue
            # 授课教师筛选
            if teacher:
                teachers_str = ','.join(t.get('nameZh', '') for t in i.get('teachers', []))
                if teacher not in teachers_str:
                    continue
            # 课程类型筛选
            if course_type and course_type != (i.get('courseType') or {}).get('nameZh', ''):
                continue
            # 课程性质筛选
            if course_property and course_property != (i.get('courseProperty') or {}).get('nameZh', ''):
                continue
            # 方案内课程筛选（按行政班）
            if admin_class:
                attend_classes = [a.get('nameZh', '') for a in i.get('attendAdminclasses', [])]
                if admin_class not in attend_classes:
                    continue
            # 必修/选修筛选
            if compulsory:
                compulsorys = i.get('compulsorys', [])
                if compulsory not in compulsorys:
                    continue

            teachers = ', '.join([t['nameZh'] for t in i['teachers']])

            # 获取选课组信息
            schedule_groups = []
            for group in i.get('scheduleGroups', []):
                group_info = {
                    'id': group['id'],
                    'no': group.get('no', 0),
                    'limitCount': group.get('limitCount', 0),
                    'default': group.get('default', False),
                    'timeText': ''
                }

                # 简化时间显示
                schedules = group.get('schedules', [])
                if schedules:
                    time_parts = []
                    for schedule in schedules:
                        weekday = schedule.get('weekday', 0)
                        start_unit = schedule.get('startUnit', 0)
                        end_unit = schedule.get('endUnit', 0)
                        weekday_map = {1: '周一', 2: '周二', 3: '周三', 4: '周四', 5: '周五', 6: '周六', 7: '周日'}
                        time_parts.append(f"{weekday_map.get(weekday, '')} 第{start_unit}-{end_unit}节")
                    group_info['timeText'] = '; '.join(time_parts)

                schedule_groups.append(group_info)

            result.append({
                "name": i['course']['nameZh'],
                "className": i.get('nameZh', ''),  # 教学班名称
                "code": i['code'],
                "id": i['id'],
                "teachers": teachers,
                "credits": i['course']['credits'],
                "capacity": i['limitCount'],
                "campus": course_campus,
                "scheduleGroups": schedule_groups,  # 添加选课组信息
                "courseType": (i.get('courseType') or {}).get('nameZh', ''),
                "courseProperty": (i.get('courseProperty') or {}).get('nameZh', ''),
                "compulsorys": i.get('compulsorys', [])
            })
            lesson_ids.append(i['id'])

        if lesson_ids:
            # 分批查询选课人数，每批 300 个，避免一次请求过多导致超时
            batch_size = 300
            selected_numbers = {}
            for batch_start in range(0, len(lesson_ids), batch_size):
                batch_ids = lesson_ids[batch_start:batch_start + batch_size]
                batch_result = get_selected_numbers(cookies, batch_ids)
                if isinstance(batch_result, dict):
                    selected_numbers.update(batch_result)
            # 确保 selected_numbers 是字典类型
            if isinstance(selected_numbers, dict):
                for course in result:
                    course_id = str(course['id'])
                    if course_id in selected_numbers:
                        selected_info = selected_numbers[course_id]
                        if isinstance(selected_info, str):
                            course['selected'] = selected_info.split('-')[0]
                            course['selected_full'] = selected_info
                        else:
                            course['selected'] = str(selected_info) if selected_info else '0'
                            course['selected_full'] = '0-0'
                    else:
                        course['selected'] = '0'
                        course['selected_full'] = '0-0'
            else:
                # API 返回非字典格式，设置默认值
                for course in result:
                    course['selected'] = '0'
                    course['selected_full'] = '0-0'

            # 计算余量并处理仅显示有余量的筛选
            if only_available:
                filtered_result = []
                for course in result:
                    selected_count = int(course.get('selected', '0'))
                    course['available'] = course['capacity'] - selected_count
                    if course['available'] > 0:
                        filtered_result.append(course)
                result = filtered_result
            else:
                for course in result:
                    selected_count = int(course.get('selected', '0'))
                    course['available'] = course['capacity'] - selected_count

        return jsonify({'success': True, 'courses': result})
    except Exception as e:
        return jsonify({'success': False, 'message': f'搜索失败: {str(e)}'})

@app.route('/select_course', methods=['POST'])
@require_login
def select_course_route():
    try:
        data = request.get_json()
        class_id = data.get('class_id')
        schedule_group_id = data.get('schedule_group_id')

        result = select_classes(
            login_state['cookies'],
            login_state['stu_id'],
            class_id,
            login_state['turn_id'],
            schedule_group_id
        )

        if result is True:
            return jsonify({'success': True, 'message': '选课成功'})
        else:
            error_msg = str(result) if result else "选课失败"
            return jsonify({'success': False, 'message': error_msg})
    except Exception as e:
        return jsonify({'success': False, 'message': f'选课失败: {str(e)}'})

@app.route('/drop_course', methods=['POST'])
@require_login
def drop_course_route():
    try:
        data = request.get_json()
        class_id = data.get('class_id')
        
        result = drop_classes(
            login_state['cookies'],
            login_state['stu_id'],
            class_id,
            login_state['turn_id']
        )
        
        if result is True:
            return jsonify({'success': True, 'message': '退课成功'})
        else:
            error_msg = str(result) if result else "退课失败"
            return jsonify({'success': False, 'message': error_msg})
    except Exception as e:
        return jsonify({'success': False, 'message': f'退课失败: {str(e)}'})

@app.route('/auto_select_with_drop', methods=['POST'])
@require_login
def auto_select_with_drop_route():
    """自动选课前先退课：退课失败不中断（课可能本来就没选），选课失败时尝试选回原课程"""
    try:
        data = request.get_json() or {}
        success, message = select_classes_with_drop(
            login_state['cookies'],
            login_state['stu_id'],
            data.get('class_id'),
            login_state['turn_id'],
            data.get('drop_class_id'),
            data.get('schedule_group_id')
        )
        return jsonify({'success': success, 'message': message})
    except Exception as e:
        return jsonify({'success': False, 'message': f'操作失败: {str(e)}'})

@app.route('/selected_courses')
@require_login
def selected_courses():
    try:
        selected = get_selected_classes(
            login_state['cookies'],
            login_state['stu_id'],
            login_state['turn_id']
        )
        
        courses = []
        lesson_ids = []
        for course in selected:
            teachers = ', '.join([t['nameZh'] for t in course['teachers']])
            course_campus = course.get('campus', {}).get('nameZh', '') if 'campus' in course else ''
            courses.append({
                "name": course['course']['nameZh'],
                "className": course.get('nameZh', ''),  # 教学班名称
                "code": course['code'],
                "id": course['id'],
                "teachers": teachers,
                "credits": course['course']['credits'],
                "campus": course_campus,
                "capacity": course['limitCount']
            })
            lesson_ids.append(course['id'])
        
        if lesson_ids:
            selected_numbers = get_selected_numbers(login_state['cookies'], lesson_ids)
            # 确保 selected_numbers 是字典类型
            if isinstance(selected_numbers, dict):
                for course in courses:
                    course_id = str(course['id'])
                    if course_id in selected_numbers:
                        selected_info = selected_numbers[course_id]
                        if isinstance(selected_info, str):
                            course['selected'] = selected_info.split('-')[0]
                            course['selected_full'] = selected_info
                        else:
                            course['selected'] = str(selected_info) if selected_info else '0'
                            course['selected_full'] = '0-0'
                    else:
                        course['selected'] = '0'
                        course['selected_full'] = '0-0'
            else:
                # API 返回非字典格式，设置默认值
                for course in courses:
                    course['selected'] = '0'
                    course['selected_full'] = '0-0'
        
        return jsonify({'success': True, 'courses': courses})
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取已选课程失败: {str(e)}'})

@app.route('/get_campuses')
@require_login
def get_campuses():
    try:
        ilist = login_state['ilist']
        campuses = set()
        for i in ilist:
            if 'campus' in i and 'nameZh' in i['campus']:
                campuses.add(i['campus']['nameZh'])
        return jsonify({'success': True, 'campuses': sorted(list(campuses))})
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取校区失败: {str(e)}'})

@app.route('/get_course_types')
@require_login
def get_course_types():
    """获取所有课程类型"""
    try:
        ilist = login_state['ilist']
        types = set()
        for i in ilist:
            ct = i.get('courseType')
            if ct and ct.get('nameZh'):
                types.add(ct['nameZh'])
        return jsonify({'success': True, 'types': sorted(list(types))})
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取课程类型失败: {str(e)}'})

@app.route('/get_course_properties')
@require_login
def get_course_properties():
    """获取所有课程性质"""
    try:
        ilist = login_state['ilist']
        properties = set()
        for i in ilist:
            cp = i.get('courseProperty')
            if cp and cp.get('nameZh'):
                properties.add(cp['nameZh'])
        return jsonify({'success': True, 'properties': sorted(list(properties))})
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取课程性质失败: {str(e)}'})

@app.route('/get_admin_classes')
@require_login
def get_admin_classes():
    """获取所有行政班（用于方案内课程筛选）"""
    try:
        ilist = login_state['ilist']
        classes = set()
        for i in ilist:
            for a in i.get('attendAdminclasses', []):
                if a.get('nameZh'):
                    classes.add(a['nameZh'])
        return jsonify({'success': True, 'classes': sorted(list(classes))})
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取行政班失败: {str(e)}'})

@app.route("/refresh_lesson_cache", methods=['GET'])
@require_login
def refresh_lesson_cache():
    global login_state
    try:
        ilist = get_itemList(login_state['cookies'], login_state['turn_id'])
        login_state['ilist'] = ilist
        with open(get_ilist_path(), "w", encoding="utf-8") as f:
            json.dump(ilist, f, ensure_ascii=False, indent=4)
        return jsonify({'success': True, 'message': '课程缓存已刷新'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'刷新课程缓存失败: {str(e)}'})

@app.route('/get_schedule_groups', methods=['POST'])
@require_login
def get_schedule_groups():
    """获取课程的选课组列表"""
    try:
        data = request.get_json()
        course_id = data.get('course_id')

        if not course_id:
            return jsonify({'success': False, 'message': '没有提供课程ID'})

        ilist = login_state['ilist']

        # 查找对应的课程
        course = None
        for item in ilist:
            if item['id'] == course_id:
                course = item
                break

        if not course:
            return jsonify({'success': False, 'message': '未找到该课程'})

        # 获取选课组列表
        schedule_groups = course.get('scheduleGroups', [])

        # 格式化选课组数据
        formatted_groups = []
        for group in schedule_groups:
            group_info = {
                'id': group['id'],
                'no': group.get('no', 0),
                'limitCount': group.get('limitCount', 0),
                'default': group.get('default', False),
                'dateTimePlace': group.get('dateTimePlace', {}).get('textZh', ''),
                'timeText': ''
            }

            # 简化时间显示
            schedules = group.get('schedules', [])
            if schedules:
                time_parts = []
                for schedule in schedules:
                    weekday = schedule.get('weekday', 0)
                    start_unit = schedule.get('startUnit', 0)
                    end_unit = schedule.get('endUnit', 0)
                    weekday_map = {1: '周一', 2: '周二', 3: '周三', 4: '周四', 5: '周五', 6: '周六', 7: '周日'}
                    time_parts.append(f"{weekday_map.get(weekday, '')} 第{start_unit}-{end_unit}节")
                group_info['timeText'] = '; '.join(time_parts)

            formatted_groups.append(group_info)

        return jsonify({
            'success': True,
            'schedule_groups': formatted_groups,
            'course_name': course.get('course', {}).get('nameZh', ''),
            'class_name': course.get('nameZh', '')
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取选课组失败: {str(e)}'})

def query_course_status(cookies, ilist, course_ids):
    """查询课程的选课人数与余量，返回 {课程ID: {selected, capacity, available}}"""
    selected_numbers = get_selected_numbers(cookies, course_ids)
    if not isinstance(selected_numbers, dict):
        selected_numbers = {}

    course_map = {c['id']: c for c in ilist}
    status = {}
    for course_id in course_ids:
        course_info = course_map.get(course_id)
        if not course_info:
            continue

        selected_info = selected_numbers.get(str(course_id))
        if isinstance(selected_info, str):
            selected_count = int(selected_info.split('-')[0])
        elif selected_info:
            selected_count = int(selected_info)
        else:
            selected_count = 0

        capacity = course_info['limitCount']
        status[course_id] = {
            'id': course_id,
            'name': course_info['course']['nameZh'],
            'code': course_info['code'],
            'teachers': ', '.join([t['nameZh'] for t in course_info['teachers']]),
            'campus': course_info.get('campus', {}).get('nameZh', '') if 'campus' in course_info else '',
            'selected': selected_count,
            'capacity': capacity,
            'available': capacity - selected_count
        }
    return status

@app.route('/check_course_availability', methods=['POST'])
@require_login
def check_course_availability():
    try:
        data = request.get_json()
        course_ids = data.get('course_ids', [])

        if not course_ids:
            return jsonify({'success': False, 'message': '没有提供课程ID'})

        status = query_course_status(login_state['cookies'], login_state['ilist'], course_ids)
        available_courses = [s for s in status.values() if s['available'] > 0]

        return jsonify({
            'success': True,
            'available_courses': available_courses,
            'total_monitored': len(course_ids)
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'检查课程余量失败: {str(e)}'})

# ============ 后台任务（抢课 / 监控）============
# 任务跑在服务端线程里，页面只负责展示，切换页面或刷新都不会中断任务

class TaskLog:
    """线程安全的日志缓冲区，支持按序号增量拉取"""

    def __init__(self, maxlen=500):
        self._lock = threading.Lock()
        self._entries = []   # [(seq, text)]
        self._seq = 0
        self._generation = 0
        self._maxlen = maxlen

    def add(self, message):
        with self._lock:
            self._seq += 1
            self._entries.append((self._seq, f"[{time.strftime('%H:%M:%S')}] {message}"))
            if len(self._entries) > self._maxlen:
                del self._entries[:len(self._entries) - self._maxlen]

    def read(self, since=0):
        with self._lock:
            if since < 0 or since > self._seq:
                since = 0
            return {
                'generation': self._generation,
                'seq': self._seq,
                'lines': [text for seq, text in self._entries if seq > since]
            }

    def clear(self):
        with self._lock:
            self._entries = []
            self._generation += 1


class AutoSelectTask:
    """自动抢课任务：按队列循环执行选课/退课，支持顺序与并发模式、定时启动"""

    def __init__(self):
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread = None
        self.log = TaskLog()
        self.operations = []
        self.state = 'idle'          # idle / scheduled / running
        self.schedule_at = None      # 预定启动时间（epoch 秒）
        self.interval = 0
        self.mode = 'sequential'
        self.thread_count = 5
        self.success_count = 0
        self.round_count = 0

    # ---- 队列管理（任务运行中不允许改动，与原前端行为一致）----

    def add_operation(self, operation):
        with self._lock:
            if self.state != 'idle':
                return False, '任务运行中，无法修改队列'
            for op in self.operations:
                if op['course_id'] == operation['course_id'] and op['type'] == operation['type']:
                    return False, '该操作已存在'
            self.operations.append(operation)
            return True, ''

    def remove_operation(self, index):
        with self._lock:
            if self.state != 'idle':
                return False, '任务运行中，无法修改队列'
            if 0 <= index < len(self.operations):
                self.operations.pop(index)
            return True, ''

    def clear_operations(self):
        with self._lock:
            if self.state != 'idle':
                return False, '任务运行中，无法修改队列'
            self.operations = []
            return True, ''

    # ---- 启停 ----

    def start(self, interval=0, mode='sequential', thread_count=5, schedule_at=None):
        with self._lock:
            if self.state != 'idle':
                return False, '任务已在运行'
            if not self.operations:
                return False, '请先添加操作'

            self.interval = max(0, int(interval or 0))
            self.mode = 'parallel' if mode == 'parallel' else 'sequential'
            self.thread_count = min(20, max(1, int(thread_count or 1)))
            self.success_count = 0
            self.round_count = 0

            if schedule_at and schedule_at > time.time():
                self.schedule_at = float(schedule_at)
                self.state = 'scheduled'
            else:
                self.schedule_at = None
                self.state = 'running'

            stop_event = threading.Event()
            self._stop_event = stop_event
            self._thread = threading.Thread(target=self._run, args=(stop_event,), daemon=True)
            self._thread.start()
            return True, ''

    def stop(self):
        with self._lock:
            if self.state == 'idle':
                return False, '任务未在运行'
            self._stop_event.set()
            return True, ''

    def reset(self):
        """登出/重新登录时：停止任务并清空队列与日志"""
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=5)
        with self._lock:
            self.state = 'idle'
            self.schedule_at = None
            self.operations = []
        self.log.clear()

    def status(self, since=0):
        with self._lock:
            return {
                'state': self.state,
                'schedule_at': self.schedule_at,
                'server_time': time.time(),
                'operations': list(self.operations),
                'config': {
                    'interval': self.interval,
                    'mode': self.mode,
                    'thread_count': self.thread_count
                },
                'success_count': self.success_count,
                'round_count': self.round_count,
                'log': self.log.read(since)
            }

    # ---- 执行 ----

    def _run(self, stop_event):
        try:
            if self.schedule_at:
                self.log.add(f"队列已预定，将在 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.schedule_at))} 启动")
                while not stop_event.is_set():
                    remaining = self.schedule_at - time.time()
                    if remaining <= 0:
                        break
                    stop_event.wait(min(1.0, remaining))
                if stop_event.is_set():
                    return
                with self._lock:
                    self.state = 'running'
                self.log.add('预定时间到达，开始执行队列...')

            mode = self.mode
            self.log.add(f"队列开始运行... ({'并发' if mode == 'parallel' else '顺序'}模式)")

            if mode == 'parallel':
                workers = [
                    threading.Thread(target=self._worker_loop, args=(i + 1, stop_event), daemon=True)
                    for i in range(self.thread_count)
                ]
                for worker in workers:
                    worker.start()
                for worker in workers:
                    worker.join()
            else:
                self._worker_loop(None, stop_event)
        except Exception as e:
            self.log.add(f'❌ 任务异常终止: {str(e)}')
        finally:
            with self._lock:
                stale = self._stop_event is not stop_event   # 已被新任务取代
                if not stale:
                    self.state = 'idle'
                    self.schedule_at = None
            if not stale:
                self.log.add('队列已停止')

    def _worker_loop(self, thread_id, stop_event):
        prefix = f'线程{thread_id}: ' if thread_id else ''
        while not stop_event.is_set():
            with self._lock:
                operations = list(self.operations)
            if not operations:
                self.log.add(f'{prefix}队列为空，停止执行')
                stop_event.set()
                break

            for operation in operations:
                if stop_event.is_set():
                    break
                self._execute(operation, prefix)
                if thread_id and not stop_event.is_set():
                    stop_event.wait(0.05)

            if stop_event.is_set():
                break
            with self._lock:
                self.round_count += 1
            if self.interval > 0:
                self.log.add(f'{prefix}一轮完成，等待 {self.interval} 秒后重新开始...')
                stop_event.wait(self.interval)

    def _execute(self, operation, prefix):
        action = '选课' if operation['type'] == 'select' else '退课'
        name = operation.get('course_name', '')
        try:
            if operation['type'] == 'select':
                result = select_classes(
                    login_state['cookies'], login_state['stu_id'],
                    operation['course_id'], login_state['turn_id'],
                    operation.get('schedule_group_id')
                )
            else:
                result = drop_classes(
                    login_state['cookies'], login_state['stu_id'],
                    operation['course_id'], login_state['turn_id']
                )

            if result is True:
                with self._lock:
                    self.success_count += 1
                self.log.add(f'{prefix}✅ 成功: {action} - {name}')
            else:
                message = result.get('error') if isinstance(result, dict) else str(result)
                self.log.add(f'{prefix}❌ 失败: {action} - {name} - {message}')
        except Exception as e:
            self.log.add(f'{prefix}❌ 错误: {action} - {name} - {str(e)}')


class MonitorTask:
    """余量监控任务：轮询课程余量，可选自动抢课"""

    def __init__(self):
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread = None
        self.log = TaskLog()
        self.courses = []
        self.running = False
        self.interval = 5
        self.auto_select = False
        self.drop_class_id = None
        self.drop_class_name = ''
        self.check_count = 0
        self.success_count = 0

    # ---- 监控列表 ----

    def add_course(self, course):
        with self._lock:
            if self.running:
                return False, '监控运行中，无法修改列表'
            if any(c['id'] == course['id'] for c in self.courses):
                return False, '该课程已在监控列表中'
            course.update({'selected': 0, 'available': 0, 'last_check': None})
            self.courses.append(course)
            return True, ''

    def remove_course(self, index):
        with self._lock:
            if self.running:
                return False, '监控运行中，无法修改列表'
            if 0 <= index < len(self.courses):
                self.courses.pop(index)
            return True, ''

    def clear_courses(self):
        with self._lock:
            if self.running:
                return False, '监控运行中，无法修改列表'
            self.courses = []
            return True, ''

    # ---- 启停 ----

    def start(self, interval=5, auto_select=False, drop_class_id=None, drop_class_name=''):
        with self._lock:
            if self.running:
                return False, '监控已在运行'
            if not self.courses:
                return False, '请先添加要监控的课程'
            if drop_class_id and any(str(c['id']) == str(drop_class_id) for c in self.courses):
                return False, '要退的课程与监控目标相同'
            self.interval = max(1, int(interval or 1))
            self.auto_select = bool(auto_select)
            self.drop_class_id = drop_class_id
            self.drop_class_name = drop_class_name or ''
            self.check_count = 0
            self.success_count = 0
            self.running = True
            if self.drop_class_id:
                self.log.add(f'📋 已设置先退课: {self.drop_class_name} (ID: {self.drop_class_id})')
            stop_event = threading.Event()
            self._stop_event = stop_event
            self._thread = threading.Thread(target=self._run, args=(stop_event,), daemon=True)
            self._thread.start()
            return True, ''

    def stop(self):
        with self._lock:
            if not self.running:
                return False, '监控未在运行'
            self._stop_event.set()
            return True, ''

    def reset(self):
        """登出/重新登录时：停止监控并清空列表与日志"""
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=5)
        with self._lock:
            self.running = False
            self.courses = []
            self.drop_class_id = None
            self.drop_class_name = ''
        self.log.clear()

    def status(self, since=0):
        with self._lock:
            return {
                'running': self.running,
                'courses': list(self.courses),
                'config': {
                    'interval': self.interval,
                    'auto_select': self.auto_select,
                    'drop_class_id': self.drop_class_id,
                    'drop_class_name': self.drop_class_name
                },
                'check_count': self.check_count,
                'success_count': self.success_count,
                'log': self.log.read(since)
            }

    # ---- 执行 ----

    def _run(self, stop_event):
        self.log.add('🚀 开始监控课程余量...')
        try:
            while not stop_event.is_set():
                self._check_once(stop_event)
                if stop_event.is_set():
                    break
                stop_event.wait(self.interval)
        except Exception as e:
            self.log.add(f'❌ 监控异常终止: {str(e)}')
        finally:
            with self._lock:
                stale = self._stop_event is not stop_event   # 已被新任务取代
                if not stale:
                    self.running = False
            if not stale:
                self.log.add('⏸️ 监控已停止')

    def _check_once(self, stop_event):
        with self._lock:
            course_ids = [c['id'] for c in self.courses]
        if not course_ids:
            self.log.add('✅ 没有待监控课程，已自动停止')
            stop_event.set()
            return

        with self._lock:
            self.check_count += 1

        try:
            status = query_course_status(login_state['cookies'], login_state['ilist'], course_ids)
        except Exception as e:
            self.log.add(f'❌ 检查出错: {str(e)}')
            return

        timestamp = time.strftime('%H:%M:%S')
        with self._lock:
            for course in self.courses:
                info = status.get(course['id'])
                if info:
                    course['selected'] = info['selected']
                    course['available'] = info['available']
                    course['capacity'] = info['capacity']
                course['last_check'] = timestamp

        available = [info for info in status.values() if info['available'] > 0]
        if not available:
            self.log.add('🔍 检查完成，暂无余量')
            return

        self.log.add(f'🟢 发现 {len(available)} 门课程有余量!')
        if not self.auto_select:
            for info in available:
                self.log.add(f"💡 {info['name']} 有 {info['available']} 个余量")
            return

        for info in available:
            if stop_event.is_set():
                break
            self._attempt_select(info, stop_event)

    def _attempt_select(self, info, stop_event):
        course_id = info['id']
        name = info['name']
        with self._lock:
            monitored = next((c for c in self.courses if c['id'] == course_id), None)
            drop_class_id = self.drop_class_id
            drop_class_name = self.drop_class_name
        schedule_group_id = monitored.get('schedule_group_id') if monitored else None

        self.log.add(f'🎯 尝试自动选课: {name}')
        try:
            if drop_class_id is not None:
                self.log.add(f'🔄 先退 {drop_class_name}(ID:{drop_class_id}) → 再选 {name}')
                success, message = select_classes_with_drop(
                    login_state['cookies'], login_state['stu_id'],
                    course_id, login_state['turn_id'], drop_class_id, schedule_group_id
                )
            else:
                result = select_classes(
                    login_state['cookies'], login_state['stu_id'],
                    course_id, login_state['turn_id'], schedule_group_id
                )
                success = result is True
                message = '自动选课成功' if success else (
                    result.get('error') if isinstance(result, dict) else str(result)
                )

            if success:
                with self._lock:
                    self.success_count += 1
                    self.courses = [c for c in self.courses if c['id'] != course_id]
                    remaining = len(self.courses)
                    if drop_class_id is not None:
                        self.drop_class_id = None
                        self.drop_class_name = ''
                self.log.add(f'🎉 {name}: {message}' if drop_class_id is not None else f'🎉 自动选课成功: {name}')
                if remaining == 0:
                    self.log.add('✅ 监控课程已全部选上，自动停止')
                    stop_event.set()
            else:
                self.log.add(f'❌ 自动选课失败: {name} - {message}')
        except Exception as e:
            self.log.add(f'❌ 自动选课出错: {name} - {str(e)}')


auto_select_task = AutoSelectTask()
monitor_task = MonitorTask()


def reset_background_tasks():
    """停止并清空所有后台任务（登出、重新登录时调用）"""
    auto_select_task.reset()
    monitor_task.reset()


# ============ 后台任务 API ============

def _since_param():
    try:
        return int(request.args.get('since', 0))
    except (TypeError, ValueError):
        return 0

@app.route('/api/auto_select/status')
@require_login
def api_auto_select_status():
    return jsonify({'success': True, **auto_select_task.status(_since_param())})

@app.route('/api/auto_select/operations/add', methods=['POST'])
@require_login
def api_auto_select_add():
    data = request.get_json()
    operation = {
        'course_id': data.get('course_id'),
        'type': data.get('type'),
        'course_name': data.get('course_name', ''),
        'schedule_group_id': data.get('schedule_group_id')
    }
    if operation['course_id'] is None or operation['type'] not in ('select', 'drop'):
        return jsonify({'success': False, 'message': '参数错误'})
    ok, message = auto_select_task.add_operation(operation)
    return jsonify({'success': ok, 'message': message})

@app.route('/api/auto_select/operations/remove', methods=['POST'])
@require_login
def api_auto_select_remove():
    data = request.get_json()
    ok, message = auto_select_task.remove_operation(int(data.get('index', -1)))
    return jsonify({'success': ok, 'message': message})

@app.route('/api/auto_select/operations/clear', methods=['POST'])
@require_login
def api_auto_select_clear():
    ok, message = auto_select_task.clear_operations()
    return jsonify({'success': ok, 'message': message})

@app.route('/api/auto_select/start', methods=['POST'])
@require_login
def api_auto_select_start():
    data = request.get_json() or {}
    ok, message = auto_select_task.start(
        interval=data.get('interval', 0),
        mode=data.get('mode', 'sequential'),
        thread_count=data.get('thread_count', 5),
        schedule_at=data.get('schedule_at')
    )
    return jsonify({'success': ok, 'message': message})

@app.route('/api/auto_select/stop', methods=['POST'])
@require_login
def api_auto_select_stop():
    ok, message = auto_select_task.stop()
    return jsonify({'success': ok, 'message': message})

@app.route('/api/auto_select/logs/clear', methods=['POST'])
@require_login
def api_auto_select_clear_logs():
    auto_select_task.log.clear()
    return jsonify({'success': True})

@app.route('/api/monitor/status')
@require_login
def api_monitor_status():
    return jsonify({'success': True, **monitor_task.status(_since_param())})

@app.route('/api/monitor/courses/add', methods=['POST'])
@require_login
def api_monitor_add():
    data = request.get_json()
    if data.get('id') is None:
        return jsonify({'success': False, 'message': '参数错误'})
    course = {
        'id': data.get('id'),
        'name': data.get('name', ''),
        'code': data.get('code', ''),
        'teachers': data.get('teachers', ''),
        'campus': data.get('campus', ''),
        'capacity': data.get('capacity', 0),
        'schedule_group_id': data.get('schedule_group_id')
    }
    ok, message = monitor_task.add_course(course)
    return jsonify({'success': ok, 'message': message})

@app.route('/api/monitor/courses/remove', methods=['POST'])
@require_login
def api_monitor_remove():
    data = request.get_json()
    ok, message = monitor_task.remove_course(int(data.get('index', -1)))
    return jsonify({'success': ok, 'message': message})

@app.route('/api/monitor/courses/clear', methods=['POST'])
@require_login
def api_monitor_clear():
    ok, message = monitor_task.clear_courses()
    return jsonify({'success': ok, 'message': message})

@app.route('/api/monitor/start', methods=['POST'])
@require_login
def api_monitor_start():
    data = request.get_json() or {}
    ok, message = monitor_task.start(
        interval=data.get('interval', 5),
        auto_select=data.get('auto_select', False),
        drop_class_id=data.get('drop_class_id'),
        drop_class_name=data.get('drop_class_name', '')
    )
    return jsonify({'success': ok, 'message': message})

@app.route('/api/monitor/stop', methods=['POST'])
@require_login
def api_monitor_stop():
    ok, message = monitor_task.stop()
    return jsonify({'success': ok, 'message': message})

@app.route('/api/monitor/logs/clear', methods=['POST'])
@require_login
def api_monitor_clear_logs():
    monitor_task.log.clear()
    return jsonify({'success': True})


def find_free_port(start_port=5001, max_attempts=10):
    """找到一个可用的端口"""
    import socket
    for port in range(start_port, start_port + max_attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', port))
                return port
        except OSError:
            continue
    return None

if __name__ == '__main__':
    import webbrowser
    port = find_free_port(5001)
    if port:
        url = f"http://127.0.0.1:{port}/login"
        print(f"启动服务器: {url}")
        # 延迟打开浏览器
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
        app.run(debug=False, host='0.0.0.0', port=port)
    else:
        print("错误: 无法找到可用端口 (5001-5010)")
        import sys
        sys.exit(1)
