"""
大连理工大学选课系统 - 桌面应用
使用 PyWebView 将 Flask 应用包装为桌面窗口
"""
import webview
import threading
from app import app

def start_flask():
    """在后台线程启动 Flask"""
    app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)

if __name__ == '__main__':
    # 启动 Flask 服务器（后台线程）
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()
    
    # 创建桌面窗口，默认打开登录页
    webview.create_window(
        title='大连理工大学选课系统',
        url='http://127.0.0.1:5000/login',
        width=1100,
        height=800,
        resizable=True,
        min_size=(800, 600)
    )
    webview.start()
