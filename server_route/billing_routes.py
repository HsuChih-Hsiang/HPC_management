"""
HPC 帳務審核

用途：管理員在「HPC 帳號管理」頁面新增預付額度或開立繳費單之後，
      實際的匯款／繳費是後來才發生的。這一頁就是把「錢真的收到了」
      這件事回寫進資料庫的狀態欄位。

兩種待審核的單據，各自對應資料表既有的狀態欄位（不需要新增欄位）：

  1. 預付額度 PrepaidAmount → is_paid
     ⚠️ 重要：一筆預付額度在資料庫中是「兩筆」紀錄，靠 source_id 配對：
        - is_history = False：活躍額度，之後扣款會直接扣減它的 amount / discount
        - is_history = True ：歷史存檔，金額永遠保留當初的原始值
     因此審核狀態一定要「兩筆一起改」，否則歷史紀錄與活躍額度會不一致，
     contact_manager 頁面的「儲值歷史紀錄」就會顯示錯誤的繳費狀態。

  2. 繳費單 Bill → status ('unpaid' / 'paid' / 'cancelled')
     繳費單只有單筆，沒有歷史副本。

另外，只有 is_paid = True 且 is_history = False 的預付額度才會被
hpc_quota_routes.execute_quota_deduction 納入可扣抵的額度，
所以這一頁按下「確認已繳費」等同於讓該筆額度正式生效。
"""

from datetime import datetime, date
from flask import Blueprint, request, jsonify
from sqlalchemy import func

from database.extensions import db
from database.hpc_model import (
    PrepaidAmount, Bill, QuotaTransaction, Contact, ContactAccountMapping
)
# 研究獎勵／免費折抵額度的判斷一律共用同一支函式（前綴常數定義在 hpc_bill_utils），
# 避免各處各自寫死字串而在新增額度類型時比對不到。
# 這類額度是系統直接發放的，建立時 is_paid 就已經是 True，不需要（也不應該）走繳費審核。
from utils.hpc.hpc_bill_utils import is_research_bonus

billing_bp = Blueprint('billing', __name__)


# =========================================================================
# 共用工具
# =========================================================================
def _build_account_contact_map():
    """
    正式帳號 (username) → Contact 的對照表。

    預付額度與帳單分別是用 username / contact_id 記錄的，
    審核畫面要顯示「這是哪個團隊的錢」，因此需要這層對照。
    """
    mapping = {}
    for m in ContactAccountMapping.query.all():
        username = m.user_accounting.username if m.user_accounting else m.manual_account
        if username and m.contact:
            mapping[username] = m.contact
    return mapping


def _contact_brief(contact):
    if not contact:
        return {'contact_id': None, 'team_name': '', 'applicant': '', 'dept_level1': ''}
    return {
        'contact_id': contact.id,
        'team_name': contact.team_name or '',
        'applicant': contact.applicant or '',
        'dept_level1': contact.dept_level1 or ''
    }


def _group_prepaids(rows):
    """
    把預付額度依 (username, source_id) 配對成「活躍 + 歷史」一組。
    回傳 dict: {(username, source_id): {'active': p 或 None, 'history': p 或 None}}
    """
    groups = {}
    for p in rows:
        key = (p.username, p.source_id)
        group = groups.setdefault(key, {'active': None, 'history': None})
        if p.is_history:
            group['history'] = p
        else:
            group['active'] = p
    return groups


def _deducted_prepaid_ids(prepaid_ids):
    """回傳這些預付額度中，已經被帳單扣抵過（有 QuotaTransaction）的 id 集合。"""
    if not prepaid_ids:
        return set()
    rows = db.session.query(QuotaTransaction.prepaid_id).filter(
        QuotaTransaction.prepaid_id.in_(list(prepaid_ids))
    ).distinct().all()
    return {r[0] for r in rows if r[0] is not None}


