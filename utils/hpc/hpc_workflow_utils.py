"""
繳費單開立流程的狀態機。

「本期費用核對與帳務管理」那四顆按鈕有嚴格的先後順序：

    1. 寄送確認信
         ↓（寄過才解鎖）
    2. 額度扣款後開立繳費單  ／  開立繳費單     ← 兩者只能擇一，做過一個另一個就鎖住
         ↓（開過單才解鎖）
    3. 寄送繳費單            ← 有未繳款的預繳紀錄時，可改開「預繳帳單」

進度必須落地在 billing_workflows 表，否則使用者重新整理網頁後前端就忘了
走到哪一步，等於沒有限制。前端會依這裡回傳的旗標決定按鈕的啟用狀態，
後端每一支 API 也會再檢查一次 —— 前端的 disabled 只是提示，
真正把關的是後端，避免有人直接打 API 跳過步驟。
"""

from datetime import datetime

from database.extensions import db
from database.hpc_model import BillingWorkflow, Bill

# 開單流程的動作代碼
ACTION_DEDUCT = 'deduct'   # 額度扣款後開立繳費單
ACTION_DIRECT = 'direct'   # 直接開立繳費單

ACTION_LABELS = {
    ACTION_DEDUCT: '額度扣款後開立繳費單',
    ACTION_DIRECT: '開立繳費單'
}

# 寄送繳費單的種類
KIND_NORMAL = 'normal'
KIND_PREPAID = 'prepaid'


def get_billing_year():
    """
    帳務年度 = 去年。

    calculate_pending_bill / confirm_deduct / create_bill 的防呆比對、
    確認信的用量統計都是用「去年度」，流程狀態也必須跟著同一個年份走，
    否則跨年時會出現「確認信記在 2025、開單卻檢查 2026」的錯位。
    """
    return datetime.now().year - 1


def get_workflow(contact_id, year=None):
    """取得該聯絡人該年度的流程紀錄；沒有就回傳 None（不建立）。"""
    year = year if year is not None else get_billing_year()
    return BillingWorkflow.query.filter_by(contact_id=contact_id, year=year).first()


def get_or_create_workflow(contact_id, year=None):
    """取得流程紀錄，沒有就建立一筆（不 commit，交給呼叫端一起提交）。"""
    year = year if year is not None else get_billing_year()
    workflow = get_workflow(contact_id, year)
    if workflow is None:
        workflow = BillingWorkflow(contact_id=contact_id, year=year)
        db.session.add(workflow)
    return workflow


def _has_existing_bill(contact_id, year):
    """
    舊資料相容：billing_workflows 這張表是後來才加的。

    在它之前就已經開過單的聯絡人不會有流程紀錄，若只看流程表會誤判成
    「還沒開過單」而讓人重複開單。因此再回頭確認 Bill 表裡有沒有該年度的帳單，
    比對方式與 confirm_deduct / create_bill 既有的防呆一致（備註含年份）。
    """
    return Bill.query.filter(
        Bill.contact_id == contact_id,
        Bill.status.in_(['unpaid', 'paid']),
        Bill.notes.like(f'%{year}%')
    ).first()


def build_workflow_state(contact, has_unpaid_prepaid=False):
    """
    組出前端要用的流程狀態與按鈕啟用旗標。

    Args:
        contact: Contact 物件
        has_unpaid_prepaid: 該帳號是否有尚未繳款的預繳紀錄
                            （決定「開立預繳帳單」能不能選）
    """
    year = get_billing_year()
    workflow = get_workflow(contact.id, year)

    confirm_email_sent = bool(workflow and workflow.confirm_email_sent_at)
    bill_action = workflow.bill_action if workflow else None
    quotation_sent = bool(workflow and workflow.quotation_sent_at)

    legacy_bill = None
    if not bill_action:
        legacy_bill = _has_existing_bill(contact.id, year)

    bill_issued = bool(bill_action) or legacy_bill is not None

    state = workflow.to_dict() if workflow else {
        'contact_id': contact.id,
        'year': year,
        'confirm_email_sent': False,
        'confirm_email_sent_at': None,
        'bill_action': None,
        'bill_id': None,
        'bill_created_at': None,
        'quotation_sent': False,
        'quotation_sent_at': None,
        'quotation_kind': None
    }

    state.update({
        'bill_issued': bill_issued,
        # 這一年度在流程表之前就已經開過單（沒有記錄是用哪個動作開的）
        'legacy_bill_id': legacy_bill.id if legacy_bill else None,
        'has_unpaid_prepaid': bool(has_unpaid_prepaid),

        # --- 按鈕啟用旗標 ---
        # 確認信可以重寄（例如上一次寄錯人），所以不因為寄過就鎖住
        'can_send_confirm_email': True,
        'can_deduct': confirm_email_sent and not bill_issued,
        'can_direct_bill': confirm_email_sent and not bill_issued,
        # 預繳帳單不受開單流程限制（見 ensure_can_send_quotation），
        # 所以只要有未繳款的預繳紀錄，「寄送繳費單」就該是可按的
        'can_send_quotation': bill_issued or bool(has_unpaid_prepaid),
        'can_send_normal_quotation': bill_issued,
        'can_send_prepaid_quotation': bool(has_unpaid_prepaid),

        # --- 給前端顯示成 title/提示用的原因 ---
        'deduct_blocked_reason': _blocked_reason(confirm_email_sent, bill_issued, bill_action, legacy_bill),
        'direct_blocked_reason': _blocked_reason(confirm_email_sent, bill_issued, bill_action, legacy_bill),
        'quotation_blocked_reason': (
            None if (bill_issued or has_unpaid_prepaid)
            else '請先完成「額度扣款後,開立繳費單」或「開立繳費單」（若有未繳款的預繳紀錄則可直接開立預繳帳單）。'
        )
    })
    return state


