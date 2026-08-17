from flask import request, Blueprint, session, jsonify
from utils.crypto_utils import decrypt_frontend_data, get_public_key_pem
from utils.smtp_config import save_smtp_config, get_smtp_credentials, has_saved_password

setting_bp = Blueprint('setting', __name__)


@setting_bp.route('/api/auth/public-key', methods=['GET'])
def get_public_key():
    """提供 RSA 公鑰給前端，用來加密要送出的密碼。"""
    try:
        return jsonify({'public_key': get_public_key_pem()})
    except Exception as e:
        return jsonify({'success': False, 'message': f'取得公鑰失敗: {e}'}), 500


@setting_bp.route('/api/setting/smtp', methods=['GET'])
def get_smtp_setting():
    """
    讀取目前的發信設定。
    只回傳帳號；密碼一律不回傳，僅以布林值告知前端「是否已設定過」，
    避免密碼經由 API 外流。
    """
    sender_email, _ = get_smtp_credentials()
    return jsonify({
        'sender_email': sender_email or '',
        'has_password': has_saved_password()
    })


@setting_bp.route('/api/setting/smtp', methods=['POST'])
def save_smtp_setting():
    """
    儲存發信設定。
    密碼必須由前端以 RSA-OAEP(SHA-256) 加密後放在 encrypted_password 送出，
    後端用私鑰解開後，再以 Fernet 加密寫入資料庫。
    未帶 encrypted_password 代表「只改帳號、沿用原本的密碼」。
    """
    data = request.get_json() or {}
    sender_email = (data.get('sender_email') or '').strip()
    encrypted_password = data.get('encrypted_password')

    if not sender_email:
        return jsonify({'success': False, 'message': '請輸入發信帳號。'}), 400

    real_password = None
    if encrypted_password:
        real_password = decrypt_frontend_data(encrypted_password)
        if not real_password:
            return jsonify({'success': False, 'message': '解密傳輸資料失敗，請重新整理頁面後再試一次。'}), 400

    # 從未設定過密碼時，第一次儲存必須要有密碼，否則寄信一定會失敗
    if not real_password and not has_saved_password():
        return jsonify({'success': False, 'message': '請輸入發信密碼。'}), 400

    try:
        save_smtp_config(sender_email, real_password)
    except Exception as e:
        return jsonify({'success': False, 'message': f'儲存設定失敗: {e}'}), 500

    return jsonify({'success': True, 'message': '發信設定已加密儲存，並已立即生效。'})
