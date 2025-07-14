from flask import Flask, render_template, request, jsonify
import json
import threading
import time
from main import *

app = Flask(__name__)

# 使用main.py中已经初始化的登录信息
# cookies, stu_id, turn_id, ilist 已经在main.py中定义

# 全局变量用于控制抢课脚本状态和日志
auto_script_running = False
auto_script_thread = None
operation_logs = []  # 存储操作日志
log_lock = threading.Lock()  # 线程锁保护日志访问

def add_log(message, log_type='info', course_info=None):
    """添加操作日志"""
    with log_lock:
        log_entry = {
            'timestamp': time.time(),
            'message': message,
            'type': log_type,  # info, success, error, warning
            'course_info': course_info,
            'formatted_time': time.strftime('%H:%M:%S', time.localtime())
        }
        operation_logs.append(log_entry)
        # 保持最多100条日志
        if len(operation_logs) > 100:
            operation_logs.pop(0)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/auto_select')
def auto_select():
    return render_template('auto_select.html')

@app.route('/search_course', methods=['POST'])
def search_course():
    try:
        data = request.get_json()
        course_name = data.get('course_name', '')
        campus = data.get('campus', '')
        
        # 搜索课程
        result = []
        lesson_ids = []
        for i in ilist:
            # 校区筛选
            course_campus = i.get('campus', {}).get('nameZh', '') if 'campus' in i else ''
            
            # 课程名称匹配 + 校区筛选
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
        
        # 获取已选人数
        if lesson_ids:
            selected_numbers = get_selected_numbers(lesson_ids)
            for course in result:
                course_id = str(course['id'])
                if course_id in selected_numbers:
                    # 格式为"已选人数-候补人数"
                    selected_info = selected_numbers[course_id]
                    course['selected'] = selected_info.split('-')[0]  # 只显示已选人数
                    course['selected_full'] = selected_info  # 完整信息"已选-候补"
                else:
                    course['selected'] = '0'
                    course['selected_full'] = '0-0'
        
        return jsonify({'success': True, 'courses': result})
    except Exception as e:
        return jsonify({'success': False, 'message': f'搜索失败: {str(e)}'})

@app.route('/select_course', methods=['POST'])
def select_course():
    try:
        data = request.get_json()
        class_id = data.get('class_id')
        
        # 选课
        result = select_classes(class_id, turn_id)
        if result is True:
            add_log(f"成功选课: {class_id}", log_type='success')
            return jsonify({'success': True, 'message': '选课成功'})
        else:
            # result为False或错误信息
            error_msg = "选课失败，未知错误"
            if isinstance(result, dict):
                try:
                    error_msg = result
                except Exception:
                    pass
            elif isinstance(result, str):
                error_msg = result
            add_log(f"选课失败: {error_msg}", log_type='error', course_info={'class_id': class_id})
            return jsonify({'success': False, 'message': error_msg})
    except Exception as e:
        return jsonify({'success': False, 'message': f'选课失败: {str(e)}'})

@app.route('/drop_course', methods=['POST'])
def drop_course():
    try:
        data = request.get_json()
        class_id = data.get('class_id')
        
        # 退课
        result = drop_classes(class_id, turn_id)
        if result is True:
            add_log(f"成功退课: {class_id}", log_type='success')
            return jsonify({'success': True, 'message': '退课成功'})
        else:
            # result为False或错误信息
            error_msg = "退课失败，未知错误"
            if isinstance(result, dict):
                try:
                    error_msg = result
                except Exception:
                    pass
            elif isinstance(result, str):
                error_msg = result
            add_log(f"退课失败: {error_msg}", log_type='error', course_info={'class_id': class_id})
            return jsonify({'success': False, 'message': error_msg})
    except Exception as e:
        return jsonify({'success': False, 'message': f'退课失败: {str(e)}'})

@app.route('/selected_courses')
def selected_courses():
    try:
        # 获取已选课程
        selected = get_selected_classes(turn_id)
        
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
        
        # 获取已选人数
        if lesson_ids:
            selected_numbers = get_selected_numbers(lesson_ids)
            for course in courses:
                course_id = str(course['id'])
                if course_id in selected_numbers:
                    # 格式为"已选人数-候补人数"
                    selected_info = selected_numbers[course_id]
                    course['selected'] = selected_info.split('-')[0]  # 只显示已选人数
                    course['selected_full'] = selected_info  # 完整信息"已选-候补"
                else:
                    course['selected'] = '0'
                    course['selected_full'] = '0-0'
        
        return jsonify({'success': True, 'courses': courses})
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取已选课程失败: {str(e)}'})


@app.route('/get_campuses')
def get_campuses():
    try:
        campuses = set()
        for i in ilist:
            if 'campus' in i and 'nameZh' in i['campus']:
                campuses.add(i['campus']['nameZh'])
        return jsonify({'success': True, 'campuses': sorted(list(campuses))})
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取校区失败: {str(e)}'})

