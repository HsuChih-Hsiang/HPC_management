import os
import re
from dotenv import load_dotenv

load_dotenv()

# 配置郵件伺服器
# 發信設定的正式來源是資料庫（「設定」頁面，見 utils/smtp_config.py）。
# 這裡的 .env 值只是「資料庫尚未設定時」的退路，全部允許不存在。
SMTP_SERVER = os.getenv("SMTP_SERVER")

# 用 int() 直接包 getenv 的話，.env 少了 SMTP_PORT 會在 import 階段就丟
# TypeError 讓整個服務起不來。這裡改為容錯：沒設定或格式錯誤都視為未提供。
_smtp_port_raw = os.getenv("SMTP_PORT")
try:
    SMTP_PORT = int(_smtp_port_raw) if _smtp_port_raw else None
except ValueError:
    print(f"警告：.env 的 SMTP_PORT='{_smtp_port_raw}' 不是有效的數字，將視為未設定。")
    SMTP_PORT = None

# 帳號與密碼已改存於資料庫（密碼經 Fernet 加密），.env 中可不再保留。
DATABASE_URI = os.getenv('DATABASE_URI')
SECRET_KEY = os.getenv('SECRET_KEY')

KEY_DIR = '/source'
PRIVATE_KEY_PATH = os.path.join(KEY_DIR, 'private_key.pem')

# HPC settings
HPC_NOTIFICATIONS_DIR = os.path.join('log', 'hpc_notifications')

# 信箱分組
UNASSIGNED_GROUP_ID = 0
UNASSIGNED_GROUP_NAME = "待分組信箱"
DEFAULT_HPC_SETTINGS = {
    'price_threshold': {'value': 500, 'type': int, 'desc': '單次通知的消費金額門檻 (NTD)', 'classification': 1},
    'check_interval': {'value': 1, 'type': int, 'desc': '檢查消費的間隔時間 (小時)', 'classification': 1},
    'diff_price_threshold': {'value': 10000, 'type': int, 'desc': '用於檢查成長率的消費差異門檻 (NTD)', 'classification': 1},
    'check_period': {'value': 30, 'type': int, 'desc': '檢查成長率的時間週期 (天)', 'classification': 1},
    'notification_cooldown_days': {'value': 7, 'type': int, 'desc': '通知冷卻時間 (天)', 'classification': 1},
    'free_quota': {'value': 10000, 'type': int, 'desc': '更新資料給的免費額度', 'classification': 2},
    'academic_quota': {'value': 1000, 'type': int, 'desc': '期刊論文給的額度(每篇1000,最高10篇)', 'classification': 2},
    'discount': {'value':[{"min_amount": 100001, "divisor": 0.36}, {"min_amount": 50001,  "divisor": 0.75}], 'type': list, 'desc': '優惠區間', 'classification': 2}
}


# ============================================================
# 功能清單（順序即側邊欄顯示順序）
# 新增頁面時在這裡加一筆，並補上底下的 endpoint 對應。
# ============================================================
ADMIN_GROUP_NAME = 'admin'

FEATURES = [
    {'key': 'batch_sending',   'label': '寄送郵件',     'icon': '📨', 'path': '/batch_sending'},
    {'key': 'edit_templates',  'label': '編輯模板',     'icon': '📝', 'path': '/edit-templates'},
    {'key': 'mailbox_manager', 'label': '信箱管理',     'icon': '📬', 'path': '/mailbox-manager'},
    {'key': 'hpc_contact',     'label': 'HPC帳號管理',  'icon': '👥', 'path': '/hpc-contact'},
    {'key': 'hpc_usage',       'label': 'HPC 用量通知', 'icon': '📊', 'path': '/hpc-usage'},
    {'key': 'hpc_billing_review', 'label': 'HPC 帳務審核', 'icon': '💰', 'path': '/hpc-billing-review'},
    {'key': 'space_stats',     'label': 'Space 統計資料', 'icon': '📈', 'path': '/space-stats'},
    {'key': 'setting',         'label': '設定',         'icon': '⚙️', 'path': '/setting'},
    {'key': 'permission',      'label': '權限管理',     'icon': '🔑', 'path': '/permission'},
]

ALL_FEATURE_KEYS = [f['key'] for f in FEATURES]
FEATURE_BY_KEY = {f['key']: f for f in FEATURES}

# 不需要任何權限就能存取的 endpoint（登入流程、等候頁面、登出、個人資料）
#
# 個人資料頁（routes.profile / profile.*）是「每個人設定自己的名字與聯絡信箱」，
# 不屬於側邊欄的功能清單，因此不放進 FEATURES，也不需要任何權限；
# 連尚未被開通的使用者都能填寫。它只會讀寫 session['user_id'] 自己的那一筆，
# 與需要 setting 權限的系統「設定」頁面（發信帳號）無關。
PUBLIC_ENDPOINTS = {
    'static',
    'routes.login_page',
    'routes.pending_approval',
    'routes.profile',
    'login.login',
    'login.callback',
    'login.logout',
    'login.check_session',
    'permission.get_my_permissions',
    'profile.get_my_profile',
    'profile.save_my_profile',
}

