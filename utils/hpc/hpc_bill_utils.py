import json
from utils.hpc.hpc_setting_utils import load_hpc_settings_by_classification
from sqlalchemy import func, cast, Numeric, and_
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
    # Serverlist 同一個 server 可能有多筆不同 queue 的價格，join 一定要帶上 queue，
    # 否則同一筆 job 會對到多筆價格造成金額被重複加總
    ).join(Serverlist, and_(Accounting.host == Serverlist.server, Accounting.queue == Serverlist.queue)).group_by(
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
    # Serverlist 同一個 server 可能有多筆不同 queue 的價格，join 一定要帶上 queue，
    # 否則同一筆 job 會對到多筆價格造成金額被重複加總
    yearly_results = db.session.query(
        Accounting.username,
        func.sum(
            (Accounting.cores * (Accounting.wtime / 3600)) * Serverlist.price
        ).label('total_price')
    ).join(Serverlist, and_(Accounting.host == Serverlist.server, Accounting.queue == Serverlist.queue)).filter(
        func.extract('year', Accounting.endtime) == current_year
    ).group_by(Accounting.username).all()

    recent_results = db.session.query(
        Accounting.username,
        func.sum(
            (Accounting.cores * (Accounting.wtime / 3600)) * Serverlist.price
        ).label('total_price')
    ).join(Serverlist, and_(Accounting.host == Serverlist.server, Accounting.queue == Serverlist.queue)).filter(
        Accounting.endtime >= recent_period_start
    ).group_by(Accounting.username).all()

    # 將查詢結果轉換為字典格式
    yearly_usage = {row.username: float(row.total_price) for row in yearly_results}
    recent_usage = {row.username: float(row.total_price) for row in recent_results}
    
    return yearly_usage, recent_usage

def get_account_last_year_usage_details(username):
    """
    計算單一帳號「去年度」依主機+queue分組的 HPC 使用量明細，供確認信範本
    (templates/email/quotation_check_email.html) 的動態使用量表格使用。

    計算公式與 hpc_quota_routes.calculate_pending_bill / contact_routes.get_hpc_statistics
    保持一致：SU = cores * (wtime 秒數 / 3600) * 該主機當時的單價。

    注意：Serverlist 同一個 server 可能有多筆不同 queue 的價格設定，
    因此 join 條件除了 host 還必須帶上 queue，否則同一筆 Accounting
    job 會同時對到該 host 底下的多個 queue 價格，造成總額被重複加總、灌水。

    Returns:
        dict: {
            'usage_year': int,                 去年度年份
            'usage_rows': [{'host', 'queue', 'job_count', 'su'}, ...],  依主機+queue分組明細
            'usage_total_su': float            該帳號去年度總 SU
        }
    """
    last_year = datetime.now().year - 1

    results = db.session.query(
        Accounting.host,
        Accounting.queue,
        func.count(Accounting.jobid).label('job_count'),
        func.sum((Accounting.cores * (cast(Accounting.wtime, Numeric) / 3600)) * Serverlist.price).label('su')
    ).join(
        Serverlist,
        (Accounting.host == Serverlist.server) & (Accounting.queue == Serverlist.queue)
    ).filter(
        Accounting.username == username,
        func.extract('year', Accounting.endtime) == last_year
    ).group_by(Accounting.host, Accounting.queue).order_by(Accounting.host, Accounting.queue).all()

    usage_rows = [
        {
            'host': row.host,
            'queue': row.queue,
            'job_count': row.job_count or 0,
            'su': round(float(row.su or 0), 2)
        }
        for row in results
    ]
    usage_total_su = round(sum(row['su'] for row in usage_rows), 2)

    return {
        'usage_year': last_year,
        'usage_rows': usage_rows,
        'usage_total_su': usage_total_su
    }

def get_usage_and_prepaid_data_db(min_usage_threshold=10000):
    """
    【資料庫版本】
    整合HPC年度用量、預繳金額和年度通知狀態。

    Args:
        min_usage_threshold (float): 本年度使用量 (SU) 顯示門檻，只有超過此門檻的帳號
            才會被列入清單，供 /api/hpc-usage/prepaid 讓前端動態調整（預設 10000）。
    """
    current_year = datetime.now().year
    
    # 1. 獲取年度總用量 (這部分不變)
    yearly_usage, _ = get_hpc_user_and_total_usage_with_details()
    
    # 2. 從資料庫獲取預繳金額（自費金額 + 優惠額度）
    # 只計入「已付款 (is_paid=True) 且非歷史封存 (is_history=False)」的紀錄，
    # 且同一帳號可能有多筆年度紀錄要加總，
    # 邏輯對齊 database/hpc_model.py 的 Contact.to_dict() 中 total_remaining 的算法，
    # 確保這裡跟聯絡人管理頁面看到的「剩餘總額度」定義一致。
    prepaid_records = PrepaidAmount.query.filter_by(is_paid=True, is_history=False).all()
    prepaid_amounts = {}
    for record in prepaid_records:
        prepaid_amounts[record.username] = (
            prepaid_amounts.get(record.username, 0.0)
            + float(record.amount or 0)
            + float(record.discount or 0)
        )
    
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
        
        if yearly_usage_rounded > min_usage_threshold :
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


def calculate_prepaid_quota(deposit_amount):
    """
    根據預繳金額計算最終獲得的額度
    :param deposit_amount: 預繳金額 (例如 60000)
    :return: 計算後的總額度 (四捨五入或取整數)
    """
    # 1. 從 DB 取出設定清單
    settings_list = load_hpc_settings_by_classification(2)
    
    # 2. 從 List 中找到 key 為 'discount' 的那一筆資料
    discount_item = next((item for item in settings_list if item.get('key') == 'discount'), {})
    discounts_raw = discount_item.get('value', [])
    
    # 3. 解析 discounts (處理字串或直接是 List/Dict 的情況)
    if isinstance(discounts_raw, str):
        try:
            discounts = json.loads(discounts_raw)
        except json.JSONDecodeError:
            discounts = []
    elif isinstance(discounts_raw, list):
        discounts = discounts_raw
    else:
        discounts = []

    # 4. 動態 If-Else 判斷與算式套用
    for rule in discounts:
        if not isinstance(rule, dict):
            continue
            
        min_amount = rule.get('min_amount', 0)
        divisor = rule.get('divisor', 1.0)
        
        if deposit_amount >= min_amount:
            if divisor != 0:
                return round(deposit_amount / divisor)
            break

    # 若未達任何優惠門檻，回傳原始預繳金額
    return deposit_amount