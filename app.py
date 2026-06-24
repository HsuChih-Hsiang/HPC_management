from flask import Flask, session, request, redirect, url_for
from database.extensions import db
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from utils.hpc.hpc_notify_utils import check_hpc_usage_and_notify
from utils.login_utils import oauth, init_oauth
from utils.crypto_utils import key_generate
from utils.params import SECRET_KEY, DATABASE_URI
from utils.session_interface import CustomSessionInterface
from server_route import mailbox_bp, hpc_bp, email_bp, template_bp, routes_bp, contact_bp, quota_bp, login_bp

app = Flask(__name__)

key_generate()

app.session_interface = CustomSessionInterface()
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
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
    if request.endpoint is None:
        return

    allowed_endpoints = [
        'static', 
        'routes.login_page', 
        'login.login', 
        'login.callback', 
        'login.check_session'
    ]

    if request.endpoint in allowed_endpoints:
        return

    if 'user_id' not in session:
        return redirect(url_for('routes.login_page'))


# --- 3. HTTP 資安防護標頭 Middleware (after_request) ---
@app.after_request
def add_security_headers(response):
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
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