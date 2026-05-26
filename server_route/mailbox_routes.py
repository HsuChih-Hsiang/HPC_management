from flask import Blueprint, request, jsonify
from database.extensions import db
from database.hpc_model import MailboxGroup, MailboxEmail
from sqlalchemy.exc import IntegrityError
from utils.email_utils import load_mailboxes
from utils import params

mailbox_bp = Blueprint('mailbox', __name__)

# 模擬獲取當前使用者，未來可從 session 獲取
def get_current_user():
    return "admin"

# --- API 路由：信箱相關 ---
@mailbox_bp.route('/api/mailboxes', methods=['GET'])
def get_mailboxes():
    username = get_current_user()
    # 呼叫我們先前改寫的 load_mailboxes，它會回傳 JSON 相容格式
    mailboxes = load_mailboxes(username)
    return jsonify(mailboxes)

@mailbox_bp.route('/api/mailboxes', methods=['POST'])
def add_group():
    username = get_current_user()
    data = request.get_json()
    group_name = data.get('name', '').strip()

    if not group_name:
        return jsonify({'success': False, 'message': '群組名稱不能為空。'}), 400

    try:
        new_group = MailboxGroup(name=group_name, owner_username=username)
        db.session.add(new_group)
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': '群組已成功新增。', 
            'group': {'id': new_group.id, 'name': new_group.name, 'emails': []}
        })
    except IntegrityError:
        db.session.rollback()
        return jsonify({'success': False, 'message': '該群組名稱已存在。'}), 409

@mailbox_bp.route('/api/mailboxes/<int:group_id>', methods=['DELETE'])
def delete_group(group_id):
    username = get_current_user()

    group = MailboxGroup.query.filter_by(id=group_id, owner_username=username).first()

    if not group:
        return jsonify({'success': False, 'message': '群組未找到。'}), 404
    
    # 假設 params.UNASSIGNED_GROUP_ID 是固定保留的
    if group.name == params.UNASSIGNED_GROUP_NAME:
        return jsonify({'success': False, 'message': '無法刪除待分組信箱。'}), 403
    
    
    # 獲取待分組群組，以便移動信箱
    unassigned = MailboxGroup.query.filter_by(
        name=params.UNASSIGNED_GROUP_NAME, 
        owner_username=username
    ).first()

    if unassigned:
        # 將要刪除群組內的信箱移至待分組
        for email_obj in group.emails:
            # 檢查待分組是否已存在該信箱，避免重複
            exists = MailboxEmail.query.filter_by(
                email_address=email_obj.email_address, 
                group_id=unassigned.id
            ).first()
            if not exists:
                email_obj.group_id = unassigned.id
            else:
                db.session.delete(email_obj) # 重複則刪除

    db.session.delete(group)
    db.session.commit()
    return jsonify({'success': True, 'message': '群組已成功刪除並移動信箱。'})

@mailbox_bp.route('/api/mailboxes/<int:group_id>/add_email', methods=['POST'])
def add_email_to_group(group_id):
    username = get_current_user()
    data = request.get_json()
    email_addr = data.get('email', '').strip()

    if not email_addr:
        return jsonify({'success': False, 'message': '信箱不能為空。'}), 400

    # 檢查群組是否存在且屬於該使用者
    group = MailboxGroup.query.filter_by(id=group_id, owner_username=username).first()
    if not group:
        return jsonify({'success': False, 'message': '群組未找到。'}), 404
    
    # 只檢查目前的 group_id 內是否已存在此信箱
    exists = MailboxEmail.query.filter_by(
        group_id=group_id, 
        email_address=email_addr
    ).first()
    if exists:
        return jsonify({'success': False, 'message': f'信箱 {email_addr} 已存在於本群組中。'}), 409

    new_email = MailboxEmail(email_address=email_addr, group_id=group_id)
    db.session.add(new_email)
    db.session.commit()
    
    return jsonify({'success': True, 'message': '信箱已成功新增。', 'mailboxes': load_mailboxes(username)})

@mailbox_bp.route('/api/mailboxes/<int:group_id>/delete_email', methods=['DELETE'])
def delete_email_from_group(group_id):
    username = get_current_user()
    data = request.get_json()
    email_addr = data.get('email', '').strip()

    email_obj = MailboxEmail.query.join(MailboxGroup).filter(
        MailboxGroup.id == group_id,
        MailboxGroup.owner_username == username,
        MailboxEmail.email_address == email_addr
    ).first()

    if not email_obj:
        return jsonify({'success': False, 'message': '在該分組中未找到此信箱。'}), 404

    db.session.delete(email_obj)
    db.session.commit()
    return jsonify({'success': True, 'message': '信箱已刪除。', 'mailboxes': load_mailboxes(username)})

@mailbox_bp.route('/api/mailboxes/move_email', methods=['POST'])
def move_email():
    username = get_current_user()
    data = request.get_json()
    email_addr = data.get('email', '').strip()
    source_id = data.get('source_group_id')
    target_id = data.get('target_group_id')

    if not email_addr or source_id is None or target_id is None:
        return jsonify({'success': False, 'message': '缺少移動信箱所需參數。'}), 400

    # 找出源信箱物件
    email_obj = MailboxEmail.query.join(MailboxGroup).filter(
        MailboxGroup.id == source_id,
        MailboxGroup.owner_username == username,
        MailboxEmail.email_address == email_addr
    ).first()

    # 確保目標群組存在
    target_group = MailboxGroup.query.filter_by(id=target_id, owner_username=username).first()

    if not email_obj or not target_group:
        return jsonify({'success': False, 'message': '找不到信箱或目標群組。'}), 404

    # 檢查目標群組是否已有此信箱
    duplicate = MailboxEmail.query.filter_by(group_id=target_id, email_address=email_addr).first()
    if duplicate:
        db.session.delete(email_obj) # 如果目標已存在，則刪除來源即可
    else:
        email_obj.group_id = target_id
    
    db.session.commit()
    return jsonify({'success': True, 'message': '信箱已成功移動。', 'mailboxes': load_mailboxes(username)})