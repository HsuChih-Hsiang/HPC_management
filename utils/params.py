import os
from dotenv import load_dotenv

load_dotenv()

# 配置郵件伺服器
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT"))
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")

# HPC settings
HPC_NOTIFICATIONS_DIR = os.path.join('log', 'hpc_notifications')

# 信箱分組數據文件路徑
UNASSIGNED_GROUP_ID = 0
UNASSIGNED_GROUP_NAME = "待分組信箱"