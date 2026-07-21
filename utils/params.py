import os
from dotenv import load_dotenv

load_dotenv()

# 配置郵件伺服器
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT"))
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
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