# 頁面 endpoint → 所需功能
PAGE_FEATURE_MAP = {
    'routes.batch_sending':   'batch_sending',
    'routes.edit_templates':  'edit_templates',
    'routes.mailbox_manager': 'mailbox_manager',
    'routes.hpc_contact':     'hpc_contact',
    'routes.hpc_usage':       'hpc_usage',
    'routes.hpc_billing_review': 'hpc_billing_review',
    'routes.space_stats':     'space_stats',
    'routes.setting':         'setting',
    'routes.permission':      'permission',
}

# Blueprint → 預設所需功能。
# 用 blueprint 當預設值的好處是：日後在既有 blueprint 新增 API，
# 會自動被納入保護，而不是預設全開。
BLUEPRINT_FEATURE_MAP = {
    'email':      'batch_sending',
    'template':   'edit_templates',
    'mailbox':    'mailbox_manager',
    'contact':    'hpc_contact',
    'quota':      'hpc_contact',
    'hpc':        'hpc_usage',
    'billing':    'hpc_billing_review',
    'setting':    'setting',
    'permission': 'permission',
}

# 跨頁面共用的 API：除了 blueprint 預設值之外，額外允許的功能。
# 例如「寄送郵件」頁面需要讀取信箱與模板清單，但不應因此獲得
# 信箱管理／模板編輯的修改權限，所以多數只開放 GET。
ENDPOINT_EXTRA_FEATURES = {
    # 寄送郵件頁：讀取收件信箱分組、讀取郵件模板
    'mailbox.get_mailboxes':                  {'features': {'batch_sending'},  'methods': {'GET'}},
    'template.handle_templates':              {'features': {'batch_sending'},  'methods': {'GET'}},
    # 寄送郵件頁的「帳號新增」：搜尋 HPC 帳號並取得該帳號底下聯絡人的 Email
    'contact.search_mail_accounts':           {'features': {'batch_sending'},  'methods': {'GET'}},
    # HPC 用量通知頁的「確認信預設副本人員」設定，與帳號管理頁共用同一份設定
    'contact.get_confirm_email_default_cc':   {'features': {'hpc_usage'},      'methods': None},
    'contact.save_confirm_email_default_cc':  {'features': {'hpc_usage'},      'methods': None},
    # HPC 帳號管理頁需要主機清單、帳號搜尋與額度設定
    'hpc.search_users':                       {'features': {'hpc_contact'},    'methods': {'GET'}},
    'hpc.get_server_list':                    {'features': {'hpc_contact'},    'methods': {'GET'}},
    'hpc.hpc_quota_settings':                 {'features': {'hpc_contact'},    'methods': None},
}


# 研究獎勵／免費折抵額度的 source_id 前綴。
# 實際寫入的格式為 RESEARCH_<類型>_<年份>_<uuid>，例如：
#   RESEARCH_FREE_2026_xxxxxxxx      （免費研究折抵）
#   RESEARCH_ACADEMIC_2026_xxxxxxxx  （學術獎勵）
#
# ⚠️ 這個常數一定要由「寫入端」與「判斷端」共用。
# 過去發放端曾經是 RESEARCH_BONUS_<年份>_，後來拆成 FREE / ACADEMIC 兩種類型時
# 只改了發放端，扣款端仍寫死比對 'RESEARCH_BONUS_'，導致「限當年帳單折抵」與
# 「優先扣抵」兩條規則一直沒有生效。之後要再新增獎勵類型，只要沿用這個前綴即可。
RESEARCH_BONUS_SOURCE_PREFIX = 'RESEARCH_'

CONFIRM_EMAIL_TEMPLATE_KEY = 'confirm_email_template'
CONFIRM_EMAIL_DEFAULT_CC_KEY = 'confirm_email_default_cc'

# 「寄送繳費單」用的通知信範本（信件本文；報價單本身另外轉成 PDF 當附件）。
# 與確認信範本一樣採「資料庫有自訂版就用自訂版，否則退回 templates/ 底下的檔案」。
BILL_NOTIFICATION_TEMPLATE_KEY = 'bill_notification_template'

# user profile utils
# 基本格式檢查即可：真正能不能收信只有寄出去才知道，
# 這裡擋的是明顯的錯字（少了 @、少了網域）。
EMAIL_PATTERN = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
NAME_MAX_LENGTH = 100
CONTACT_EMAIL_MAX_LENGTH = 120

# smpt config
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