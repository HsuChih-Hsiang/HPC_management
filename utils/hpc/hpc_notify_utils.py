from flask import current_app
from sqlalchemy import desc, func
from flask import render_template
from utils.hpc.hpc_bill_utils import get_hpc_user_and_total_usage_with_details
from utils.hpc.hpc_setting_utils import load_hpc_settings_by_classification
from utils.email_utils import send_hpc_notification_email
from database.extensions import db
from database.hpc_model import NotificationHistory
from datetime import datetime, timedelta



# --- HPC 用量通知紀錄 ---
# 後續補搜尋
def get_hpc_notifications_by_date(start_date_str, end_date_str, page=None, limit=None):
    """
    從 NotificationHistory 資料庫表中獲取 HPC 用量通知紀錄。
    支援日期範圍篩選，並可選分頁功能。
    
    Args:
        start_date_str (str): 起始日期字串 (YYYY-MM-DD)。
        end_date_str (str): 結束日期字串 (YYYY-MM-DD)。
        page (int, optional): 當前頁碼，從 1 開始。若為 None，則不分頁。
        limit (int, optional): 每頁顯示的紀錄數。若為 None，則不分頁。

    Returns:
        tuple: (紀錄列表, 總紀錄數)
    """
    try:
        start_datetime = datetime.strptime(start_date_str, '%Y-%m-%d') if start_date_str else None
        end_datetime = (datetime.strptime(end_date_str, '%Y-%m-%d') + timedelta(days=1)) if end_date_str else None

        with current_app.app_context():
            query = NotificationHistory.query

            if start_datetime:
                query = query.filter(NotificationHistory.notified_at >= start_datetime)
            if end_datetime:
                query = query.filter(NotificationHistory.notified_at < end_datetime)

            query = query.order_by(desc(NotificationHistory.notified_at))
            total_records = query.count()

            if page is not None and limit is not None and page > 0 and limit > 0:
                offset = (page - 1) * limit
                final_records_query = query.offset(offset).limit(limit)
            else:
                final_records_query = query

            paginated_records = []
            for record in final_records_query.all():
                paginated_records.append({
                    'id': record.id,
                    'username': record.username,
                    'notification_type': record.notification_type,
                    'notified_at': record.notified_at.strftime('%Y-%m-%d %H:%M:%S'), 
                    'year': record.year,
                    'message': record.message, 
                    'amount': record.amount   
                })

        return paginated_records, total_records

    except ValueError as e:
        current_app.logger.error(f"日期格式錯誤: {e}")
        return [], 0
    except Exception as e:
        current_app.logger.error(f"查詢歷史紀錄時發生錯誤: {e}")
        return [], 0


