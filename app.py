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
        r1 = requests.post(url, json=data, cookies=cookies)
        uuid1 = r1.text

        url1 = "http://jxgl.dlut.edu.cn/student/ws/for-std/course-select/add-drop-response"
        data1 = {"studentId": stu_id, "requestId": uuid1}
        r2 = requests.post(url1, data=data1, cookies=cookies)

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
        r1 = requests.post(url, json=data, cookies=cookies)
        uuid1 = r1.text
        
        url1 = "http://jxgl.dlut.edu.cn/student/ws/for-std/course-select/add-drop-response"
        data1 = {"studentId": stu_id, "requestId": uuid1}
        r2 = requests.post(url1, data=data1, cookies=cookies)
        
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

def get_selected_classes(cookies, stu_id, turn_id):
    """获取已选课程"""
    url = "http://jxgl.dlut.edu.cn/student/ws/for-std/course-select/selected-lessons"
    data = {"studentId": stu_id, "turnId": turn_id}
    r = requests.post(url, data=data, cookies=cookies)
    return json.loads(r.text)

def get_selected_numbers(cookies, lesson_ids):
    """获取选课人数"""
    url = "http://jxgl.dlut.edu.cn/student/ws/for-std/course-select/std-count"
    data = [("lessonIds[]", lid) for lid in lesson_ids]
    r = requests.post(url, data=data, cookies=cookies)
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

        ilist = login_state['ilist']
        cookies = login_state['cookies']

        result = []
        lesson_ids = []
        for i in ilist:
            course_campus = i.get('campus', {}).get('nameZh', '') if 'campus' in i else ''
            if course_name in i['course']['nameZh'] and (not campus or campus == course_campus):
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
                    "scheduleGroups": schedule_groups  # 添加选课组信息
                })
                lesson_ids.append(i['id'])

        if lesson_ids:
            selected_numbers = get_selected_numbers(cookies, lesson_ids)
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

@app.route('/check_course_availability', methods=['POST'])
@require_login
def check_course_availability():
    try:
        data = request.get_json()
        course_ids = data.get('course_ids', [])
        
        if not course_ids:
            return jsonify({'success': False, 'message': '没有提供课程ID'})
        
        cookies = login_state['cookies']
        ilist = login_state['ilist']
        
        selected_numbers = get_selected_numbers(cookies, course_ids)
        
        available_courses = []
        for course_id in course_ids:
            course_id_str = str(course_id)
            if course_id_str in selected_numbers:
                selected_info = selected_numbers[course_id_str]
                selected_count = int(selected_info.split('-')[0])
                
                course_info = None
                for course in ilist:
                    if course['id'] == course_id:
                        course_info = course
                        break
                
                if course_info:
                    capacity = course_info['limitCount']
                    available_spots = capacity - selected_count
                    
                    if available_spots > 0:
                        teachers = ', '.join([t['nameZh'] for t in course_info['teachers']])
                        course_campus = course_info.get('campus', {}).get('nameZh', '') if 'campus' in course_info else ''
                        available_courses.append({
                            'id': course_id,
                            'name': course_info['course']['nameZh'],
                            'code': course_info['code'],
                            'teachers': teachers,
                            'campus': course_campus,
                            'selected': selected_count,
                            'capacity': capacity,
                            'available': available_spots
                        })
        
        return jsonify({
            'success': True,
            'available_courses': available_courses,
            'total_monitored': len(course_ids)
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'检查课程余量失败: {str(e)}'})

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
