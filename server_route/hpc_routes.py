import json
from datetime import datetime
from flask import Blueprint, request, jsonify, render_template
from utils.hpc.hpc_setting_utils import (load_hpc_settings_by_classification, save_hpc_settings,
                                          load_bill_discount, BILL_DISCOUNT_KEY)
from utils.hpc.hpc_notify_utils import get_hpc_notifications_by_date, send_hpc_notification_email, save_notification_to_db
from utils.hpc.hpc_log_utils import save_hpc_notification_log
from utils.hpc.hpc_bill_utils import get_usage_and_prepaid_data_db, update_prepaid_amount_db
from database.extensions import db
from database.hpc_model import Serverlist, UserAccounting

hpc_bp = Blueprint('hpc', __name__)

# API 路由：獲取 HPC 用量通知紀錄
@hpc_bp.route('/api/hpc-usage/history', methods=['GET'])
def get_hpc_history():
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 10, type=int)

    notifications, total_records = get_hpc_notifications_by_date(start_date_str, end_date_str, page, limit)

    return jsonify({
        'records': notifications,
        'total_records': total_records
    })

# API 路由：儲存與讀取 HPC 用量設定
@hpc_bp.route('/api/hpc-usage/settings', methods=['GET', 'POST'])
def hpc_notify_settings():
    if request.method == 'GET':
        current_settings = load_hpc_settings_by_classification(1)
        return jsonify(current_settings)

    elif request.method == 'POST':
        data = request.get_json()
        price_threshold = data.get('price_threshold')
        check_interval = data.get('check_interval')
        diff_price_threshold = data.get('diff_price_threshold')
        check_period = data.get('check_period')
        notification_cooldown_days = data.get('notification_cooldown_days')
        classification = data.get('classification')  # 1. 提取新欄位

        # 2. 加入必要欄位檢查
        if not all([
            price_threshold is not None, 
            check_interval is not None, 
            diff_price_threshold is not None,  # 建議 diff_price_threshold 也加入必填檢查
            check_period is not None, 
            notification_cooldown_days is not None,
            classification is not None
        ]):
            return jsonify({'success': False, 'message': '缺少必要的設定參數。'}), 400
        
        try:
            price_threshold = int(price_threshold)
            check_interval = int(check_interval)
            diff_price_threshold = int(diff_price_threshold)
            check_period = int(check_period)
            notification_cooldown_days = int(notification_cooldown_days)
            classification = int(classification)  # 3. 轉為整數
            
            # 4. 檢查範圍（假設 classification 必須大於等於 0，若可為負值請依需求調整）
            if not (price_threshold >= 0 and 
                    check_interval > 0 and 
                    check_period > 0 and 
                    diff_price_threshold >= 0 and 
                    notification_cooldown_days >= 0 and 
                    classification > 0):
                return jsonify({'success': False, 'message': '設定參數數值無效，請檢查範圍。'}), 400

        except (ValueError, TypeError):  # 建議加上 TypeError 防止傳入非字串/數字型態 (如 list/dict)
            print('2')
            return jsonify({'success': False, 'message': '設定參數格式不正確，請輸入數字。'}), 400

        # 5. 寫入儲存字典
        new_settings = {
            'price_threshold': price_threshold,
            'check_interval': check_interval,
            'diff_price_threshold': diff_price_threshold,
            'check_period': check_period,
            'notification_cooldown_days': notification_cooldown_days,
            'classification': classification
        }
        save_hpc_settings(new_settings)
        
        return jsonify({'success': True, 'message': '設定已成功儲存。'})

@hpc_bp.route('/api/hpc-usage/settings_free_quota', methods=['GET', 'POST'])
def hpc_quota_settings():
    if request.method == 'GET':
        current_settings = load_hpc_settings_by_classification(2)
        return jsonify(current_settings)

    elif request.method == 'POST':
        data = request.get_json() or {}
        
        free_quota = data.get('free_quota')
        academic_quota = data.get('academic_quota')
        prepay_discounts = data.get('prepay_discounts')  # 前端傳入 List

        if free_quota is None or academic_quota is None:
            return jsonify({'success': False, 'message': '缺少必要的設定參數。'}), 400
        
        try:
            free_quota = int(free_quota)
            academic_quota = int(academic_quota)
            
            # 處理階梯算式設定
            discounts_json = "[]"
            if prepay_discounts and isinstance(prepay_discounts, list):
                # 依門檻金額由大到小排序 (確保 > 100001 先判斷)
                sorted_discounts = sorted(
                    prepay_discounts, 
                    key=lambda x: x.get('min_amount', 0), 
                    reverse=True
                )
                discounts_json = json.dumps(sorted_discounts)

        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': '參數格式不正確。'}), 400

        # 寫入資料庫
        # 注意：
        #  1. key 必須是 'discount'（跟 DEFAULT_HPC_SETTINGS / calculate_prepaid_quota 讀取的 key 一致），
        #     用 'prepay_discounts' 存的話，實際計算優惠時永遠讀不到剛存的值。
        #  2. save_hpc_settings 沒收到 classification 時預設是 1，這三筆設定原本屬於分類 2，
        #     不帶的話存檔會把它們的 classification 也一併改成 1，後續用分類 2 讀取就會全部撈不到。
        new_settings = {
            'free_quota': free_quota,
            'academic_quota': academic_quota,
            'discount': discounts_json,
            'classification': 2
        }
        save_hpc_settings(new_settings)
        
        return jsonify({'success': True, 'message': '設定已成功儲存。'})