def _blocked_reason(confirm_email_sent, bill_issued, bill_action, legacy_bill):
    """回傳按鈕被鎖住的原因文字；沒被鎖住則回傳 None。"""
    if not confirm_email_sent:
        return '請先完成「寄送確認信」。'
    if bill_action:
        return f'本年度已執行過「{ACTION_LABELS.get(bill_action, bill_action)}」，兩者只能擇一。'
    if legacy_bill is not None:
        return f'本年度已存在帳單紀錄 (帳單 ID: {legacy_bill.id})，無法重複開單。'
    if bill_issued:
        return '本年度已開立過繳費單。'
    return None


def ensure_can_issue_bill(contact, action):
    """
    檢查現在能不能執行開單動作（deduct / direct）。
    可以則回傳 None，不行則回傳給前端看的錯誤訊息。
    """
    year = get_billing_year()
    workflow = get_workflow(contact.id, year)

    if not (workflow and workflow.confirm_email_sent_at):
        return f'流程順序錯誤：請先完成「寄送確認信」，才能執行「{ACTION_LABELS.get(action, action)}」。'

    if workflow.bill_action:
        if workflow.bill_action == action:
            return f'本年度已執行過「{ACTION_LABELS.get(action, action)}」，無法重複執行。'
        return (f'本年度已執行過「{ACTION_LABELS.get(workflow.bill_action, workflow.bill_action)}」，'
                f'與「{ACTION_LABELS.get(action, action)}」只能擇一。')

    return None


def ensure_can_send_quotation(contact, kind, has_unpaid_prepaid):
    """
    檢查現在能不能寄送繳費單。可以則回傳 None，不行則回傳錯誤訊息。
    """
    if kind not in (KIND_NORMAL, KIND_PREPAID):
        return f'未知的繳費單種類：{kind}'

    # 預繳帳單不受「寄確認信 → 開單」的流程限制：
    # 它收的是客戶已經談定要預繳、但尚未繳款的那筆錢，與「用了多少、
    # 該收多少」的年度結算是兩回事，本來就可以獨立開立與寄送。
    # 唯一的前提是真的有尚未繳款的預繳紀錄，否則等於憑空生出一筆應收款。
    if kind == KIND_PREPAID:
        if not has_unpaid_prepaid:
            return '該帳號沒有尚未繳款的預繳紀錄，無法開立預繳帳單。'
        return None

    year = get_billing_year()
    workflow = get_workflow(contact.id, year)

    bill_issued = bool(workflow and workflow.bill_action) or _has_existing_bill(contact.id, year) is not None
    if not bill_issued:
        return '流程順序錯誤：請先完成「額度扣款後,開立繳費單」或「開立繳費單」，才能寄送繳費單。'

    return None


def mark_confirm_email_sent(contact_id):
    """記錄「寄送確認信」完成（不 commit）。"""
    workflow = get_or_create_workflow(contact_id)
    workflow.confirm_email_sent_at = datetime.now()
    return workflow


def mark_bill_issued(contact_id, action, bill_id=None):
    """記錄開單動作完成（不 commit）。"""
    workflow = get_or_create_workflow(contact_id)
    workflow.bill_action = action
    workflow.bill_id = bill_id
    workflow.bill_created_at = datetime.now()
    return workflow


def mark_quotation_sent(contact_id, kind):
    """記錄「寄送繳費單」完成（不 commit）。"""
    workflow = get_or_create_workflow(contact_id)
    workflow.quotation_sent_at = datetime.now()
    workflow.quotation_kind = kind
    return workflow
