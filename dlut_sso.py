import des
import requests

def initial(initUrl, id):
    s = requests.Session()
    response = s.get(initUrl)
    al = 'LT{}cas'.format(response.text.split('LT')[1].split('cas')[0])
    s.cookies.set('dlut_cas_un', id)
    s.cookies.set('cas_hash', "")
    return s, al

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
    targetUrl = 'https://sso.dlut.edu.cn/cas/login?service=http%3A%2F%2Fjxgl.dlut.edu.cn%2Fstudent%2Fucas-sso%2Flogin'
    s, lt = initial(targetUrl, id)
    s.headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.88 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8'
    }
    res = s.post(targetUrl, constructPara(id, passwd, lt), headers={'Content-Type': 'application/x-www-form-urlencoded'}).headers
    return s

