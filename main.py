import configparser
import json
import re
import time

import requests
import dlut_sso

config = configparser.ConfigParser()
config.read("./config.ini",encoding="utf-8")
userid = config.get("dlut_sso","userid")
password = config.get("dlut_sso","password")
turn_number = config.getint("turn","number")

def jw_login():
    s = dlut_sso.login(userid, password)
    cookies = {
        "SESSION": s.cookies['SESSION'],
        "INGRESSCOOKIE": s.cookies['INGRESSCOOKIE'],
        "SERVERNAME": s.cookies['SERVERNAME']
    }
    s.get("http://jxgl.dlut.edu.cn/student/for-std/course-select")
    return cookies

def get_class_turns(i):
    url = "http://jxgl.dlut.edu.cn/student/ws/for-std/course-select/open-turns"
    data = {
        "bizTypeId":"2",
        "studentId":stu_id
    }
    r = requests.post(url, data=data, cookies=cookies)
    data1=json.loads(r.text)
    # data1=data1[i] #0一般是主修选课
    return 2601

def get_itemList(id):
    url = f"http://jxgl.dlut.edu.cn/student/cache/course-select/version/{id}/version.json"
    r = requests.get(url, cookies=cookies)
    data = json.loads(r.text)
    a = data['itemList'][0]
    url1 = f"http://cdn-dlut.supwisdom.com/student/cache/course-select/addable-lessons/{id}/{a}.json"
    return json.loads(requests.get(url1, cookies=cookies).text)['data']

def get_student_id():
    url = "http://jxgl.dlut.edu.cn/student/for-std/course-select/single-student/turns"
    html = requests.get(url,cookies=cookies).text
    match = re.search(r'studentId\s*:\s*(\d+),', html)
    if match:
        student_id = match.group(1)
        return int(student_id)

def select_classes(class_id, turn_id):
    try:
        url = "http://jxgl.dlut.edu.cn/student/ws/for-std/course-select/add-request"
        data = {"studentAssoc":stu_id,"courseSelectTurnAssoc":turn_id,"requestMiddleDtos":[{"lessonAssoc":class_id,"virtualCost":0,"scheduleGroupAssoc":None}]}
        r1= requests.post(url,json=data,cookies=cookies)
        uuid1 = r1.text
        url1 = "http://jxgl.dlut.edu.cn/student/ws/for-std/course-select/add-drop-response"
        data1 ={
            "studentId":stu_id,
            "requestId":uuid1
        }
        r2 = requests.post(url1,data=data1,cookies=cookies)
        
        if r2.status_code != 200:
            return {"error": f"HTTP错误: {r2.status_code}"}
            
        try:
            r2_res = json.loads(r2.text)
        except json.JSONDecodeError:
            return {"error": "服务器返回无效的JSON格式"}
            
        if r2_res is None:
            return {"error": "服务器返回空响应"}
            
        if r2_res.get('success'):
            print("选课成功")
            return True
        else:
            print("选课失败")
            # 返回完整错误信息字典
            return r2_res['errorMessage']['textZh'] if r2_res else {"error": "未知错误"}
    except Exception as e:
        return {"error": f"选课请求异常: {str(e)}"}

def drop_classes(class_id,turn_id):
    try:
        url = "http://jxgl.dlut.edu.cn/student/ws/for-std/course-select/drop-request"
        data = {"studentAssoc":stu_id,"lessonAssocs":[class_id],"courseSelectTurnAssoc":turn_id,"coursePackAssoc":None}
        r1 = requests.post(url,json=data,cookies=cookies)
        uuid1 = r1.text
        url1 = "http://jxgl.dlut.edu.cn/student/ws/for-std/course-select/add-drop-response"
        data1 = {
            "studentId": stu_id,
            "requestId": uuid1
        }
        r2 = requests.post(url1, data=data1, cookies=cookies)
        
        if r2.status_code != 200:
            return {"error": f"HTTP错误: {r2.status_code}"}
            
        try:
            r2_res = json.loads(r2.text)
        except json.JSONDecodeError:
            return {"error": "服务器返回无效的JSON格式"}
            
        if r2_res is None:
            return {"error": "服务器返回空响应"}
            
        if r2_res.get('success'):
            print("退课成功")
            return True
        else:
            print("退课失败")
            print(r2_res)
            # 返回完整错误信息字典
            return r2_res['errorMessage']['textZh'] if r2_res else {"error": "未知错误"}
    except Exception as e:
        return {"error": f"退课请求异常: {str(e)}"}