@hpc_bp.route('/api/hpc-usage/settings_bill_discount', methods=['GET', 'POST'])
def hpc_bill_discount_settings():
    """
    開帳單折扣設定（HPCSetting key='bill_discount'，classification=2）。

    規則：本期應收總金額超過「門檻金額 min_amount」時，
          「超出的部分」以 discount 折計算，門檻以內的金額不打折：

              結算價格 = min_amount + (應收總金額 - min_amount) × discount / 10

    discount 存的是「折數」（8.5 = 8.5 折 = 85%），與 UI 上填的數字一致，
    避免有人看資料庫時把 0.85 誤解成「打 0.85 折」。
    傳入空的 min_amount 或 discount 代表「清除設定」，存成空字典。
    """
    if request.method == 'GET':
        return jsonify(load_bill_discount())

    data = request.get_json() or {}
    min_amount = data.get('min_amount')
    discount = data.get('discount')

    # 兩欄都空 = 清除設定（畫面上就不再顯示折扣與結算價格）
    is_blank = lambda v: v is None or (isinstance(v, str) and not v.strip())
    if is_blank(min_amount) and is_blank(discount):
        save_hpc_settings({BILL_DISCOUNT_KEY: json.dumps({}), 'classification': 2})
        return jsonify({'success': True, 'message': '已清除帳單折扣設定。', 'value': {}})

    if is_blank(min_amount) or is_blank(discount):
        return jsonify({'success': False, 'message': '門檻金額與折數必須一起填寫，或兩者都留空以清除設定。'}), 400

    try:
        min_amount = float(min_amount)
        discount = float(discount)
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': '門檻金額與折數必須是數字。'}), 400

    if min_amount < 0:
        return jsonify({'success': False, 'message': '門檻金額不可為負數。'}), 400
    if not (0 < discount <= 10):
        return jsonify({'success': False, 'message': '折數必須大於 0 且不超過 10（10 折 = 不打折）。'}), 400

    value = {'min_amount': min_amount, 'discount': discount}
    save_hpc_settings({BILL_DISCOUNT_KEY: json.dumps(value), 'classification': 2})

    return jsonify({'success': True, 'message': '帳單折扣設定已儲存。', 'value': value})


@hpc_bp.route('/api/hpc-usage/prepaid', methods=['GET'])
def get_prepaid_data():
    filter_exceeded = request.args.get('filter_exceeded', 'false').lower() == 'true'
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 10, type=int)
    min_usage = request.args.get('min_usage', 10000, type=float)

    all_data = get_usage_and_prepaid_data_db(min_usage)

    if filter_exceeded:
        all_data = [d for d in all_data if d['yearly_usage'] > d['prepaid_amount']]

    all_data.sort(key=lambda x: x['username'])

    total_records = len(all_data)
    start_index = (page - 1) * limit
    end_index = start_index + limit
    paginated_data = [
        {
            'username': d['username'],
            'prepaid_limit': d['prepaid_amount'],
            'yearly_usage': d['yearly_usage'],
            'notification_status': '已通知' if d['notified'] else '未通知'
        }
        for d in all_data[start_index:end_index]
    ]

    return jsonify({
        'records': paginated_data,
        'total_records': total_records
    })

@hpc_bp.route('/api/hpc-usage/prepaid', methods=['POST'])
def update_prepaid_amount():
    data = request.get_json()
    username = data.get('username')
    amount = data.get('amount')

    if not username or amount is None:
        return jsonify({'success': False, 'message': '缺少使用者名稱或金額。'}), 400
    
    try:
        amount = float(amount)
        if amount < 0:
            raise ValueError("金額不能為負數")
    except ValueError:
        return jsonify({'success': False, 'message': '金額必須是有效的非負數字。'}), 400

    update_prepaid_amount_db(username, amount)

    return jsonify({'success': True, 'message': f"使用者 {username} 的預繳金額已更新。"})