def _serialize_prepaid_group(username, source_id, group, deducted_ids):
    """
    序列化一組預付額度。

    金額有兩個來源，意義不同，兩個都要給前端：
      - 原始金額 (origin)  ：取歷史存檔那筆，永遠是當初開單的金額
      - 目前餘額 (active)  ：活躍那筆，會被後續扣款減少
    """
    active = group['active']
    history = group['history']
    origin = history or active
    if origin is None:
        return None

    # 前端操作一律以「活躍紀錄」的 id 當作 handle；
    # 萬一舊資料缺了活躍紀錄，就退而用歷史紀錄的 id，後端仍會依 source_id 兩筆一起改。
    handle = active or history

    is_bonus = is_research_bonus(source_id)
    ids = [p.id for p in (active, history) if p is not None]
    is_deducted = any(pid in deducted_ids for pid in ids)

    # 鎖定條件（前端據此停用「退回未繳費」按鈕並排除批次勾選）：
    #   1. 已被帳單扣抵過 —— 退回會讓已扣掉的額度憑空消失，帳務對不起來
    #   2. 學術／免費獎勵額度 —— 系統直接發放、本來就沒有收款這回事，
    #      建立時 is_paid 即為 True，不存在「退回未繳費」的情境
    # 兩者同時成立時顯示扣抵的訊息，因為那是比較嚴重的後果。
    if is_deducted:
        lock_reason = '此額度已被帳單扣抵過，不可退回未繳費狀態。'
    elif is_bonus:
        lock_reason = '系統直接發放的獎勵額度，不涉及收款，不可退回未繳費狀態。'
    else:
        lock_reason = ''

    return {
        'id': handle.id,
        'source_id': source_id,
        'username': username,
        'year': origin.year,
        'amount': round(float(origin.amount or 0), 2),
        'discount': round(float(origin.discount or 0), 2),
        'total': round(float(origin.amount or 0) + float(origin.discount or 0), 2),
        # 目前剩餘（已被帳單扣抵過就會小於原始金額）
        'remaining': round(
            float(active.amount or 0) + float(active.discount or 0), 2
        ) if active else None,
        'payment_date': origin.payment_date.strftime('%Y-%m-%d') if origin.payment_date else '',
        'is_paid': bool(origin.is_paid),
        'is_bonus': is_bonus,
        'kind_label': '學術／免費獎勵額度' if is_bonus else '預付儲值',
        # 資料完整性提示：正常情況一定是活躍 + 歷史成對出現
        'paired': active is not None and history is not None,
        'locked': bool(lock_reason),
        'lock_reason': lock_reason
    }


def _serialize_bill(bill, contact_map_by_id):
    contact = contact_map_by_id.get(bill.contact_id)
    amount = round(float(bill.amount or 0), 2)

    # 金額 0 的帳單是「額度全額抵扣成功」時系統補寫的紀錄單，不是真的要收錢，
    # 沒有審核的必要，也不該讓人把它改回未繳費。
    is_record_only = amount == 0

    data = {
        'id': bill.id,
        'amount': amount,
        'status': bill.status or 'unpaid',
        'created_at': bill.created_at.strftime('%Y-%m-%d') if bill.created_at else '',
        'notes': bill.notes or '',
        'formal_account': contact.get_formal_account() if contact else '',
        'is_record_only': is_record_only,
        'locked': is_record_only,
        'lock_reason': '此為額度全額抵扣後系統自動產生的紀錄單（金額 0 元），無需審核。' if is_record_only else ''
    }
    data.update(_contact_brief(contact))
    return data


