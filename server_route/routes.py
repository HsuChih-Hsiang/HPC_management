from flask import Blueprint
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
def login():
    # 顯示登入頁面
    return render_template('login.html')