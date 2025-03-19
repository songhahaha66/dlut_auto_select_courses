import configparser
import json
import re

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
    data1=data1[i] #0一般是主修选课
    return data1['id']

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
    r2_res = json.loads(r2.text)
    if r2_res['success']:
        print("选课成功")
        return True
    else:
        print("选课失败")

def drop_classes(class_id,turn_id):
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
    r2_res = json.loads(r2.text)
    if r2_res['success']:
        print("退课成功")
        return True
    else:
        print("退课失败")
        print(r2_res)


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

cookies = jw_login()
stu_id = get_student_id()
turn_id = get_class_turns(turn_number)
ilist = get_itemList(turn_id)
ilist = json.loads(ilist)

if __name__ == "__main__":
    class_id = 6666 #请将此替换为你要选的class_id
    while True:
        res = select_classes(class_id, turn_id)
        if res:
            break