# =========================================================================
# 1. 待審核／已審核清單
# =========================================================================
@billing_bp.route('/api/billing/review-items', methods=['GET'])
def list_review_items():
    """
    回傳預付額度與繳費單的審核清單。

    query string:
      status = pending (預設) | reviewed | all
    """
    status = (request.args.get('status') or 'pending').lower()
    if status not in ('pending', 'reviewed', 'all'):
        return jsonify({'success': False, 'message': 'status 參數只接受 pending / reviewed / all。'}), 400

    account_contact_map = _build_account_contact_map()
    contact_map_by_id = {c.id: c for c in Contact.query.all()}

    # ---- 預付額度 ----
    prepaid_query = PrepaidAmount.query
    if status == 'pending':
        prepaid_query = prepaid_query.filter(PrepaidAmount.is_paid == False)  # noqa: E712
    elif status == 'reviewed':
        prepaid_query = prepaid_query.filter(PrepaidAmount.is_paid == True)   # noqa: E712

    prepaid_rows = prepaid_query.order_by(
        PrepaidAmount.year.desc(), PrepaidAmount.id.desc()
    ).all()

    groups = _group_prepaids(prepaid_rows)
    deducted_ids = _deducted_prepaid_ids([p.id for p in prepaid_rows])

    prepaids = []
    for (username, source_id), group in groups.items():
        item = _serialize_prepaid_group(username, source_id, group, deducted_ids)
        if item:
            item.update(_contact_brief(account_contact_map.get(username)))
            prepaids.append(item)

    # 排序：先照年份／繳款日由新到舊，再把未繳費的整批提到最前面。
    # Python 的 sort 是穩定排序，所以第二次排序不會打亂第一次的結果。
    prepaids.sort(key=lambda x: (x['year'] or 0, x['payment_date']), reverse=True)
    prepaids.sort(key=lambda x: x['is_paid'])

    # ---- 繳費單 ----
    bill_query = Bill.query.filter(Bill.status != 'cancelled')
    if status == 'pending':
        bill_query = bill_query.filter(Bill.status == 'unpaid')
    elif status == 'reviewed':
        bill_query = bill_query.filter(Bill.status == 'paid')

    bills = [
        _serialize_bill(b, contact_map_by_id)
        for b in bill_query.order_by(Bill.created_at.desc(), Bill.id.desc()).all()
    ]

    return jsonify({
        'success': True,
        'prepaids': prepaids,
        'bills': bills,
        'summary': _build_summary()
    })


def _build_summary():
    """
    上方統計卡片：待審核的筆數與金額。

    一筆額度有活躍與歷史兩份紀錄，統計時只算「活躍」那一份才不會重複計算。
    未繳費的額度不會被扣款程序納入（扣款只看 is_paid=True），
    所以此時活躍紀錄的金額必然仍是原始金額。
    """
    pending_prepaid_count, pending_prepaid_amount = db.session.query(
        func.count(PrepaidAmount.id),
        func.coalesce(func.sum(PrepaidAmount.amount + PrepaidAmount.discount), 0)
    ).filter(
        PrepaidAmount.is_paid == False,    # noqa: E712
        PrepaidAmount.is_history == False  # noqa: E712
    ).first()

    pending_bill_count, pending_bill_amount = db.session.query(
        func.count(Bill.id),
        func.coalesce(func.sum(Bill.amount), 0)
    ).filter(
        Bill.status == 'unpaid',
        Bill.amount > 0
    ).first()

    return {
        'pending_prepaid_count': int(pending_prepaid_count or 0),
        'pending_prepaid_amount': round(float(pending_prepaid_amount or 0), 2),
        'pending_bill_count': int(pending_bill_count or 0),
        'pending_bill_amount': round(float(pending_bill_amount or 0), 2)
    }


# =========================================================================
# 2. 單筆審核
# =========================================================================
def _parse_payment_date(value):
    """把前端傳來的 YYYY-MM-DD 轉成 datetime；沒給或格式錯就用今天。"""
    try:
        return datetime.combine(datetime.strptime(value, '%Y-%m-%d').date(), datetime.min.time())
    except (ValueError, TypeError):
        return datetime.combine(date.today(), datetime.min.time())


def _review_prepaid(prepaid_id, is_paid, payment_date_str):
    """
    更新一組預付額度的繳費狀態。回傳 (成功, 訊息, 影響筆數)。
    ⚠️ 一定是依 username + source_id 把「活躍 + 歷史」兩筆一起更新。
    """
    target = db.session.get(PrepaidAmount, prepaid_id)
    if not target:
        return False, f'找不到預付額度紀錄 (id={prepaid_id})。', 0

    siblings = PrepaidAmount.query.filter_by(
        username=target.username, source_id=target.source_id
    ).all()

    if is_paid:
        payment_date = _parse_payment_date(payment_date_str)
        for p in siblings:
            p.is_paid = True
            p.payment_date = payment_date
        return True, '', len(siblings)

    # 退回未繳費：已被帳單扣抵過就不能退回，否則已扣掉的額度會憑空消失／重複計算
    deducted = _deducted_prepaid_ids([p.id for p in siblings])
    if deducted:
        return False, (f'{target.username} 的這筆額度已被帳單扣抵過，'
                       '不可退回未繳費狀態。如需調整請改用退款流程。'), 0

    # 學術／免費獎勵額度是系統直接發放的，沒有收款這件事，自然也沒有「退回未繳費」。
    # 前端已停用按鈕，這裡再擋一次，避免直接打 API 繞過。
    if is_research_bonus(target.source_id):
        return False, (f'{target.username} 的這筆額度為系統直接發放的學術／免費獎勵額度，'
                       '不涉及收款，不可退回未繳費狀態。'), 0

    for p in siblings:
        p.is_paid = False
    return True, '', len(siblings)