@app.route("/refresh_lesson_cache", methods=['GET'])
def refresh_lesson_cache():
    try:
        global ilist
        ilist = get_itemList(turn_id)  # 重新获取课程列表
        ilist = json.loads(ilist)
        with open("ilist.json", "w", encoding="utf-8") as f:
            json.dump(ilist, f, ensure_ascii=False, indent=4)
        return jsonify({'success': True, 'message': '课程缓存已刷新'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'刷新课程缓存失败: {str(e)}'})

@app.route('/start_auto_script', methods=['POST'])
def start_auto_script():
    global auto_script_running, auto_script_thread
    
    if auto_script_running:
        return jsonify({'success': False, 'message': '脚本已在运行中'})
    
    try:
        data = request.get_json()
        operations = data.get('operations', [])
        interval = data.get('interval', 2)
        
        if not operations:
            return jsonify({'success': False, 'message': '操作列表不能为空'})
        
        # 验证操作格式
        for op in operations:
            if 'type' not in op or 'course_id' not in op:
                return jsonify({'success': False, 'message': '操作格式错误'})
            if op['type'] not in ['select', 'drop']:
                return jsonify({'success': False, 'message': f'无效的操作类型: {op["type"]}'})
        
        # 启动后台线程执行抢课脚本
        auto_script_running = True
        auto_script_thread = threading.Thread(
            target=run_auto_script_background,
            args=(operations, interval)
        )
        auto_script_thread.daemon = True
        auto_script_thread.start()
        
        add_log(f"抢课脚本已启动，操作数: {len(operations)}，间隔: {interval}秒", log_type='info')
        return jsonify({'success': True, 'message': '抢课脚本已启动'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'启动脚本失败: {str(e)}'})

@app.route('/stop_auto_script', methods=['POST'])
def stop_auto_script():
    global auto_script_running
    
    if not auto_script_running:
        return jsonify({'success': False, 'message': '脚本未在运行'})
    
    auto_script_running = False
    add_log(f"抢课脚本已请求停止", log_type='info')
    return jsonify({'success': True, 'message': '正在停止脚本...'})

@app.route('/script_status')
def script_status():
    return jsonify({
        'running': auto_script_running,
        'thread_alive': auto_script_thread.is_alive() if auto_script_thread else False
    })

@app.route('/get_operation_logs')
def get_operation_logs():
    """获取操作日志"""
    start_index = request.args.get('start_index', 0, type=int)
    
    with log_lock:
        # 返回从指定索引开始的新日志
        new_logs = operation_logs[start_index:] if start_index < len(operation_logs) else []
        return jsonify({
            'success': True,
            'logs': new_logs,
            'total_count': len(operation_logs)
        })

@app.route('/clear_logs', methods=['POST'])
def clear_logs():
    """清空操作日志"""
    global operation_logs
    with log_lock:
        operation_logs = []
    return jsonify({'success': True, 'message': '日志已清空'})

def run_auto_script_background(operations, interval):
    """后台运行抢课脚本"""
    global auto_script_running
    
    def should_stop():
        return not auto_script_running
    
    try:
        add_log(f"开始执行自动抢课脚本，共 {len(operations)} 个操作", 'info')
        
        # 转换操作格式并添加课程信息
        formatted_operations = []
        for op in operations:
            # 添加操作验证
            if not isinstance(op, dict) or 'course_id' not in op or 'type' not in op:
                add_log(f"❌ 无效的操作格式: {op}", 'error')
                continue
                
            # 查找课程信息
            course_info = {}  # 默认为空字典而不是None
            try:
                for course in ilist:
                    if course['id'] == op['course_id']:
                        course_info = {
                            'name': course['course']['nameZh'],
                            'code': course['code'],
                            'teachers': ', '.join([t['nameZh'] for t in course['teachers']])
                        }
                        break
            except Exception as e:
                add_log(f"❌ 查找课程信息时出错: {str(e)}", 'error')
                course_info = {'name': f"课程ID:{op['course_id']}"}
            
            formatted_operations.append({
                'type': op['type'],
                'class_id': op['course_id'],
                'course_info': course_info
            })
        
        # 执行持续操作（修改后的版本）
        success, attempts = continuous_operations_with_log(
            formatted_operations, 
            interval=interval, 
            max_attempts=None,  # 无限制尝试
            stop_check=should_stop,
            log_callback=add_log
        )
        
        if success:
            add_log(f"✅ 所有操作在第 {attempts} 次尝试后完成", 'success')
        else:
            add_log(f"⏹️ 脚本被手动停止", 'warning')
            
    except Exception as e:
        add_log(f"❌ 抢课脚本执行出错: {str(e)}", 'error')
    finally:
        auto_script_running = False
        add_log("脚本执行结束", 'info')

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
