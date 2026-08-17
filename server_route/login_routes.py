from flask import Blueprint, session, redirect, url_for, jsonify
from database.extensions import db
from database.hpc_model import AdUser
from utils.login_utils import oauth
from utils.permission_utils import get_user_ordered_features, get_landing_path

login_bp = Blueprint('login', __name__)

@login_bp.route('/login')
def login():
    return oauth.google.authorize_redirect(url_for('login.callback', _external=True))

@login_bp.route('/callback')
def callback():
    token = oauth.google.authorize_access_token()
    user_info = token.get('userinfo')
    
    if not user_info:
        user_info = oauth.google.parse_id_token(token, nonce=None)
        
    user = AdUser.query.filter_by(google_id=user_info['sub']).first()
    
    if not user:
        new_user = AdUser(
            google_id=user_info['sub'],
            email=user_info['email'],
            name=user_info.get('name')
        )
        db.session.add(new_user)
        db.session.commit()
        user = new_user

    session.permanent = True
    session['user_id'] = user.id
    session['user_name'] = user.name

    # 依實際擁有的權限決定登入後的落地頁；尚未開通者會導向等候頁面。
    # 使用有序清單，讓落地頁與該群組側邊欄的第一個項目一致。
    return redirect(get_landing_path(get_user_ordered_features(user.id)))

@login_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('routes.login_page'))

@login_bp.route('/check-session', methods=['GET'])
def check_session():
    if 'user_id' in session:
        return jsonify({"authenticated": True}), 200
    
    # 若沒有，回傳 401 狀態碼
    return jsonify({"authenticated": False, "message": "Session expired"}), 401