def _review_bill(bill_id, is_paid):
    """更新繳費單狀態。回傳 (成功, 訊息, 影響筆數)。"""
    bill = db.session.get(Bill, bill_id)
    if not bill:
        return False, f'找不到繳費單 (id={bill_id})。', 0

    if bill.status == 'cancelled':
        return False, f'繳費單 #{bill.id} 已作廢，不可變更繳費狀態。', 0

    if round(float(bill.amount or 0), 2) == 0:
        return False, (f'繳費單 #{bill.id} 金額為 0 元，'
                       '屬於額度全額抵扣後的系統紀錄單，不需要審核。'), 0

    bill.status = 'paid' if is_paid else 'unpaid'
    return True, '', 1


@billing_bp.route('/api/billing/prepaids/<int:prepaid_id>/review', methods=['PUT'])
def review_prepaid(prepaid_id):
    data = request.get_json() or {}
    is_paid = bool(data.get('is_paid'))

    ok, message, affected = _review_prepaid(prepaid_id, is_paid, data.get('payment_date'))
    if not ok:
        db.session.rollback()
        return jsonify({'success': False, 'message': message}), 400

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': '更新失敗', 'error': str(e)}), 500

    action = '已確認繳費' if is_paid else '已退回未繳費'
    return jsonify({
        'success': True,
        'message': f'預付額度{action}（同步更新活躍與歷史共 {affected} 筆紀錄）。'
    })


@billing_bp.route('/api/billing/bills/<int:bill_id>/review', methods=['PUT'])
def review_bill(bill_id):
    data = request.get_json() or {}
    is_paid = bool(data.get('is_paid'))

    ok, message, _ = _review_bill(bill_id, is_paid)
    if not ok:
        db.session.rollback()
        return jsonify({'success': False, 'message': message}), 400

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': '更新失敗', 'error': str(e)}), 500

    action = '已確認繳費' if is_paid else '已退回未繳費'
    return jsonify({'success': True, 'message': f'繳費單 #{bill_id} {action}。'})


# =========================================================================
# 3. 批次審核（勾選多筆後一次送出）
# =========================================================================
@billing_bp.route('/api/billing/review-batch', methods=['POST'])
def review_batch():
    """
    body: {
      "prepaid_ids": [1, 2],
      "bill_ids": [3],
      "is_paid": true,
      "payment_date": "2026-08-18"
    }
    只要其中任一筆失敗就整批回滾，避免只更新一半造成帳務不一致。
    """
    data = request.get_json() or {}
    prepaid_ids = data.get('prepaid_ids') or []
    bill_ids = data.get('bill_ids') or []
    is_paid = bool(data.get('is_paid'))
    payment_date_str = data.get('payment_date')

    if not prepaid_ids and not bill_ids:
        return jsonify({'success': False, 'message': '請先勾選要審核的項目。'}), 400

    errors = []
    prepaid_done = 0
    bill_done = 0

    for pid in prepaid_ids:
        ok, message, _ = _review_prepaid(pid, is_paid, payment_date_str)
        if ok:
            prepaid_done += 1
        else:
            errors.append(message)

    for bid in bill_ids:
        ok, message, _ = _review_bill(bid, is_paid)
        if ok:
            bill_done += 1
        else:
            errors.append(message)

    if errors:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': '批次審核已取消，沒有任何一筆被更新：\n' + '\n'.join(errors)
        }), 400

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': '批次更新失敗', 'error': str(e)}), 500

    action = '確認繳費' if is_paid else '退回未繳費'
    return jsonify({
        'success': True,
        'message': f'批次{action}完成：預付額度 {prepaid_done} 筆、繳費單 {bill_done} 筆。'
    })
