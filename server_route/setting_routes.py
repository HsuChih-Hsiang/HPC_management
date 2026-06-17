from flask import request
from flask import Blueprint, session
from database.extensions import db
from database.hpc_model import AdUser

setting_bp = Blueprint('setting', __name__)

@setting_bp.route('/save_smtp', methods=['POST'])
def save_smtp():
    config = {
        "email": request.form.get('email'),
        "password": request.form.get('password'),
        "host": request.form.get('host'),
        "port": int(request.form.get('port'))
    }
    user = AdUser.query.get(session['user_id'])
    user.set_smtp_config(config, SECRET_KEY)
    db.session.commit()
    return "儲存成功"