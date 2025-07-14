from flask import Flask, render_template, request, jsonify
import json
from main import *

app = Flask(__name__)

# 使用main.py中已经初始化的登录信息
# cookies, stu_id, turn_id, ilist 已经在main.py中定义

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search_course', methods=['POST'])
def search_course():
    try:
        data = request.get_json()
        course_name = data.get('course_name')
        
        # 搜索课程
        result = []
        lesson_ids = []
        for i in ilist:
            if course_name in i['course']['nameZh']:
                teachers = ', '.join([t['nameZh'] for t in i['teachers']])
                result.append({
                    "name": i['course']['nameZh'],
                    "id": i['id'],
                    "teachers": teachers,
                    "credits": i['course']['credits'],
                    "capacity": i['limitCount'],
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
        if result:
            return jsonify({'success': True, 'message': '选课成功'})
        else:
            return jsonify({'success': False, 'message': '选课失败'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'选课失败: {str(e)}'})

@app.route('/drop_course', methods=['POST'])
def drop_course():
    try:
        data = request.get_json()
        class_id = data.get('class_id')
        
        # 退课
        result = drop_classes(class_id, turn_id)
        if result:
            return jsonify({'success': True, 'message': '退课成功'})
        else:
            return jsonify({'success': False, 'message': '退课失败'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'退课失败: {str(e)}'})

@app.route('/selected_courses')
def selected_courses():
    try:
        # 获取已选课程
        selected = get_selected_classes(turn_id)
        
        courses = []
        for course in selected:
            teachers = ', '.join([t['nameZh'] for t in course['teachers']])
            courses.append({
                "name": course['course']['nameZh'],
                "id": course['id'],
                "teachers": teachers,
                "credits": course['course']['credits']
            })
        
        return jsonify({'success': True, 'courses': courses})
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取已选课程失败: {str(e)}'})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
