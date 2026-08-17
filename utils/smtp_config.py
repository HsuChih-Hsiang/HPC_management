"""
發信帳號設定 (SMTP)

儲存位置：HPCSetting 資料表
  - smtp_sender_email    : 發信帳號（明文）
  - smtp_sender_password : 發信密碼（經 Fernet 加密後的密文）

加密分工：
  - 傳輸中：前端以 RSA-OAEP(SHA-256) 加密密碼後才送出，後端用私鑰解開，
            避免密碼以明文出現在 request body。
  - 靜態時：解開後改用 Fernet 對稱加密才寫進資料庫，資料庫被翻出來也讀不到明文。

執行期快取：
  系統啟動時 (app.py) 呼叫一次 load_smtp_config_to_cache()，把設定撈出來解密後
  放進模組層級的全域變數，之後寄信一律讀這份快取，不必每次寄信都查一次 DB 並解密。
"""

from database.extensions import db
from database.hpc_model import HPCSetting
from utils.crypto_utils import encrypt_for_storage, decrypt_from_storage
from utils.params import SENDER_EMAIL, SENDER_PASSWORD

SMTP_SENDER_EMAIL_KEY = 'smtp_sender_email'
SMTP_SENDER_PASSWORD_KEY = 'smtp_sender_password'
SMTP_SETTING_CLASSIFICATION = 3  # 3 = 系統發信設定（1: 用量通知、2: 額度與優惠）

# --- 執行期全域變數（系統啟動時填入） ---
_RUNTIME_SENDER_EMAIL = None
_RUNTIME_SENDER_PASSWORD = None


def _get_setting(key):
    return HPCSetting.query.filter_by(key=key).first()


def _upsert_setting(key, value, description):
    setting = _get_setting(key)
    if setting:
        setting.value = value
        setting.classification = SMTP_SETTING_CLASSIFICATION
    else:
        db.session.add(HPCSetting(
            key=key,
            value=value,
            description=description,
            classification=SMTP_SETTING_CLASSIFICATION
        ))


def load_smtp_config_to_cache():
    """
    系統啟動時呼叫：從資料庫撈出發信設定、解密後放入全域變數。
    資料庫沒有設定時保持 None，寄信時會自動退回 .env 的設定值。
    """
    global _RUNTIME_SENDER_EMAIL, _RUNTIME_SENDER_PASSWORD

    email_setting = _get_setting(SMTP_SENDER_EMAIL_KEY)
    password_setting = _get_setting(SMTP_SENDER_PASSWORD_KEY)

    _RUNTIME_SENDER_EMAIL = email_setting.value if email_setting and email_setting.value else None
    _RUNTIME_SENDER_PASSWORD = (
        decrypt_from_storage(password_setting.value)
        if password_setting and password_setting.value
        else None
    )

    if _RUNTIME_SENDER_EMAIL:
        print(f"已從資料庫載入發信帳號設定：{_RUNTIME_SENDER_EMAIL}")
    else:
        print("資料庫尚無發信帳號設定，將沿用 .env 的 SENDER_EMAIL / SENDER_PASSWORD。")

    return _RUNTIME_SENDER_EMAIL, _RUNTIME_SENDER_PASSWORD


def save_smtp_config(sender_email, sender_password):
    """
    寫入發信設定：帳號存明文、密碼經 Fernet 加密後儲存，
    並同步更新執行期快取（免去改完設定還要重啟服務才生效）。

    sender_password 傳 None 代表「不修改現有密碼」，僅更新帳號。
    """
    global _RUNTIME_SENDER_EMAIL, _RUNTIME_SENDER_PASSWORD

    _upsert_setting(SMTP_SENDER_EMAIL_KEY, sender_email, '系統發信帳號')

    if sender_password:
        _upsert_setting(
            SMTP_SENDER_PASSWORD_KEY,
            encrypt_for_storage(sender_password),
            '系統發信密碼 (Fernet 加密)'
        )

    db.session.commit()

    _RUNTIME_SENDER_EMAIL = sender_email
    if sender_password:
        _RUNTIME_SENDER_PASSWORD = sender_password


def get_smtp_credentials():
    """
    取得目前實際要用來寄信的帳號密碼。
    優先使用資料庫設定（啟動時載入的全域變數），沒有才退回 .env 的值，
    確保尚未在畫面上設定過的環境仍可正常寄信。
    """
    email = _RUNTIME_SENDER_EMAIL or SENDER_EMAIL
    password = _RUNTIME_SENDER_PASSWORD or SENDER_PASSWORD
    return email, password


def has_saved_password():
    """畫面上用來顯示「目前已設定密碼」而不外洩密碼內容。"""
    setting = _get_setting(SMTP_SENDER_PASSWORD_KEY)
    return bool(setting and setting.value)
