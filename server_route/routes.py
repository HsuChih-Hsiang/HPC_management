from flask import Blueprint, session, redirect, url_for
from flask import render_template

routes_bp = Blueprint('routes', __name__)

@routes_bp.route('/batch_sending')
def batch_sending():
    return render_template('batch_sending.html')

@routes_bp.route('/edit-templates')
def edit_templates():
    return render_template('edit_templates.html')

@routes_bp.route('/mailbox-manager')
def mailbox_manager():
    return render_template('mailbox_manager.html')

@routes_bp.route('/hpc-usage')
def hpc_usage():
    return render_template('hpc_usage.html')

@routes_bp.route('/hpc-contact')
def hpc_contact():
    return render_template('contact_manager.html')

@routes_bp.route('/')
@routes_bp.route('/login_page')
def login_page():
    # 確認 session 是否還有效，如果有效，直接跳轉到內部主頁
    if 'user_id' in session:
        return redirect(url_for('routes.batch_sending'))
    
    # 若無 session 或已過期，才顯示登入頁面
    return render_template('login.html')