from flask import Flask, session, request, redirect, url_for, jsonify, render_template
from database.extensions import db
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from utils.hpc.hpc_setting_utils import init_hpc_settings, load_hpc_settings_by_classification
from utils.hpc.hpc_notify_utils import check_hpc_usage_and_notify
from utils.login_utils import oauth, init_oauth
from utils.crypto_utils import key_generate
from utils.params import SECRET_KEY, DATABASE_URI
from utils.session_interface import CustomSessionInterface
from utils.smtp_config import load_smtp_config_to_cache
from utils.permission_utils import (
    init_permission_groups, get_required_features, get_user_features,
    get_user_ordered_features, get_sidebar_features
)
from server_route import (
    mailbox_bp, hpc_bp, email_bp, template_bp, routes_bp,
    contact_bp, quota_bp, login_bp, setting_bp, permission_bp
)

app = Flask(__name__)

app.session_interface = CustomSessionInterface()
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# app.config['SESSION_COOKIE_SECURE'] = True    # 【防竊聽】僅限 HTTPS 傳輸（本地開發 HTTP 時先註解，上線要打開）

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URI
app.secret_key = SECRET_KEY

app.register_blueprint(mailbox_bp)
app.register_blueprint(hpc_bp)
app.register_blueprint(email_bp)
app.register_blueprint(template_bp)
app.register_blueprint(routes_bp)
app.register_blueprint(contact_bp)
app.register_blueprint(quota_bp)
app.register_blueprint(login_bp)
app.register_blueprint(setting_bp)
app.register_blueprint(permission_bp)

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


# --- 2-1. 全域權限防護 Middleware ---
# 頁面與 API 都在這裡統一把關：沒有被授權的功能，
# 既不會出現在側邊欄，直接打網址或呼叫 API 也一律擋下。
@app.before_request
def enforce_permission_protection():
    if request.endpoint is None or 'user_id' not in session:
        return

    required_features = get_required_features(request.endpoint, request.method)
    if not required_features:
        return

    user_features = get_user_features(session['user_id'])

    # 具備其中任一項功能即可通過（部分 API 為多個頁面共用）
    if user_features & required_features:
        return

    # API 回 403 讓前端能辨識；頁面則導向等候／可用的頁面
    if request.path.startswith('/api/') or request.path == '/send_email':
        return jsonify({
            'success': False,
            'message': '權限不足，請聯絡管理員開通此功能。'
        }), 403

    if not user_features:
        return redirect(url_for('routes.pending_approval'))

    return render_template('no_permission.html'), 403


# --- 2-2. 將側邊欄可見項目注入所有樣板 ---
@app.context_processor
def inject_sidebar_features():
    if 'user_id' not in session:
        return {'sidebar_features': [], 'allowed_features': set()}

    # 用有序的清單取得側邊欄順序（各群組可自訂），權限判斷則用 set
    ordered_features = get_user_ordered_features(session['user_id'])
    return {
        'sidebar_features': get_sidebar_features(ordered_features),
        'allowed_features': set(ordered_features)
    }


# --- 3. HTTP 資安防護標頭 Middleware (after_request) ---
@app.after_request
def add_security_headers(response):
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    
    return response

with app.app_context():
    db.init_app(app)
    init_oauth(app)
    key_generate()
    init_hpc_settings(app)
    # 系統啟動時撈出發信帳密並解密，放進全域快取供寄信使用
    load_smtp_config_to_cache()
    # 確保 admin 群組存在且擁有全部權限（含防鎖死保護）
    init_permission_groups(app)

def check_hpc_usage_in_context():
    with app.app_context():
        check_hpc_usage_and_notify()

def get_hpc_check_interval_days():
    """讀取 HPCSetting (classification=1) 的 check_interval，供 APScheduler 排程間隔使用。"""
    with app.app_context():
        settings_list = load_hpc_settings_by_classification(1)
        setting = next((item for item in settings_list if item['key'] == 'check_interval'), None)
        return setting['value'] if setting else 1

# --- run server ---
if __name__ == '__main__':
    # scheduler = BackgroundScheduler()
    # scheduler.add_job(
    #     func=check_hpc_usage_in_context,
    #     trigger="interval",
    #     days=get_hpc_check_interval_days(),
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