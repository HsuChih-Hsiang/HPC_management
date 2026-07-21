from sqlalchemy import func
from database.extensions import db
from database.hpc_model import Accounting, PrepaidAmount, NotificationHistory, Serverlist
from datetime import datetime, timedelta


def get_hpc_user_and_total_usage_with_details():
    """
    計算每個帳號在當年度和【今年初至今】的總費用，並提供每個 server 的明細。

    Args:
        check_period_days (int, optional): 原本用於計算近期用量，現已改為計算今年初至今，此參數可留空。

    Returns:
        tuple: 包含當年度用量和今年初至今用量的字典。
               每個字典的 key 是使用者名稱，value 是一個包含 'total_price' 和 'details' 的字典。
    """
    current_year = datetime.now().year
    
    # 關鍵修改：將近期計算的起點，設定為當年度的 1 月 1 日 0 點 0 分 0 秒
    recent_period_start = datetime(current_year, 1, 1, 0, 0, 0)
    
    # 執行 SQL 聯結查詢，並計算每個使用者在每個 server 上的花費
    base_query = db.session.query(
        Accounting.username,
        Serverlist.server,
        func.sum(
            (Accounting.cores * (Accounting.wtime / 3600)) * Serverlist.price
        ).label('total_price')
    ).join(Serverlist, Accounting.host == Serverlist.server).group_by(
        Accounting.username, Serverlist.server
    )
    
    # 過濾出當年度的資料（依據年份標籤）
    yearly_results = base_query.filter(
        func.extract('year', Accounting.endtime) == current_year
    ).all()

    # 過濾出今年初到現在的資料（依據時間戳記大於等於 1/1）
    recent_results = base_query.filter(
        Accounting.endtime >= recent_period_start
    ).all()

    # 將查詢結果轉換為所需的巢狀字典格式
    yearly_usage = {}
    for row in yearly_results:
        if row.username not in yearly_usage:
            yearly_usage[row.username] = {
                'total_price': 0.0,
                'details': {}
            }
        
        cost = float(row.total_price)
        yearly_usage[row.username]['total_price'] += cost
        yearly_usage[row.username]['details'][row.server] = cost

    # 這邊算出來的就是「今年初至今」的數據了
    recent_usage = {}
    for row in recent_results:
        if row.username not in recent_usage:
            recent_usage[row.username] = {
                'total_price': 0.0,
                'details': {}
            }

        cost = float(row.total_price)
        recent_usage[row.username]['total_price'] += cost
        recent_usage[row.username]['details'][row.server] = cost
        
    return yearly_usage, recent_usage

def get_hpc_user_and_total_usage(check_period_days):
    """
    計算每個帳號在當年度和指定時間範圍內的總費用。
    
    Args:
        check_period_days (int): 用於計算近一段時間用量的天數。
    
    Returns:
        tuple: 包含當年度用量和近期用量的字典，格式為
               (yearly_usage, recent_usage)
               例如: ({'user1': 1000, 'user2': 500}, {'user1': 50, 'user2': 20})
    """
    
    current_year = datetime.now().year
    
    # 計算時間點
    recent_period_start = datetime.now() - timedelta(days=check_period_days)
    
    # 執行 SQL 聯結查詢並計算費用
    # 計算 job 執行的小時數 (wtime / 3600)
    yearly_results = db.session.query(
        Accounting.username,
        func.sum(
            (Accounting.cores * (Accounting.wtime / 3600)) * Serverlist.price
        ).label('total_price')
    ).join(Serverlist, Accounting.host == Serverlist.server).filter(
        func.extract('year', Accounting.endtime) == current_year
    ).group_by(Accounting.username).all()

    recent_results = db.session.query(
        Accounting.username,
        func.sum(
            (Accounting.cores * (Accounting.wtime / 3600)) * Serverlist.price
        ).label('total_price')
    ).join(Serverlist, Accounting.host == Serverlist.server).filter(
        Accounting.endtime >= recent_period_start
    ).group_by(Accounting.username).all()

    # 將查詢結果轉換為字典格式
    yearly_usage = {row.username: float(row.total_price) for row in yearly_results}
    recent_usage = {row.username: float(row.total_price) for row in recent_results}
    
    return yearly_usage, recent_usage

def get_usage_and_prepaid_data_db():
    """
    【資料庫版本】
    整合HPC年度用量、預繳金額和年度通知狀態。
    """
    current_year = datetime.now().year
    
    # 1. 獲取年度總用量 (這部分不變)
    yearly_usage, _ = get_hpc_user_and_total_usage_with_details()
    
    # 2. 從資料庫獲取預繳金額
    prepaid_records = PrepaidAmount.query.all()
    prepaid_amounts = {record.username: record.amount for record in prepaid_records}
    
    # 3. 從資料庫獲取今年已通知預繳金額超額的使用者
    notified_users_records = db.session.query(NotificationHistory.username).filter(
        NotificationHistory.year == current_year,
        NotificationHistory.notification_type == 0
    ).distinct().all()
    notified_this_year = {record.username for record in notified_users_records}

    # 4. 組合資料
    combined_data = []
    all_users = set(yearly_usage.keys()) | set(prepaid_amounts.keys())

    for user in all_users:
        if user.startswith('gst'):
            continue

        usage_data = yearly_usage.get(user, {'total_price': 0.0})
        yearly_usage_rounded = round(usage_data['total_price'], 2)
        
        if yearly_usage_rounded > 10000 :
            prepaid = prepaid_amounts.get(user, 0.0)
            
            combined_data.append({
                'username': user,
                'yearly_usage': yearly_usage_rounded,
                'prepaid_amount': float(prepaid),
                'notified': user in notified_this_year
            })
    
    return combined_data

def update_prepaid_amount_db(username, amount):
    """【資料庫版本】更新或建立使用者的預繳金額紀錄。"""
    record = PrepaidAmount.query.filter_by(username=username).first()
    if record:
        record.amount = amount
    else:
        record = PrepaidAmount(username=username, amount=amount)
        db.session.add(record)
    db.session.commit()