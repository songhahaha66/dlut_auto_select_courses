from flask import Flask, render_template, request, jsonify, redirect, session
import json
import threading
import time
import dlut_sso
import requests
import re

app = Flask(__name__)
app.secret_key = 'dlut_course_select_secret_key_2024'

# 全局变量存储登录状态
login_state = {
    'logged_in': False,
    'cookies': None,
    'stu_id': None,
    'turn_id': None,
    'ilist': None
}

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

def get_student_id(cookies):
    """获取学生ID"""
    url = "http://jxgl.dlut.edu.cn/student/for-std/course-select/single-student/turns"
    html = requests.get(url, cookies=cookies).text
    match = re.search(r'studentId\s*:\s*(\d+),', html)
    if match:
        return int(match.group(1))
    return None

def get_open_turns(cookies, stu_id):
    """获取所有可用的选课轮次"""
    url = "http://jxgl.dlut.edu.cn/student/ws/for-std/course-select/open-turns"
    data = {"bizTypeId": "2", "studentId": stu_id}
    r = requests.post(url, data=data, cookies=cookies)
    return json.loads(r.text)

def get_itemList(cookies, turn_id):
    """获取课程列表"""
    url = f"http://jxgl.dlut.edu.cn/student/cache/course-select/version/{turn_id}/version.json"
    r = requests.get(url, cookies=cookies)
    data = json.loads(r.text)
    a = data['itemList'][0]
    url1 = f"http://cdn-dlut.supwisdom.com/student/cache/course-select/addable-lessons/{turn_id}/{a}.json"
    return json.loads(requests.get(url1, cookies=cookies).text)['data']

def select_classes(cookies, stu_id, class_id, turn_id):
    """选课"""
    try:
        url = "http://jxgl.dlut.edu.cn/student/ws/for-std/course-select/add-request"
        data = {"studentAssoc": stu_id, "courseSelectTurnAssoc": turn_id,
                "requestMiddleDtos": [{"lessonAssoc": class_id, "virtualCost": 0, "scheduleGroupAssoc": None}]}
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
    """登录API"""
    global login_state
    
    try:
        data = request.get_json()
        userid = data.get('userid')
        password = data.get('password')
        turn_id = data.get('turn_id')  # 直接使用选择的 turn_id
        
        # 登录
        cookies = jw_login(userid, password)
        stu_id = get_student_id(cookies)
        
        if not stu_id:
            return jsonify({'success': False, 'message': '获取学生ID失败'})
        
        # 如果没有传 turn_id，获取第一个可用的
        if not turn_id:
            turns = get_open_turns(cookies, stu_id)
            if not turns:
                return jsonify({'success': False, 'message': '没有可用的选课轮次'})
            turn_id = turns[0]['id']
        
        # 获取课程列表
        try:
            with open("ilist.json", "r", encoding="utf-8") as f:
                ilist = json.load(f)
        except FileNotFoundError:
            ilist = get_itemList(cookies, turn_id)
            with open("ilist.json", "w", encoding="utf-8") as f:
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
        
        # 登录获取 cookies
        cookies = jw_login(userid, password)
        stu_id = get_student_id(cookies)
        
        if not stu_id:
            return jsonify({'success': False, 'message': '获取学生ID失败，请检查账号密码'})
        
        # 获取可用轮次
        turns = get_open_turns(cookies, stu_id)
        
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
                result.append({
                    "name": i['course']['nameZh'],
                    "code": i['code'],
                    "id": i['id'],
                    "teachers": teachers,
                    "credits": i['course']['credits'],
                    "capacity": i['limitCount'],
                    "campus": course_campus
                })
                lesson_ids.append(i['id'])
        
        if lesson_ids:
            selected_numbers = get_selected_numbers(cookies, lesson_ids)
            for course in result:
                course_id = str(course['id'])
                if course_id in selected_numbers:
                    selected_info = selected_numbers[course_id]
                    course['selected'] = selected_info.split('-')[0]
                    course['selected_full'] = selected_info
                else:
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
        
        result = select_classes(
            login_state['cookies'],
            login_state['stu_id'],
            class_id,
            login_state['turn_id']
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
            for course in courses:
                course_id = str(course['id'])
                if course_id in selected_numbers:
                    selected_info = selected_numbers[course_id]
                    course['selected'] = selected_info.split('-')[0]
                    course['selected_full'] = selected_info
                else:
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
        with open("ilist.json", "w", encoding="utf-8") as f:
            json.dump(ilist, f, ensure_ascii=False, indent=4)
        return jsonify({'success': True, 'message': '课程缓存已刷新'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'刷新课程缓存失败: {str(e)}'})

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

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