NOTIFICATION_TYPE_PREPAID = 0  # 對應 database/hpc_model.py NotificationHistory 註解：0 為 'prepaid'

def _send_prepaid_shortage_notifications(target_user=None, notify_all=False):
    """
    核心邏輯：找出年度用量超過預繳額度、且今年尚未通知過的帳號，寄送 HTML 通知信。
    傳入 target_user 只通知單一帳號；notify_all=True 則通知所有符合條件的帳號。
    回傳 (success, message, status_code) 供路由組裝 JSON response。
    """
    all_data = get_usage_and_prepaid_data_db()
    users_to_notify = []

    if target_user:
        user_data = next((u for u in all_data if u['username'] == target_user), None)
        if not user_data:
            return False, '找不到該使用者，或該帳號本年度用量未超過顯示門檻。', 404
        if user_data['yearly_usage'] > user_data['prepaid_amount'] and not user_data['notified']:
            users_to_notify.append(user_data)
    elif notify_all:
        users_to_notify = [
            u for u in all_data if u['yearly_usage'] > u['prepaid_amount'] and not u['notified']
        ]
    else:
        return False, '未指定通知目標。', 400

    if not users_to_notify:
        return True, '沒有需要通知的使用者。', 200

    recipients_map = {u['username']: "chh0410@ntu.edu.tw" for u in users_to_notify}

    successful_notifications = 0
    for user_data in users_to_notify:
        username = user_data['username']
        recipient_email = recipients_map.get(username)
        if not recipient_email:
            print(f"找不到使用者 {username} 的 email，跳過發送。")
            continue

        subject = "HPC 預繳金額使用提醒"
        body = render_template(
            'email/prepaid_notification.html',
            username=username,
            yearly_usage=user_data['yearly_usage'],
            prepaid_amount=user_data['prepaid_amount']
        )

        if send_hpc_notification_email([recipient_email], subject, body):
            message = f"預繳金額不足通知 (年度用量: ${user_data['yearly_usage']}, 預繳: ${user_data['prepaid_amount']})"
            save_notification_to_db(username, NOTIFICATION_TYPE_PREPAID, message, user_data['yearly_usage'])
            successful_notifications += 1

            # email log
            notification_record = {
                "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "message": message,
                "usage": user_data['yearly_usage'],
                "users": [username],
                "recipients": [recipient_email]
            }
            save_hpc_notification_log(notification_record)

    return True, f"成功發送 {successful_notifications} 封通知郵件。", 200


@hpc_bp.route('/api/hpc-usage/notify-single', methods=['POST'])
def notify_single_user():
    data = request.get_json() or {}
    username = data.get('username')

    if not username:
        return jsonify({'success': False, 'message': '未指定通知目標。'}), 400

    success, message, status_code = _send_prepaid_shortage_notifications(target_user=username)
    return jsonify({'success': success, 'message': message}), status_code


@hpc_bp.route('/api/hpc-usage/notify-all', methods=['POST'])
def notify_all_users():
    success, message, status_code = _send_prepaid_shortage_notifications(notify_all=True)
    return jsonify({'success': success, 'message': message}), status_code


@hpc_bp.route('/api/hpc-usage/notify-prepaid', methods=['POST'])
def notify_prepaid_users():
    data = request.get_json() or {}
    target_user = data.get('username')
    notify_all = data.get('notify_all', False)

    if target_user:
        success, message, status_code = _send_prepaid_shortage_notifications(target_user=target_user)
    elif notify_all:
        success, message, status_code = _send_prepaid_shortage_notifications(notify_all=True)
    else:
        success, message, status_code = False, '未指定通知目標。', 400

    return jsonify({'success': success, 'message': message}), status_code

@hpc_bp.route('/api/hpc-usage/serverlist', methods=['GET'])
def get_server_list():
    # 使用 .distinct() 確保名稱重複的伺服器只會出現一次
    # 同時過濾 status 為 true 的機器
    servers = db.session.query(Serverlist.server).filter_by(status=True).distinct().all()
    return jsonify([{"server": s[0]} for s in servers])

@hpc_bp.route('/api/hpc-usage/search_users')
def search_users():
    query_str = request.args.get('q', '')
    if not query_str:
        return jsonify([])

    # 搜尋 username 或 name 包含關鍵字的使用者
    # 使用 ilike 進行不分大小寫搜尋
    users = UserAccounting.query.filter(
        (UserAccounting.username.ilike(f'%{query_str}%'))
    ).limit(10).all()

    return jsonify([{
        "id": u.id,
        "username": u.username
    } for u in users])