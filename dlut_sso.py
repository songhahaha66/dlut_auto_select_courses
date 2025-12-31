import des
import requests
import time

def initial(initUrl, id):
    """初始化登录会话"""
    for attempt in range(10):
        try:
            s = requests.Session()
            response = s.get(initUrl, timeout=10)
            al = 'LT{}cas'.format(response.text.split('LT')[1].split('cas')[0])
            s.cookies.set('dlut_cas_un', id)
            s.cookies.set('cas_hash', "")
            return s, al
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                IndexError) as e:
            print(f"[SSO初始化重试 {attempt + 1}/10] {str(e)[:50]}")
            if attempt == 9:
                raise e

def constructPara(id, passwd, lt):
    al = {
        #'none': 'on',
        'rsa': des.strEnc(id + passwd + lt, '1', '2', '3'),
        'ul': str(len(id)),
        'pl': str(len(passwd)),
        'lt': lt,
        'sl':"0", #不知道干什么的
        'execution': 'e1s1',
        '_eventId': 'submit',
    }
    return '&'.join([i+'='+j for i, j in al.items()])

def login(id, passwd):
    """SSO登录"""
    targetUrl = 'https://sso.dlut.edu.cn/cas/login?service=http%3A%2F%2Fjxgl.dlut.edu.cn%2Fstudent%2Fucas-sso%2Flogin'
    s, lt = initial(targetUrl, id)
    s.headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36 Edg/138.0.0.0',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8'
    }
    
    for attempt in range(10):
        try:
            s.post(targetUrl, constructPara(id, passwd, lt), 
                   headers={'Content-Type': 'application/x-www-form-urlencoded'},
                   timeout=15)
            return s
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as e:
            print(f"[SSO登录重试 {attempt + 1}/10] {str(e)[:50]}")
            if attempt == 9:
                raise e

