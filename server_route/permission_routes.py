from flask import Blueprint, request, jsonify, session
from database.extensions import db
from database.hpc_model import AdUser, PermissionGroup, GroupPermission
from utils.permission_utils import (
    FEATURES, ALL_FEATURE_KEYS, ADMIN_GROUP_NAME,
    get_user_features
)

permission_bp = Blueprint('permission', __name__)


@permission_bp.route('/api/permission/my-permissions', methods=['GET'])
def get_my_permissions():
    """
    供等候頁面輪詢用：回傳目前登入者是否已被開通。
    這支刻意不需要任何功能權限（列在 PUBLIC_ENDPOINTS），
    否則尚未開通的使用者連自己的狀態都查不到。
    """
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'authenticated': False}), 401

    features = get_user_features(user_id)
    return jsonify({
        'authenticated': True,
        'approved': bool(features),
        'features': sorted(features)
    })


@permission_bp.route('/api/permission/features', methods=['GET'])
def list_features():
    """回傳系統中所有可授權的功能清單，供權限設定畫面渲染勾選項目。"""
    return jsonify({'features': FEATURES})


@permission_bp.route('/api/permission/groups', methods=['GET'])
def list_groups():
    groups = PermissionGroup.query.order_by(
        PermissionGroup.is_system.desc(), PermissionGroup.name.asc()
    ).all()
    return jsonify({'groups': [g.to_dict() for g in groups]})


@permission_bp.route('/api/permission/groups', methods=['POST'])
def create_group():
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    description = (data.get('description') or '').strip()
    features = data.get('features') or []

    if not name:
        return jsonify({'success': False, 'message': '請輸入群組名稱。'}), 400

    if PermissionGroup.query.filter_by(name=name).first():
        return jsonify({'success': False, 'message': f'群組「{name}」已存在。'}), 400

    invalid = [f for f in features if f not in ALL_FEATURE_KEYS]
    if invalid:
        return jsonify({'success': False, 'message': f'包含無效的功能代碼: {", ".join(invalid)}'}), 400

    group = PermissionGroup(name=name, description=description, is_system=False)
    db.session.add(group)
    db.session.flush()

    _replace_group_features(group.id, features)

    db.session.commit()
    return jsonify({'success': True, 'message': f'群組「{name}」已建立。', 'group': group.to_dict()})


@permission_bp.route('/api/permission/groups/<int:group_id>', methods=['PUT'])
def update_group(group_id):
    group = db.session.get(PermissionGroup, group_id)
    if not group:
        return jsonify({'success': False, 'message': '找不到該群組。'}), 404

    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    description = (data.get('description') or '').strip()
    features = data.get('features')

    # admin 是系統群組：名稱與權限都不開放調整，避免管理員把自己鎖在門外
    if group.is_system:
        if features is not None and set(features) != set(ALL_FEATURE_KEYS):
            return jsonify({
                'success': False,
                'message': f'「{group.name}」為系統群組，必須保留全部權限，無法調整。'
            }), 400
        if name and name != group.name:
            return jsonify({'success': False, 'message': '系統群組名稱不可修改。'}), 400
    else:
        if not name:
            return jsonify({'success': False, 'message': '請輸入群組名稱。'}), 400
        exists = PermissionGroup.query.filter(
            PermissionGroup.name == name, PermissionGroup.id != group_id
        ).first()
        if exists:
            return jsonify({'success': False, 'message': f'群組「{name}」已存在。'}), 400
        group.name = name

    group.description = description

    if features is not None:
        invalid = [f for f in features if f not in ALL_FEATURE_KEYS]
        if invalid:
            return jsonify({'success': False, 'message': f'包含無效的功能代碼: {", ".join(invalid)}'}), 400

        # 系統群組的功能「內容」不可增減，但仍允許調整顯示順序，
        # 因此這裡對 admin 也會重建紀錄（上面已驗證過集合必須完全相同）。
        _replace_group_features(group.id, features)

    db.session.commit()
    return jsonify({'success': True, 'message': '群組設定已更新。', 'group': group.to_dict()})


