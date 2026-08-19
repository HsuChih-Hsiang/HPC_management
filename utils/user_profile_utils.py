"""
個人資料（顯示名稱 + 聯絡信箱）

兩個信箱要分清楚：
  ad_user.email          Google 登入帳號，由 OAuth 帶回來，使用者不能改，
                         只用於辨識身分（有 unique 限制）。
  ad_user.contact_email  使用者自己填的聯絡信箱，系統要聯絡本人時用這個，
                         可以留空、可以與 Google 帳號完全無關，也不要求唯一。

側邊欄顯示的名字來自 session['user_name']，所以改完名字後
呼叫端（profile_routes）必須一併更新 session，否則要重新登入才會看到新名字。
"""

import re
from sqlalchemy import inspect
from database.extensions import db
from database.hpc_model import AdUser

# 基本格式檢查即可：真正能不能收信只有寄出去才知道，
# 這裡擋的是明顯的錯字（少了 @、少了網域）。
EMAIL_PATTERN = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

NAME_MAX_LENGTH = 100
CONTACT_EMAIL_MAX_LENGTH = 120


def check_profile_columns(app):
    """
    啟動時確認 ad_user.contact_email 已建立。

    這個欄位一旦寫進 model，SQLAlchemy 的每一次 AdUser 查詢都會 SELECT 它，
    包含登入流程與權限檢查。若資料庫還沒加欄位，錯誤會以難以理解的
    ProgrammingError 出現在完全無關的地方，所以在啟動時就先講清楚。
    """
    with app.app_context():
        inspector = inspect(db.engine)
        if 'ad_user' not in set(inspector.get_table_names()):
            return

        if 'contact_email' not in {c['name'] for c in inspector.get_columns('ad_user')}:
            print('=' * 70)
            print("[個人資料] ad_user 缺少 contact_email 欄位（個人資料頁的聯絡信箱所需）。")
            print("請先執行 sql/20260818_add_user_contact_email.sql 後再啟動服務。")
            print('=' * 70)


def get_user_profile(user_id):
    """回傳個人資料頁需要的欄位；找不到使用者回傳 None。"""
    user = db.session.get(AdUser, user_id)
    if not user:
        return None

    return {
        'name': user.name or '',
        'contact_email': user.contact_email or '',
        # 唯讀顯示用，讓使用者看得出「這個是登入用的，不是聯絡用的」
        'google_email': user.email or ''
    }


def validate_profile(name, contact_email):
    """檢查欄位內容，通過回傳 None，否則回傳給前端看的錯誤訊息。"""
    if not name:
        return '請輸入顯示名稱。'

    if len(name) > NAME_MAX_LENGTH:
        return f'顯示名稱請勿超過 {NAME_MAX_LENGTH} 個字。'

    if contact_email:
        if len(contact_email) > CONTACT_EMAIL_MAX_LENGTH:
            return f'聯絡 Email 請勿超過 {CONTACT_EMAIL_MAX_LENGTH} 個字元。'
        if not EMAIL_PATTERN.match(contact_email):
            return '聯絡 Email 格式不正確，請確認是否為有效的信箱位址。'

    return None


def save_user_profile(user_id, name, contact_email):
    """
    寫入名稱與聯絡信箱，回傳更新後的個人資料；找不到使用者回傳 None。
    contact_email 傳空字串代表「清掉不設定」，資料庫存 NULL。
    """
    user = db.session.get(AdUser, user_id)
    if not user:
        return None

    user.name = name
    user.contact_email = contact_email or None
    db.session.commit()

    return {
        'name': user.name or '',
        'contact_email': user.contact_email or '',
        'google_email': user.email or ''
    }
