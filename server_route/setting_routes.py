from flask import request, Blueprint, session, jsonify
from database.extensions import db
from database.hpc_model import AdUser
from utils.crypto_utils import decrypt_frontend_data, get_public_key_pem
from utils.params import SECRET_KEY

setting_bp = Blueprint('setting', __name__)

@setting_bp.route('/api/user/save-smtp', methods=['POST'])
def save_smtp():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    encrypted_password = data.get('encrypted_password')
    smtp_user = data.get('smtp_user')

    # 1. 解密前端傳過來的 RSA 密文
    real_password = decrypt_frontend_data(encrypted_password)

    if not real_password:
        return jsonify({"error": "解密傳輸資料失敗"}), 400

    # 2. 整理成要塞進資料庫的 dict
    config_dict = {
        "smtp_user": smtp_user,
        "smtp_password": real_password
    }

    # 3. 找到當前使用者並寫入（內部自動觸發 Fernet 加密）
    user = AdUser.query.get(session['user_id'])
    if user:
        user.set_smtp_config(config_dict, SECRET_KEY)
        db.session.commit()
        return jsonify({"message": "SMTP 設定已安全加密儲存"})

    return jsonify({"error": "User not found"}), 404

@setting_bp.route('/api/auth/public-key', methods=['GET'])
def get_public_key():
    return jsonify({"public_key": get_public_key_pem()})