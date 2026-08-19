from flask import Blueprint, request, session, jsonify
from utils.user_profile_utils import get_user_profile, save_user_profile, validate_profile

profile_bp = Blueprint('profile', __name__)


@profile_bp.route('/api/profile', methods=['GET'])
def get_my_profile():
    """讀取目前登入者的個人資料（只會是自己的，user_id 一律取自 session）。"""
    profile = get_user_profile(session.get('user_id'))
    if profile is None:
        return jsonify({'success': False, 'message': '找不到使用者資料，請重新登入。'}), 404

    return jsonify({'success': True, 'profile': profile})


@profile_bp.route('/api/profile', methods=['POST'])
def save_my_profile():
    """
    更新顯示名稱與聯絡信箱。
    Google 登入帳號（ad_user.email）不接受從這裡修改，即使前端送上來也會被忽略。
    """
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    contact_email = (data.get('contact_email') or '').strip()

    error = validate_profile(name, contact_email)
    if error:
        return jsonify({'success': False, 'message': error}), 400

    try:
        profile = save_user_profile(session.get('user_id'), name, contact_email)
    except Exception as e:
        return jsonify({'success': False, 'message': f'儲存個人資料失敗: {e}'}), 500

    if profile is None:
        return jsonify({'success': False, 'message': '找不到使用者資料，請重新登入。'}), 404

    # 側邊欄的名字讀的是 session，不同步更新的話要重新登入才會生效
    session['user_name'] = profile['name']

    return jsonify({
        'success': True,
        'message': '個人資料已更新。',
        'profile': profile
    })
