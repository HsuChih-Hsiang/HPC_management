# oauth_config.py
import os
from functools import wraps
from authlib.integrations.flask_client import OAuth
from flask import session, redirect, url_for

# 建立 OAuth 物件
oauth = OAuth()

def init_oauth(app):
    """初始化 OAuth 並註冊 Google 服務"""
    oauth.init_app(app)
    
    oauth.register(
        name='google',
        client_id=os.getenv('GOOGLE_CLIENT_ID'),
        client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'}
    )

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function