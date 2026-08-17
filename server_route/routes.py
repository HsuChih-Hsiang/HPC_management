from flask import Blueprint, session, redirect, url_for
from flask import render_template
from utils.permission_utils import get_user_ordered_features, get_landing_path

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

@routes_bp.route('/setting')
def setting():
    return render_template('setting.html')

@routes_bp.route('/permission')
def permission():
    return render_template('permission.html')

@routes_bp.route('/pending-approval')
def pending_approval():
    """尚未被指派權限群組的使用者，登入後會被導向此頁等候管理員開通。"""
    return render_template('pending_approval.html')

@routes_bp.route('/')
@routes_bp.route('/login_page')
def login_page():
    if 'user_id' in session:
        # 同樣依權限決定落地頁，避免導向使用者無權存取的頁面
        return redirect(get_landing_path(get_user_ordered_features(session['user_id'])))
    return render_template('login.html')