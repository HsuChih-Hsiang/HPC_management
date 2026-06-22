from flask import Flask, session, request, redirect, url_for
from database.extensions import db
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from utils.hpc.hpc_notify_utils import check_hpc_usage_and_notify
from utils.login_utils import oauth, init_oauth
from utils.params import SECRET_KEY, DATABASE_URI
from server_route import mailbox_bp, hpc_bp, email_bp, template_bp, routes_bp, contact_bp, quota_bp, login_bp

app = Flask(__name__)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)
app.config['SESSION_COOKIE_HTTPONLY'] = True   # 【防 XSS】禁止 JavaScript 讀取 Session Cookie
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'   # 【防 CSRF】限制第三方網站請求攜帶 Cookie
# app.config['SESSION_COOKIE_SECURE'] = True    # 【防竊聽】僅限 HTTPS 傳輸（本地開發 HTTP 時先註解，上線要打開）

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URI
db.init_app(app)

app.secret_key = SECRET_KEY
init_oauth(app)

app.register_blueprint(mailbox_bp)
app.register_blueprint(hpc_bp)
app.register_blueprint(email_bp)
app.register_blueprint(template_bp)
app.register_blueprint(routes_bp)
app.register_blueprint(contact_bp)
app.register_blueprint(quota_bp)
app.register_blueprint(login_bp)

# --- 2. 全域登入防護 Middleware (before_request) ---
@app.before_request
def enforce_login_protection():
    # 💡 核心修正 1：如果請求的是不存在的路由或 /favicon.ico，建立此處放行
    # 讓 Flask 去報 404 即可，不要將這類請求抓去重導向，否則會引發無限無窮迴圈
    if request.endpoint is None:
        return

    # 定義白名單
    allowed_endpoints = ['routes.login_page', 'login.login', 'login.callback', 'static']
    
    # 💡 核心修正 2：如果當前請求在白名單內，直接放行
    if request.endpoint in allowed_endpoints:
        return
        
    # 如果不在白名單內，且檢查到未登入，才強制導向登入頁面
    if 'user_id' not in session:
        return redirect(url_for('routes.login_page'))


# --- 3. HTTP 資安防護標頭 Middleware (after_request) ---
# 為每一個回應（Response）加上防禦性 Header，防止常見的 Web 攻擊
@app.after_request
def add_security_headers(response):
    # 防止點擊劫持 (Clickjacking)：不允許網頁被內嵌在別人的 <iframe> 中
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    
    # 防止 MIME 類型嗅探：強迫瀏覽器遵從 Content-Type 企圖，防止惡意上傳腳本執行
    response.headers['X-Content-Type-Options'] = 'nosniff'
    
    # 限制引薦來源 (Referrer Policy)：避免在跳轉時洩漏敏感的網址參數
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    
    # 啟用瀏覽器內建的 XSS 過濾器
    response.headers['X-XSS-Protection'] = '1; mode=block'
    
    return response



def check_hpc_usage_in_context():
    with app.app_context():
        check_hpc_usage_and_notify()



# --- run server ---
if __name__ == '__main__':
    scheduler = BackgroundScheduler()
    # scheduler.add_job(
    #     func=check_hpc_usage_in_context,
    #     trigger="interval",
    #     days=load_hpc_settings()['check_interval'],
    #     id='hpc_check_job'
    # )
    # scheduler.add_job(
    # func=check_hpc_usage_in_context,
    # trigger='date',
    # run_date=datetime.now() + timedelta(seconds=5),
    # id='one_time_hpc_check'
    # )
    # scheduler.start()
    app.run(debug=True, use_reloader=False)