def search_class(class_name,ilist):
    result = []
    for i in ilist:
        if class_name in i['course']['nameZh']:
            result.append({"name":i['course']['nameZh'],"id":i['id'], "teachers":i['teachers']})
    return result

def get_selected_classes(turn_Id):
    url = "http://jxgl.dlut.edu.cn/student/ws/for-std/course-select/selected-lessons"
    data = {
        "studentId":stu_id,
        "turnId":turn_Id
    }
    r = requests.post(url,data=data,cookies=cookies)
    d = json.loads(r.text)
    return d

def get_selected_numbers(lesson_ids):
    url = "http://jxgl.dlut.edu.cn/student/ws/for-std/course-select/std-count"
    data = [("lessonIds[]", lid) for lid in lesson_ids]
    r = requests.post(url, data=data, cookies=cookies)
    return json.loads(r.text)

def batch_operations(operations, interval=2):
    """
    批量执行选课/退课操作
    operations: 操作列表，每个操作包含 {'type': 'select'|'drop', 'class_id': int}
    interval: 操作间隔时间（秒）
    """
    results = []
    
    for i, operation in enumerate(operations):
        operation_type = operation.get('type')
        class_id = operation.get('class_id')
        
        if operation_type not in ['select', 'drop']:
            results.append({
                'success': False,
                'message': f'无效的操作类型: {operation_type}',
                'operation': operation
            })
            continue
            
        try:
            if operation_type == 'select':
                result = select_classes(class_id, turn_id)
            else:  # drop
                result = drop_classes(class_id, turn_id)
            
            if result is True:
                msg = f'{"选课" if operation_type == "select" else "退课"}成功'
                results.append({
                    'success': True,
                    'message': msg,
                    'operation': operation
                })
            else:
                # result为错误信息字典
                error_msg = "未知错误"
                if isinstance(result, dict):
                    # 尝试提取更详细的错误信息
                    if 'errorMessage' in result:
                        error_detail = result['errorMessage']
                        if isinstance(error_detail, dict):
                            error_msg = error_detail.get('textZh', error_detail.get('text', error_msg))
                        else:
                            error_msg = str(error_detail)
                    elif 'message' in result:
                        error_msg = result['message']
                    elif 'error' in result:
                        error_msg = result['error']
                elif isinstance(result, str):
                    error_msg = result
                msg = f'{"选课" if operation_type == "select" else "退课"}失败: {error_msg}'
                results.append({
                    'success': False,
                    'message': msg,
                    'operation': operation
                })
            
        except Exception as e:
            results.append({
                'success': False,
                'message': f'操作出错: {str(e)}',
                'operation': operation
            })
        
        # 如果不是最后一个操作，等待间隔时间
        if i < len(operations) - 1:
            time.sleep(interval)
    
    return results

def continuous_operations(operations, interval=2, max_attempts=None, stop_check=None):
    """
    持续执行操作直到所有操作成功
    operations: 操作列表
    interval: 操作间隔时间（秒）
    max_attempts: 最大尝试次数，None表示无限制
    stop_check: 停止检查函数，返回True时停止执行
    """
    attempt = 0
    remaining_operations = operations.copy()
    
    while remaining_operations and (max_attempts is None or attempt < max_attempts):
        # 检查是否需要停止
        if stop_check and stop_check():
            print("收到停止信号，脚本终止")
            break
            
        attempt += 1
        print(f"第 {attempt} 次尝试，剩余 {len(remaining_operations)} 个操作")
        
        results = batch_operations(remaining_operations, interval)
        
        # 移除成功的操作
        successful_operations = []
        for i, result in enumerate(results):
            if result['success']:
                successful_operations.append(remaining_operations[i])
        
        for op in successful_operations:
            remaining_operations.remove(op)
        
        if remaining_operations:
            print(f"还有 {len(remaining_operations)} 个操作未完成，等待 {interval} 秒后继续...")
            time.sleep(interval)
        else:
            print("所有操作已完成！")
            break
    
    return len(remaining_operations) == 0, attempt

