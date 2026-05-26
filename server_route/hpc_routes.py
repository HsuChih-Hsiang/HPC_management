from flask import Blueprint, request, jsonify, render_template
from datetime import datetime
from utils.hpc.hpc_setting_utils import load_hpc_settings, save_hpc_settings
from utils.hpc.hpc_notify_utils import (
    get_hpc_notifications_by_date, send_hpc_notification_email, 
    save_notification_to_db, save_hpc_notification_log
)
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
def hpc_settings():
    if request.method == 'GET':
        current_settings = load_hpc_settings()
        return jsonify(current_settings)

    elif request.method == 'POST':
        data = request.get_json()
        price_threshold = data.get('price_threshold')
        check_interval = data.get('check_interval')
        diff_price_threshold = data.get('diff_price_threshold')
        check_period = data.get('check_period')
        notification_cooldown_days = data.get('notification_cooldown_days')

        if not all([price_threshold is not None, check_interval is not None, check_period is not None, notification_cooldown_days is not None]): # 修改這行
            return jsonify({'success': False, 'message': '缺少必要的設定參數。'}), 400
        
        try:
            price_threshold = int(price_threshold)
            check_interval = int(check_interval)
            diff_price_threshold = int(diff_price_threshold)
            check_period = int(check_period)
            notification_cooldown_days = int(notification_cooldown_days)
            
            if not (price_threshold >= 0 and check_interval > 0 and check_period > 0 and diff_price_threshold >= 0 and notification_cooldown_days >= 0): # 修改這行
                print('1')
                return jsonify({'success': False, 'message': '設定參數數值無效，請檢查範圍。'}), 400

        except ValueError:
            print('2')
            return jsonify({'success': False, 'message': '設定參數格式不正確，請輸入數字。'}), 400

        new_settings = {
            'price_threshold': price_threshold,
            'check_interval': check_interval,
            'diff_price_threshold': diff_price_threshold,
            'check_period': check_period,
            'notification_cooldown_days': notification_cooldown_days
        }
        save_hpc_settings(new_settings)
        
        return jsonify({'success': True, 'message': '設定已成功儲存。'})
    
@hpc_bp.route('/api/hpc-usage/prepaid', methods=['GET'])
def get_prepaid_data():
    filter_exceeded = request.args.get('filter_exceeded', 'false').lower() == 'true'
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 10, type=int)

    all_data = get_usage_and_prepaid_data_db()

    if filter_exceeded:
        all_data = [d for d in all_data if d['yearly_usage'] > d['prepaid_amount']]

    all_data.sort(key=lambda x: x['username'])

    total_records = len(all_data)
    start_index = (page - 1) * limit
    end_index = start_index + limit
    paginated_data = all_data[start_index:end_index]

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


@hpc_bp.route('/api/hpc-usage/notify-prepaid', methods=['POST'])
def notify_prepaid_users():
    data = request.get_json()
    target_user = data.get('username')
    notify_all = data.get('notify_all', False)

    all_data = get_usage_and_prepaid_data_db()
    users_to_notify = []

    if target_user:
        user_data = next((u for u in all_data if u['username'] == target_user), None)
        if not user_data:
             return jsonify({'success': False, 'message': '找不到該使用者。'}), 404
        if user_data['yearly_usage'] > user_data['prepaid_amount'] and not user_data['notified']:
            users_to_notify.append(user_data)
    elif notify_all:
        users_to_notify = [
            u for u in all_data if u['yearly_usage'] > u['prepaid_amount'] and not u['notified']
        ]
    else:
        return jsonify({'success': False, 'message': '未指定通知目標。'}), 400

    if not users_to_notify:
        return jsonify({'success': True, 'message': '沒有需要通知的使用者。'})
    
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
            'prepaid_notification_template.html',
            username=username,
            yearly_usage=user_data['yearly_usage'],
            prepaid_amount=user_data['prepaid_amount']
        )
        
        if send_hpc_notification_email([recipient_email], subject, body):
            save_notification_to_db(username, 'prepaid')
            successful_notifications += 1
            
            # email log
            notification_record = {
                "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "message": f"預繳金額不足通知 (年度用量: ${user_data['yearly_usage']}, 預繳: ${user_data['prepaid_amount']})",
                "usage": user_data['yearly_usage'],
                "users": [username],
                "recipients": [recipient_email]
            }
            save_hpc_notification_log(notification_record)

    return jsonify({'success': True, 'message': f"成功發送 {successful_notifications} 封通知郵件。"})

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