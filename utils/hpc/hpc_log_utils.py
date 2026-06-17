
import os
import json
from  utils.params import HPC_NOTIFICATIONS_DIR
from datetime import datetime

def save_hpc_notification_log(notification_record):
    """
    將單筆通知紀錄儲存到對應的日期檔案中，並自動建立不存在的資料夾。
    notification_record: 包含 'timestamp', 'message', 'usage' 的字典。
    """
    # 確保根目錄存在
    os.makedirs(HPC_NOTIFICATIONS_DIR, exist_ok=True)
    
    timestamp_str = notification_record['timestamp']
    try:
        record_time = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        print("錯誤: 時間戳格式不正確，無法儲存此紀錄。")
        return

    # 根據時間戳建立分層的資料夾路徑
    year_dir = os.path.join(HPC_NOTIFICATIONS_DIR, record_time.strftime('%Y'))
    month_dir = os.path.join(year_dir, record_time.strftime('%m'))
    file_path = os.path.join(month_dir, f"{record_time.strftime('%d')}.json")

    # 檢查並建立資料夾，exist_ok=True 可確保即使資料夾已存在也不會報錯
    os.makedirs(month_dir, exist_ok=True)

    # 讀取現有紀錄，若檔案不存在則建立新清單
    daily_records = []
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                daily_records = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            pass
    
    # 將新紀錄新增到清單
    daily_records.append(notification_record)

    # 將更新後的清單寫回檔案
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(daily_records, f, ensure_ascii=False, indent=4)
    
    print(f"新紀錄已成功儲存至 {file_path}")