def continuous_operations_with_log(operations, interval=2, max_attempts=None, stop_check=None, log_callback=None):
    """
    持续执行操作直到所有操作成功，带日志记录功能
    operations: 操作列表，每个操作包含 {'type': 'select'|'drop', 'class_id': int, 'course_info': dict}
    interval: 操作间隔时间（秒）
    max_attempts: 最大尝试次数，None表示无限制
    stop_check: 停止检查函数，返回True时停止执行
    log_callback: 日志回调函数
    """
    attempt = 0
    remaining_operations = operations.copy()
    
    while remaining_operations and (max_attempts is None or attempt < max_attempts):
        # 检查是否需要停止
        if stop_check and stop_check():
            if log_callback:
                log_callback("收到停止信号，脚本终止", 'warning')
            break
            
        attempt += 1
        if log_callback:
            log_callback(f"第 {attempt} 次尝试，剩余 {len(remaining_operations)} 个操作", 'info')
        
        # 执行当前轮次的所有操作
        successful_operations = []
        for i, operation in enumerate(remaining_operations):
            # 添加空值检查
            if operation is None:
                if log_callback:
                    log_callback("❌ 发现空操作，跳过", 'error')
                continue
                
            operation_type = operation.get('type') if isinstance(operation, dict) else None
            class_id = operation.get('class_id') if isinstance(operation, dict) else None
            course_info = operation.get('course_info', {}) if isinstance(operation, dict) else {}
            
            # 确保course_info是字典
            if not isinstance(course_info, dict):
                course_info = {}
                
            course_name = course_info.get('name', f'课程ID:{class_id}') if course_info else f'课程ID:{class_id}'
            
            if operation_type not in ['select', 'drop']:
                if log_callback:
                    log_callback(f"❌ {course_name}: 无效的操作类型 {operation_type}", 'error', course_info)
                continue
                
            if class_id is None:
                if log_callback:
                    log_callback(f"❌ {course_name}: 课程ID为空", 'error', course_info)
                continue
                
            try:
                if operation_type == 'select':
                    result = select_classes(class_id, turn_id)
                else:  # drop
                    result = drop_classes(class_id, turn_id)
                
                if result is True:
                    action = "选课" if operation_type == "select" else "退课"
                    msg = f"✅ {course_name}: {action}成功"
                    if log_callback:
                        log_callback(msg, 'success', course_info)
                    successful_operations.append(operation)
                else:
                    # result为错误信息字典
                    error_msg = "未知错误"
                    if isinstance(result, dict):
                        # 尝试提取更详细的错误信息
                        if 'errorMessage' in result:
                            error_detail = result['errorMessage']
                            if isinstance(error_detail, dict):
                                error_msg = error_detail.get('textZh', error_detail.get('text', error_msg))
                            else:
                                error_msg = str(error_detail)
                        elif 'message' in result:
                            error_msg = result['message']
                        elif 'error' in result:
                            error_msg = result['error']
                    elif isinstance(result, str):
                        error_msg = result
                    
                    action = "选课" if operation_type == "select" else "退课"
                    msg = f"❌ {course_name}: {action}失败 - {error_msg}"
                    if log_callback:
                        log_callback(msg, 'error', course_info)
                
            except Exception as e:
                action = "选课" if operation_type == "select" else "退课"
                msg = f"❌ {course_name}: {action}操作出错 - {str(e)}"
                if log_callback:
                    log_callback(msg, 'error', course_info)
            
            # 操作间短暂延时
            if i < len(remaining_operations) - 1:
                time.sleep(min(interval * 0.2, 1))  # 单个操作间的小延时
        
        # 移除成功的操作
        for op in successful_operations:
            remaining_operations.remove(op)
        
        if remaining_operations:
            if log_callback:
                log_callback(f"还有 {len(remaining_operations)} 个操作未完成，等待 {interval} 秒后继续...", 'info')
            time.sleep(interval)
        else:
            if log_callback:
                log_callback("🎉 所有操作已完成！", 'success')
            break
    
    return len(remaining_operations) == 0, attempt

cookies = jw_login()
stu_id = get_student_id()
turn_id = get_class_turns(turn_number)
try:
    with open("ilist.json", "r", encoding="utf-8") as f:
        ilist = json.load(f)
except FileNotFoundError:
    print("ilist.json not found, fetching from server...")
    ilist = get_itemList(turn_id)
    ilist = json.loads(ilist)
    with open("ilist.json", "w", encoding="utf-8") as f:
        json.dump(ilist, f, ensure_ascii=False, indent=4)

if __name__ == "__main__":
    class_id = 6666 #请将此替换为你要选的class_id
    while True:
        res = select_classes(class_id, turn_id)
        if res:
            break