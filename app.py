from flask import Flask, render_template, request, jsonify
import json
import threading
import time
from main import *

app = Flask(__name__)

# 使用main.py中已经初始化的登录信息
# cookies, stu_id, turn_id, ilist 已经在main.py中定义

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
            return jsonify({'success': True, 'message': '选课成功'})
        else:
            error_msg = str(result) if result else "选课失败，未知错误"
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
            return jsonify({'success': True, 'message': '退课成功'})
        else:
            error_msg = str(result) if result else "退课失败，未知错误"
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

@app.route('/monitor')
def monitor():
    return render_template('monitor.html')

@app.route('/check_course_availability', methods=['POST'])
def check_course_availability():
    try:
        data = request.get_json()
        course_ids = data.get('course_ids', [])
        
        if not course_ids:
            return jsonify({'success': False, 'message': '没有提供课程ID'})
        
        # 获取课程的当前选课人数
        selected_numbers = get_selected_numbers(course_ids)
        
        available_courses = []
        for course_id in course_ids:
            course_id_str = str(course_id)
            if course_id_str in selected_numbers:
                selected_info = selected_numbers[course_id_str]
                selected_count = int(selected_info.split('-')[0])
                
                # 从ilist中找到对应课程的容量信息
                course_info = None
                for course in ilist:
                    if course['id'] == course_id:
                        course_info = course
                        break
                
                if course_info:
                    capacity = course_info['limitCount']
                    available_spots = capacity - selected_count
                    
                    # 如果有余量，记录课程信息
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
