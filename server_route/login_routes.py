from flask import Blueprint, session, redirect, url_for
from database.extensions import db
from database.hpc_model import AdUser
from utils.login_utils import oauth # 從拆分的檔案引入 oauth 物件

login_bp = Blueprint('login', __name__)

@login_bp.route('/login')
def login():
    # 使用 oauth.google 來呼叫
    return oauth.google.authorize_redirect(url_for('login.callback', _external=True))

@login_bp.route('/callback')
def callback():
    # 1. 取得 Access Token
    token = oauth.google.authorize_access_token()
    
    # 2. 使用 token 中的 id_token 進行解析，這會包含 user_info
    # 如果你不想處理 nonce，可以直接存取 token['userinfo']
    user_info = token.get('userinfo')
    
    # 如果 userinfo 為空，則手動解碼 id_token (如果需要)
    if not user_info:
        user_info = oauth.google.parse_id_token(token, nonce=None) 
    
    # 檢查使用者是否存在
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
    
    session['user_id'] = user.id
    session['user_name'] = user.name # 存入名稱供側邊欄使用
    return redirect(url_for('routes.batch_sending')) # 建議使用 url_for

@login_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('routes.login'))