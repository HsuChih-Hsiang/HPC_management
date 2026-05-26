from sqlalchemy import func
from database.hpc_model import Accounting, PrepaidAmount, NotificationHistory, Serverlist
from datetime import datetime, timedelta
from database.extensions import db



def get_hpc_user_and_total_usage_with_details(check_period_days):
    """
    計算每個帳號在當年度和指定時間範圍內的總費用，並提供每個 server 的明細。

    Args:
        check_period_days (int): 用於計算近期用量的天數。

    Returns:
        tuple: 包含當年度用量和近期用量的字典。
               每個字典的 key 是使用者名稱，value 是一個包含 'total_price' 和 'details' 的字典。
               'details' 是一個字典，key 是 server 名稱，value 是該 server 的花費。
               例如: (yearly_usage, recent_usage)
               yearly_usage = {
                   'user1': {
                       'total_price': 1000.0,
                       'details': {
                           'serverA': 600.0,
                           'serverB': 400.0
                       }
                   },
                   'user2': { ... }
               }
    """
    current_year = datetime.now().year
    recent_period_start = datetime.now() - timedelta(days=check_period_days)
    
    # 執行 SQL 聯結查詢，並計算每個使用者在每個 server 上的花費
    # 這邊除了 username 和 total_price 外，還會選擇 servername
    base_query = db.session.query(
        Accounting.username,
        Serverlist.server,  # 選擇 servername
        func.sum(
            (Accounting.cores * (Accounting.wtime / 3600)) * Serverlist.price
        ).label('total_price')
    ).join(Serverlist, Accounting.host == Serverlist.server).group_by(
        Accounting.username, Serverlist.server  # 以 username 和 servername 分組
    )
    
    # 過濾出當年度的資料
    yearly_results = base_query.filter(
        func.extract('year', Accounting.endtime) == current_year
    ).all()

    # 過濾出近期內的資料
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
        
        # 累加總花費，並記錄每個 server 的花費
        cost = float(row.total_price)
        yearly_usage[row.username]['total_price'] += cost
        yearly_usage[row.username]['details'][row.server] = cost

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
    yearly_usage, _ = get_hpc_user_and_total_usage_with_details(365)
    
    # 2. 從資料庫獲取預繳金額
    prepaid_records = PrepaidAmount.query.all()
    prepaid_amounts = {record.username: record.amount for record in prepaid_records}
    
    # 3. 從資料庫獲取今年已通知預繳金額超額的使用者
    notified_users_records = db.session.query(NotificationHistory.username).filter(
        NotificationHistory.year == current_year,
        NotificationHistory.notification_type == 'prepaid'
    ).distinct().all()
    notified_this_year = {record.username for record in notified_users_records}

    # 4. 組合資料
    combined_data = []
    all_users = set(yearly_usage.keys()) | set(prepaid_amounts.keys())

    for user in all_users:
        usage_data = yearly_usage.get(user, {'total_price': 0.0})
        prepaid = prepaid_amounts.get(user, 0.0)
        
        combined_data.append({
            'username': user,
            'yearly_usage': round(usage_data['total_price'], 2),
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