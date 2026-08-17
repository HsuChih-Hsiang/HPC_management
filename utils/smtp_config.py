"""
發信設定 (SMTP)

儲存位置：HPCSetting 資料表（classification = 3）
  - smtp_server          : 郵件主機位址（明文）
  - smtp_port            : 連接埠（明文）
  - smtp_sender_email    : 發信帳號（明文）
  - smtp_sender_password : 發信密碼（經 Fernet 加密後的密文）

加密分工（僅密碼需要）：
  - 傳輸中：前端以 RSA-OAEP(SHA-256) 加密密碼後才送出，後端用私鑰解開，
            避免密碼以明文出現在 request body。
  - 靜態時：解開後改用 Fernet 對稱加密才寫進資料庫，資料庫被翻出來也讀不到明文。
  主機位址與連接埠不是機密，維持明文儲存以便直接查看與排錯。

執行期快取：
  系統啟動時 (app.py) 呼叫一次 load_smtp_config_to_cache()，把設定撈出來解密後
  放進模組層級的全域變數，之後寄信一律讀這份快取，不必每次寄信都查一次 DB 並解密。
"""

from database.extensions import db
from database.hpc_model import HPCSetting
from utils.crypto_utils import encrypt_for_storage, decrypt_from_storage
from utils.params import SMTP_SERVER, SMTP_PORT, SENDER_EMAIL, SENDER_PASSWORD

SMTP_SERVER_KEY = 'smtp_server'
SMTP_PORT_KEY = 'smtp_port'
SMTP_SENDER_EMAIL_KEY = 'smtp_sender_email'
SMTP_SENDER_PASSWORD_KEY = 'smtp_sender_password'
SMTP_SETTING_CLASSIFICATION = 3  # 3 = 系統發信設定（1: 用量通知、2: 額度與優惠）

# --- 執行期全域變數（系統啟動時填入） ---
_RUNTIME_SMTP_SERVER = None
_RUNTIME_SMTP_PORT = None
_RUNTIME_SENDER_EMAIL = None
_RUNTIME_SENDER_PASSWORD = None


def _get_setting(key):
    return HPCSetting.query.filter_by(key=key).first()


def _get_value(key):
    setting = _get_setting(key)
    return setting.value if setting and setting.value else None


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
    global _RUNTIME_SMTP_SERVER, _RUNTIME_SMTP_PORT
    global _RUNTIME_SENDER_EMAIL, _RUNTIME_SENDER_PASSWORD

    _RUNTIME_SMTP_SERVER = _get_value(SMTP_SERVER_KEY)
    _RUNTIME_SENDER_EMAIL = _get_value(SMTP_SENDER_EMAIL_KEY)

    port_raw = _get_value(SMTP_PORT_KEY)
    try:
        _RUNTIME_SMTP_PORT = int(port_raw) if port_raw else None
    except (TypeError, ValueError):
        # 資料庫存了無法轉成數字的值時不要讓寄信整組壞掉，退回 .env 設定
        print(f"發信設定的連接埠 '{port_raw}' 無法轉為數字，將沿用 .env 的 SMTP_PORT。")
        _RUNTIME_SMTP_PORT = None

    encrypted_password = _get_value(SMTP_SENDER_PASSWORD_KEY)
    _RUNTIME_SENDER_PASSWORD = (
        decrypt_from_storage(encrypted_password) if encrypted_password else None
    )

    if _RUNTIME_SENDER_EMAIL or _RUNTIME_SMTP_SERVER:
        server, port, email, _ = get_smtp_settings()
        print(f"已從資料庫載入發信設定：{email} @ {server}:{port}")
    else:
        print("資料庫尚無發信設定，將沿用 .env 的 SMTP_SERVER / SMTP_PORT / SENDER_EMAIL / SENDER_PASSWORD。")

    return get_smtp_settings()


def save_smtp_config(smtp_server, smtp_port, sender_email, sender_password):
    """
    寫入發信設定：主機、連接埠、帳號存明文，密碼經 Fernet 加密後儲存，
    並同步更新執行期快取（免去改完設定還要重啟服務才生效）。

    sender_password 傳 None 代表「不修改現有密碼」，僅更新其他欄位。
    """
    global _RUNTIME_SMTP_SERVER, _RUNTIME_SMTP_PORT
    global _RUNTIME_SENDER_EMAIL, _RUNTIME_SENDER_PASSWORD

    _upsert_setting(SMTP_SERVER_KEY, smtp_server, '郵件主機位址')
    _upsert_setting(SMTP_PORT_KEY, str(smtp_port), '郵件主機連接埠')
    _upsert_setting(SMTP_SENDER_EMAIL_KEY, sender_email, '系統發信帳號')

    if sender_password:
        _upsert_setting(
            SMTP_SENDER_PASSWORD_KEY,
            encrypt_for_storage(sender_password),
            '系統發信密碼 (Fernet 加密)'
        )

    db.session.commit()

    _RUNTIME_SMTP_SERVER = smtp_server
    _RUNTIME_SMTP_PORT = int(smtp_port)
    _RUNTIME_SENDER_EMAIL = sender_email
    if sender_password:
        _RUNTIME_SENDER_PASSWORD = sender_password


def get_smtp_settings():
    """
    取得目前實際要用來寄信的完整設定 (server, port, email, password)。
    優先使用資料庫設定（啟動時載入的全域變數），沒有才退回 .env 的值，
    確保尚未在畫面上設定過的環境仍可正常寄信。
    """
    server = _RUNTIME_SMTP_SERVER or SMTP_SERVER
    # 連接埠可能是 0 以外的任何數字，但 0 不是合法的埠號，用 or 判斷即可
    port = _RUNTIME_SMTP_PORT or SMTP_PORT
    email = _RUNTIME_SENDER_EMAIL or SENDER_EMAIL
    password = _RUNTIME_SENDER_PASSWORD or SENDER_PASSWORD
    return server, port, email, password


def get_smtp_credentials():
    """向後相容：只取帳號與密碼。"""
    _, _, email, password = get_smtp_settings()
    return email, password


def ensure_smtp_configured():
    """
    寄信前檢查設定是否齊全，缺少時丟出可讀的錯誤訊息。

    發信帳密已從 .env 移除、改存資料庫，因此若資料庫也沒有設定
    （例如全新環境、或 SECRET_KEY 變更導致密碼解不開），
    直接呼叫 smtplib 會得到 'NoneType' 之類難以理解的錯誤。
    這裡提前擋下並明確指出要去哪裡設定。
    """
    server, port, email, password = get_smtp_settings()

    missing = []
    if not server:
        missing.append('郵件主機')
    if not port:
        missing.append('連接埠')
    if not email:
        missing.append('發信帳號')
    if not password:
        missing.append('發信密碼')

    if missing:
        raise RuntimeError(
            f"發信設定不完整（缺少：{'、'.join(missing)}），"
            "請至「設定」頁面填寫後再寄信。"
        )

    return server, port, email, password


def has_saved_password():
    """畫面上用來顯示「目前已設定密碼」而不外洩密碼內容。"""
    return bool(_get_value(SMTP_SENDER_PASSWORD_KEY))