@permission_bp.route('/api/permission/groups/<int:group_id>', methods=['DELETE'])
def delete_group(group_id):
    group = db.session.get(PermissionGroup, group_id)
    if not group:
        return jsonify({'success': False, 'message': '找不到該群組。'}), 404

    if group.is_system:
        return jsonify({'success': False, 'message': f'「{group.name}」為系統群組，不可刪除。'}), 400

    if group.users:
        return jsonify({
            'success': False,
            'message': f'仍有 {len(group.users)} 個帳號屬於此群組，請先將他們改分配到其他群組。'
        }), 400

    db.session.delete(group)
    db.session.commit()
    return jsonify({'success': True, 'message': f'群組「{group.name}」已刪除。'})


@permission_bp.route('/api/permission/users', methods=['GET'])
def list_users():
    """
    回傳所有帳號，並拆出「尚未指派群組」的清單，
    讓管理員一眼看到有誰在等待開通。
    """
    users = AdUser.query.order_by(AdUser.created_at.asc()).all()
    all_users = [u.to_dict() for u in users]
    return jsonify({
        'users': all_users,
        'pending_users': [u for u in all_users if u['group_id'] is None]
    })


@permission_bp.route('/api/permission/users/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    """
    刪除一筆「申請」：把尚未開通的帳號從系統中移除。

    只允許刪除 group_id 為 NULL 的帳號，理由有二：
      1. 已開通的帳號可能還在使用系統，要移除請先在畫面上改回「未開通」，
         多一道手續可避免誤刪。
      2. 收回權限的那條路徑已經有「最後一個 admin」的防鎖死檢查，
         這裡限定未開通帳號就不會有繞過的問題。

    刪掉的是登入紀錄本身，對方若再次用 Google 登入會重新產生一筆新的申請，
    因此這個動作等同「駁回這次申請」，不是永久封鎖。
    """
    user = db.session.get(AdUser, user_id)
    if not user:
        return jsonify({'success': False, 'message': '找不到該帳號。'}), 404

    if user.id == session.get('user_id'):
        return jsonify({'success': False, 'message': '不可刪除自己的帳號。'}), 400

    if user.group_id is not None:
        return jsonify({
            'success': False,
            'message': '此帳號已開通，請先將它的群組改為「未開通」再刪除。'
        }), 400

    email = user.email
    db.session.delete(user)
    db.session.commit()
    return jsonify({'success': True, 'message': f'已刪除 {email} 的申請。'})


@permission_bp.route('/api/permission/users/<int:user_id>/group', methods=['PUT'])
def assign_user_group(user_id):
    user = db.session.get(AdUser, user_id)
    if not user:
        return jsonify({'success': False, 'message': '找不到該帳號。'}), 404

    data = request.get_json() or {}
    group_id = data.get('group_id')

    # group_id 傳 null 代表收回權限（改回等待開通狀態）
    if group_id is None:
        if _is_last_admin(user):
            return jsonify({
                'success': False,
                'message': '這是最後一個 admin 帳號，不可收回權限，否則將無人能管理系統。'
            }), 400
        user.group_id = None
        db.session.commit()
        return jsonify({'success': True, 'message': f'已收回 {user.email} 的權限。', 'user': user.to_dict()})

    group = db.session.get(PermissionGroup, group_id)
    if not group:
        return jsonify({'success': False, 'message': '找不到該群組。'}), 404

    if _is_last_admin(user) and not group.is_system:
        return jsonify({
            'success': False,
            'message': '這是最後一個 admin 帳號，不可移出 admin 群組，否則將無人能管理系統。'
        }), 400

    user.group_id = group.id
    db.session.commit()
    return jsonify({
        'success': True,
        'message': f'已將 {user.email} 指派至「{group.name}」。',
        'user': user.to_dict()
    })


def _replace_group_features(group_id, features):
    """
    以傳入的順序重建該群組的功能清單。
    features 是「有序」的陣列，其索引即 sort_order，
    決定該群組成員側邊欄的排列順序，因此不可用 set 去重（會打亂順序）。
    """
    GroupPermission.query.filter_by(group_id=group_id).delete(synchronize_session=False)

    seen = set()
    order = 0
    for key in features:
        if key in seen:
            continue
        seen.add(key)
        db.session.add(GroupPermission(
            group_id=group_id, feature_key=key, sort_order=order
        ))
        order += 1


def _is_last_admin(user):
    """判斷此使用者是否為系統中僅存的 admin，用於阻擋會造成鎖死的操作。"""
    admin_group = PermissionGroup.query.filter_by(name=ADMIN_GROUP_NAME).first()
    if not admin_group or user.group_id != admin_group.id:
        return False
    return AdUser.query.filter_by(group_id=admin_group.id).count() <= 1