# --- HPC notify ---
def check_hpc_usage_and_notify():
    """
    根據設定檢查 HPC 用量並發送通知，使用資料庫進行歷史紀錄管理。
    """
    # 假設 load_hpc_settings 已經使用資料庫版本，如 hpc_setting_utils.py 所示
    settings = load_hpc_settings_by_classification(1)
    cooldown_days = settings.get('notification_cooldown_days', 7)
    check_period_days = settings.get('check_period', 30)
    
    # 獲取 HPC 各用量數據
    yearly_usage, recent_usage = get_hpc_user_and_total_usage_with_details(check_period_days) 
    
    # --- 檢查年度總用量閾值 ---
    MESSAGE_TYPE_YEARLY = "年度總用量通知" 
    NOTIFICATION_TYPE_THRESHOLD = 1 # 假設 1 為 threshold 通知類型
    
    for username, user_yearly_usage_data in yearly_usage.items():
        user_total_price = user_yearly_usage_data['total_price']

        if user_total_price >= settings['price_threshold']:
            
            # 使用資料庫檢查冷卻期 (取代原檔案遍歷邏輯)
            if is_in_cooldown_period_db(username, MESSAGE_TYPE_YEARLY, cooldown_days):
                print(f"使用者 {username} 在冷卻期 ({cooldown_days} 天) 內已收到年度總用量通知，跳過本次發送。")
                continue

            # user_email = get_user_email_from_db(username) # 恢復為使用 DB 獲取 Email
            user_email = "chh0410@ntu.edu.tw" # 測試用 Email

            if not user_email:
                print(f"找不到使用者 {username} 的 email，跳過發送。")
                continue

            emails_to_notify = [user_email]

            # 渲染年度總用量通知的 HTML 內容
            notification_message = render_template(
                'notification_template.html',
                username=username,
                total_price=user_total_price,
                threshold=settings['price_threshold'],
                details=user_yearly_usage_data['details'],
                message_type="年度總用量提醒",
                period_description="本年度"
            )
            subject = "HPC 用量提醒"

            if send_hpc_notification_email(emails_to_notify, subject, notification_message):
                
                # 將通知紀錄儲存到資料庫 (取代 save_hpc_notification_log 和 save_notified_emails_history_log)
                save_notification_to_db(
                    username=username,
                    notification_type=NOTIFICATION_TYPE_THRESHOLD,
                    message=MESSAGE_TYPE_YEARLY, 
                    amount=user_total_price
                )
                
                print(f"已向信箱 {user_email} 發送年度總用量閾值通知。")
            else:
                print(f"發送年度總用量通知給 {user_email} 失敗。")


    # --- 檢查近期用量增長閾值 ---
    MESSAGE_TYPE_RECENT = "近期用量增長通知" 
    NOTIFICATION_TYPE_GROWTH = 2 # 假設 2 為 growth 通知類型
    
    for username, user_recent_usage_data in recent_usage.items():
        user_recent_price = user_recent_usage_data['total_price']
        
        if user_recent_price >= settings['diff_price_threshold']:
            
            # 使用資料庫檢查冷卻期
            if is_in_cooldown_period_db(username, MESSAGE_TYPE_RECENT, cooldown_days):
                print(f"使用者 {username} 處於通知冷卻期 ({cooldown_days} 天) 內，跳過本次通知。")
                continue
            
            # user_email = get_user_email_from_db(username) # 恢復為使用 DB 獲取 Email
            user_email = "chh0410@ntu.edu.tw" # 測試用 Email

            if not user_email:
                print(f"找不到使用者 {username} 的 email，跳過發送。")
                continue
            
            emails_to_notify = [user_email]

            # 渲染近期用量增長通知的 HTML 內容
            notification_message = render_template(
                'notification_template.html',
                username=username,
                total_price=user_recent_price,
                threshold=settings['diff_price_threshold'],
                details=user_recent_usage_data['details'],
                message_type="近期用量增長提醒",
                period_description=f"過去 {settings['check_period']} 天內"
            )
            subject = "HPC 用量增長提醒"
            
            if send_hpc_notification_email(emails_to_notify, subject, notification_message):
                
                # 將通知紀錄儲存到資料庫
                save_notification_to_db(
                    username=username,
                    notification_type=NOTIFICATION_TYPE_GROWTH,
                    message=MESSAGE_TYPE_RECENT, 
                    amount=user_recent_price
                )
                
                print(f"已向信箱 {user_email} 發送近期用量增長通知。")
            else:
                print(f"發送近期用量增長通知給 {user_email} 失敗。")


def save_notification_to_db(username: str, notification_type: int, message: str, amount: float):
    """將 HPC 用量通知紀錄儲存到資料庫"""
    try:
        with current_app.app_context():
            new_record = NotificationHistory(
                username=username,
                notification_type=notification_type,
                notified_at=datetime.now(),
                year=datetime.now().year,
                message=message,
                amount=amount
            )
            db.session.add(new_record)
            db.session.commit()
            current_app.logger.info(f"已將通知紀錄儲存到資料庫: {username}, {message}")
            return True
    except Exception as e:
        current_app.logger.error(f"儲存通知紀錄到資料庫時發生錯誤: {e}")
        db.session.rollback()
        return False

def is_in_cooldown_period_db(username: str, message_type: str, cooldown_days: int) -> bool:
    """
    檢查使用者是否在通知冷卻期內。

    Args:
        username: 使用者名稱。
        message_type: 通知訊息的類型關鍵字 (用於在 message 欄位中模糊匹配，例如 '年度總用量通知')。
        cooldown_days: 冷卻期天數。

    Returns:
        bool: 如果在冷卻期內，返回 True；否則返回 False。
    """
    cooldown_start_date = datetime.now() - timedelta(days=cooldown_days)
    
    with current_app.app_context():
        # 查詢在冷卻期內且包含特定訊息關鍵字的最新紀錄
        # 使用 LIKE 進行模糊匹配，以應對 message 欄位可能包含其他文字
        recent_notification = NotificationHistory.query.filter(
            NotificationHistory.username == username,
            NotificationHistory.notified_at >= cooldown_start_date,
            NotificationHistory.message.like(f'%{message_type}%')
        ).first()

        return recent_notification is not None