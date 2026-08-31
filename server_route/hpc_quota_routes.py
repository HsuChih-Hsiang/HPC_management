import base64
import uuid
from flask import request, jsonify, Blueprint, render_template_string
from utils.hpc.hpc_bill_utils import (calculate_prepaid_quota, get_account_last_year_usage_details,
                                      is_research_bonus, RESEARCH_BONUS_SOURCE_PREFIX,
                                      accounting_price_join)
from utils.hpc.hpc_setting_utils import load_hpc_settings_by_classification, load_bill_discount
from utils.hpc.hpc_quotation_utils import (build_quotation_context, render_quotation_html,
                                           render_bill_notification_html, quotation_html_to_pdf,
                                           build_quotation_filename, get_unpaid_prepaids)
from utils.hpc import hpc_workflow_utils as workflow_utils
from database.extensions import db
from database.hpc_model import Contact, PrepaidAmount, Accounting, Serverlist, Bill, QuotaTransaction
from sqlalchemy import func, cast, Numeric, and_
from datetime import datetime, date
from utils.email_utils import (send_hpc_notification_email, send_email_with_pdf,
                                get_confirm_email_template_html, get_confirm_email_default_cc,
                                render_usage_table_html)


quota_bp = Blueprint('quota', __name__)

@quota_bp.route('/api/contacts/<int:id>/quota', methods=['POST'])
def add_contact_quota(id):
    """管理員後台提交：新增特定年份的購買額度（同時寫入活躍與歷史兩筆紀錄）"""
    data = request.get_json() or {}
    amount = data.get('amount')
    purchase_date_str = data.get('purchase_date')
    
    if amount is None or amount <= 0:
        return jsonify({'message': '請輸入有效的新增額度'}), 400
        
    contact = Contact.query.get_or_404(id)
    formal_account = contact.get_formal_account()
    if not formal_account:
        return jsonify({'message': '該對象尚未對應正式帳號，無法新增額度'}), 400

    try:
        purchase_date = datetime.strptime(purchase_date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        purchase_date = date.today()
    
    purchase_year = purchase_date.year

    result_amout = calculate_prepaid_quota(amount)
    discount = abs(result_amout - amount)

    current_source_id = str(uuid.uuid4())

    try:
        # 🌟 1. 建立第一筆：活躍額度資料 (is_history = False)
        prepaid_active = PrepaidAmount(
            username=formal_account,
            amount=amount,
            discount=discount,
            year=purchase_year,
            payment_date=datetime.combine(purchase_date, datetime.min.time()),
            is_paid=False,
            is_history=False,
            source_id=current_source_id
        )
        
        # 🌟 2. 建立第二筆：歷史存檔資料 (is_history = True)，其餘欄位完全複製
        prepaid_history = PrepaidAmount(
            username=formal_account,
            amount=amount,
            discount=discount,
            year=purchase_year,
            payment_date=datetime.combine(purchase_date, datetime.min.time()),
            is_paid=False,
            is_history=True,
            source_id=current_source_id
        )
        
        # 將兩筆資料都加入 session
        db.session.add(prepaid_active)
        db.session.add(prepaid_history)
        
        # 統一提交
        db.session.commit()
        return jsonify({'message': '活躍與歷史雙軌額度新增成功'}), 200

    except Exception as e:
        db.session.rollback()
        print(e)
        return jsonify({'message': '資料庫儲存失敗', 'error': str(e)}), 500


# =========================================================================
# 3. 核心計費扣款邏輯 (Deduct Logic)
# =========================================================================

def execute_quota_deduction(contact_id, total_charge, bill_date_str, bill_id=None):
    """
    核心扣款邏輯（純運算與額度扣減，不進行 db.session.commit()）
    支援：年度研究更新 10,000 元「限當年帳單折抵」與「到期日優先排序」機制
    """
    contact = Contact.query.get(contact_id)
    if not contact:
        return False, total_charge, [], "找不到該聯絡人"

    formal_account = contact.get_formal_account()
    if not formal_account:
        return False, total_charge, [], "該聯絡人未對應正式帳號"

    remaining_bill = round(float(total_charge), 2)
    if remaining_bill <= 0:
        return True, 0.0, [], "扣款金額小於或等於 0，無需執行"

    # 撈出該帳號所有有餘額的活躍年度紀錄
    prepaids = PrepaidAmount.query.filter(
        PrepaidAmount.username == formal_account,
        PrepaidAmount.is_paid == True,  
        PrepaidAmount.is_history == False,  
        (PrepaidAmount.amount > 0) | (PrepaidAmount.discount > 0)
    ).order_by(PrepaidAmount.year.asc()).all()

    valid_prepaids = []
    
    # 階段一：過濾有效額度並動態計算過期日
    for p in prepaids:
        # 新增規則：如果是「研究資料更新」的特別折抵額度
        # 前綴一律以 hpc_bill_utils 的共用常數判斷，不可再寫死字串，
        # 否則發放端新增額度類型時這裡會再次比對不到而整段失效。
        if is_research_bonus(p.source_id):
            # 嚴格限制：只能折抵「同一年」拿到的帳單 (比對帳單開立年份)
            if bill_date_str.startswith(str(p.year)):
                p._calculated_expire = f"{p.year}-12-31"  # 限當年度年底過期
                valid_prepaids.append(p)
            continue # 處理完畢，跳過下方常規儲值邏輯

        # 🛠️ 標準儲值紀錄過期邏輯 (購買年 + 2 的 12-31 之前)
        expire_year = p.year + 2 if p.year else datetime.now().year
        expire_date_str = f"{expire_year}-12-31"
        if expire_date_str >= bill_date_str:
            p._calculated_expire = expire_date_str  # 快遞綁定動態屬性
            valid_prepaids.append(p)

    # 核心優化：重新按「過期日早晚」排序！
    # 舉例：2026年的研究紅利(2026過期) 會被排在 2025年的標準自費(2027過期) 前面優先扣除！
    valid_prepaids.sort(key=lambda x: x._calculated_expire)

    deducted_details = []
    tx_logs = [] # 🌟 新增：用來收集要寫入資料庫的流水帳物件
    
    # 階段二：優先扣除「優惠額度 (discount)」
    for p in valid_prepaids:
        if remaining_bill <= 0:
            break
        if p.discount > 0:
            is_research = "研究更新" if is_research_bonus(p.source_id) else "儲值"
            
            if p.discount >= remaining_bill:
                deducted_details.append(f"從 {p.year} 年[{is_research}]優惠額度扣除 ${remaining_bill} 元")
                
                # 🌟 紀錄流水帳：扣除多少優惠就記負數
                tx_logs.append(QuotaTransaction(
                    username=formal_account, bill_id=bill_id, prepaid_id=p.id,
                    tx_type='deduct', discount_changed=-remaining_bill, amount_changed=0.0,
                    description=f"折抵帳單：從 {p.year} 年[{is_research}]優惠額度扣除"
                ))
                
                p.discount = round(p.discount - remaining_bill, 2)
                remaining_bill = 0.0
            else:
                deducted_details.append(f"從 {p.year} 年[{is_research}]優惠額度扣除 ${p.discount} 元 (已扣完)")
                
                tx_logs.append(QuotaTransaction(
                    username=formal_account, bill_id=bill_id, prepaid_id=p.id,
                    tx_type='deduct', discount_changed=-p.discount, amount_changed=0.0,
                    description=f"折抵帳單：{p.year} 年[{is_research}]優惠額度扣光"
                ))
                
                remaining_bill = round(remaining_bill - p.discount, 2)
                p.discount = 0.0

    # 階段三：扣除「自費金額 (amount)」
    for p in valid_prepaids:
        if remaining_bill <= 0:
            break
        if p.amount > 0:
            if p.amount >= remaining_bill:
                deducted_details.append(f"從 {p.year} 年自費金額扣除 ${remaining_bill} 元")
                
                # 🌟 紀錄流水帳
                tx_logs.append(QuotaTransaction(
                    username=formal_account, bill_id=bill_id, prepaid_id=p.id,
                    tx_type='deduct', discount_changed=0.0, amount_changed=-remaining_bill,
                    description=f"折抵帳單：從 {p.year} 年自費金額扣除"
                ))
                
                p.amount = round(p.amount - remaining_bill, 2)
                remaining_bill = 0.0
            else:
                deducted_details.append(f"從 {p.year} 年自費金額扣除 ${p.amount} 元 (已扣完)")
                
                tx_logs.append(QuotaTransaction(
                    username=formal_account, bill_id=bill_id, prepaid_id=p.id,
                    tx_type='deduct', discount_changed=0.0, amount_changed=-p.amount,
                    description=f"折抵帳單：{p.year} 年自費金額扣光"
                ))
                
                remaining_bill = round(remaining_bill - p.amount, 2)
                p.amount = 0.0

    # 🌟 修改回傳值：把流水帳物件一起丟回去給 Controller 寫入
    return True, remaining_bill, deducted_details, "額度扣減運算完成", tx_logs

# =========================================================================
# 1. 動態計算該帳號尚未扣款的「建議帳單金額」 (供管理員核對)
# =========================================================================
def compute_suggested_bill(contact, id):
    """
    算出「本期應收總金額」的建議值與自動帶入的核對備註說明。

    抽成共用函式的原因：這組「建議金額 + 自動備註」除了給前端預先填入之外，
    送出開單／扣款時後端還要再算一次，用來判斷管理員是否改了金額卻沒有
    一併修改備註（見 validate_amount_and_notes）。兩邊必須是同一份邏輯，
    否則前端顯示的跟後端檢查的會對不起來。

    Returns:
        dict: {'suggested_amount', 'bill_date', 'notes'}；
              未對應正式帳號時 suggested_amount 為 None（代表無法試算）。
    """
    formal_account_info = contact.get_formal_account()
    username = (formal_account_info if isinstance(formal_account_info, str)
                else getattr(formal_account_info, 'username', None))

    if not username:
        return {
            'suggested_amount': None,
            'bill_date': datetime.now().strftime('%Y-%m-%d'),
            'notes': '未對應正式帳號，無法試算'
        }

    last_year = datetime.now().year - 1

    # 優先判斷之前有沒有開過「扣款後因額度不足自動補開」的帳單
    # 透過關鍵字『額度不足自動補開單』與『特定年份』進行精準比對
    existing_bill = Bill.query.filter(
        Bill.contact_id == id,
        Bill.notes.like('%額度不足自動補開單%'),
        Bill.notes.like(f'%{last_year}%'),  # 👈 確保是針對同一個計算年份
        Bill.status.in_(['unpaid', 'paid'])  # 排除已取消 (cancelled) 的帳單
    ).order_by(Bill.created_at.desc()).first()

    if existing_bill:
        # 1. 若該帳單為「未繳費」，直接改成顯示該帳單剩餘金額
        if existing_bill.status == 'unpaid':
            return {
                'suggested_amount': round(float(existing_bill.amount), 2),
                'bill_date': existing_bill.created_at.strftime('%Y-%m-%d'),
                'notes': f"⚠️ 系統提示：該帳號先前已執行過扣款，此金額為【未繳費】的差額帳單內容 (帳單 ID: {existing_bill.id})。"
            }

        # 2. 若該帳單「已繳費」，直接顯示 0.0 元
        return {
            'suggested_amount': 0.0,
            'bill_date': datetime.now().strftime('%Y-%m-%d'),
            'notes': f"✅ 系統提示：該年度扣款後補開的差額帳單 (帳單 ID: {existing_bill.id}) 【已完成繳費】，此年度無需再執行扣款。"
        }

    # -----------------------------------------------------------------
    # 若先前「沒有」開過相關帳單，才執行原本的 HPC 使用量動態計算邏輯
    # -----------------------------------------------------------------
    result = db.session.query(
        func.sum((Accounting.cores * (cast(Accounting.wtime, Numeric) / 3600)) * Serverlist.price).label('total_price'),
        func.count(Accounting.jobid).label('job_count')
    ).join(
        # 計價一律走 accounting_price_join()：同一個 (server, queue) 會有多筆
        # 歷史費率，它會依 job 年份挑出唯一適用的那一筆（見該函式說明）
        Serverlist, accounting_price_join()
    ).filter(
        Accounting.username == username,
        func.extract('year', Accounting.endtime) == last_year
    ).first()

    final_amount = round(float(result.total_price or 0), 2)
    job_count = result.job_count or 0

    return {
        'suggested_amount': final_amount,
        'bill_date': datetime.now().strftime('%Y-%m-%d'),
        'notes': f"{last_year} 年度合計 {job_count} 筆作業，系統自動統計費用。"
    }


def validate_amount_and_notes(contact, id, submitted_amount, submitted_notes):
    """
    金額被改過時，強制要求管理員也自己寫過「核對備註說明」。

    為什麼不是「有沒有填文字」就好：備註欄一開啟就會自動帶入系統產生的說明
    （例如「2025 年度合計 123 筆作業，系統自動統計費用。」），所以「有文字」
    永遠成立，擋不住任何東西。真正要擋的是「金額被人工調整過，備註卻還是
    系統自動產生的那一句」—— 那張單日後沒有人說得出金額為什麼不一樣。

    因此比對的是「備註是否仍等於系統當下會自動產生的那句話」。
    前端會做同樣的檢查，這裡是後端的第二道關卡（前端可以被繞過）。

    Returns:
        None 代表通過；否則回傳給前端顯示的錯誤訊息。
    """
    suggestion = compute_suggested_bill(contact, id)
    suggested_amount = suggestion['suggested_amount']

    # 無法試算（未對應正式帳號）時不做這項檢查，否則會擋死正常的手動開單
    if suggested_amount is None:
        return None

    try:
        amount = round(float(submitted_amount), 2)
    except (TypeError, ValueError):
        return '金額格式不正確。'

    if amount == round(float(suggested_amount), 2):
        return None

    notes = (submitted_notes or '').strip()
    if not notes:
        return ('本期應收總金額已與系統試算金額不同，請於「核對備註說明」填寫調整原因後再送出。')

    if notes == suggestion['notes'].strip():
        return (f"本期應收總金額已由系統試算的 ${suggested_amount:,.2f} 調整為 ${amount:,.2f}，"
                "請一併修改「核對備註說明」寫出調整原因（目前仍是系統自動帶入的文字）。")

    return None


@quota_bp.route('/api/contacts/<int:id>/calculate_pending_bill', methods=['GET'])
def calculate_pending_bill(id):
    contact = Contact.query.get_or_404(id)

    try:
        suggestion = compute_suggested_bill(contact, id)
        if suggestion['suggested_amount'] is None:
            return jsonify({'suggested_amount': 0.0, 'notes': suggestion['notes']}), 200
        return jsonify(suggestion), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'message': '計算失敗', 'error': str(e)}), 500


# =========================================================================
# 2. 接受管理員確認後的「正式扣款」 (拆分為兩階段：先扣款、後手動開單)
# =========================================================================
@quota_bp.route('/api/contacts/<int:id>/confirm_deduct', methods=['POST'])
def confirm_deduct(id):
    """
    [API] 執行額度扣減，若餘額不足時，自動建立並持久化未繳帳單 (Bill)，防止數據丟失
    """
    data = request.get_json() or {}
    final_amount = data.get('final_amount')
    bill_date_str = data.get('bill_date') or date.today().isoformat()
    notes = data.get('notes', '管理員核定扣款')

    if final_amount is None or final_amount < 0:
        return jsonify({'message': '請輸入有效的扣款金額'}), 400
    if final_amount == 0:
        return jsonify({'message': '扣款金額為 0，無需執行'}), 200

    contact = Contact.query.get_or_404(id)

    # 流程順序把關：一定要先寄過確認信，且本年度尚未執行過另一種開單動作
    order_error = workflow_utils.ensure_can_issue_bill(contact, workflow_utils.ACTION_DEDUCT)
    if order_error:
        return jsonify({'message': order_error}), 400

    # 金額被人工調整過時，備註必須是管理員自己寫的，不能還是系統自動帶入的那句
    notes_error = validate_amount_and_notes(contact, id, final_amount, data.get('notes'))
    if notes_error:
        return jsonify({'message': notes_error}), 400

    last_year = datetime.now().year - 1

    try:
        # 核心防呆機制：檢查該聯絡人是否已經有該年度的扣款或開單紀錄
        existing_bill = Bill.query.filter(
            Bill.contact_id == id,
            Bill.status.in_(['unpaid', 'paid']),
            Bill.notes.like(f'%{last_year}%')
        ).first()

        if existing_bill:
            return jsonify({
                'message': f'系統防呆：該帳號先前已執行過 {last_year} 年度的帳務處理 (帳單 ID: {existing_bill.id}，目前狀態: {existing_bill.status})，無法重複執行扣款！'
            }), 400

        # 🌟 1. 執行記憶體中的額度扣減運算（正確解包 5 個回傳值）
        success, remaining_bill, details, msg, tx_logs = execute_quota_deduction(id, final_amount, bill_date_str)
        
        if not success:
            return jsonify({'message': msg}), 400

        new_bill = None
        
        # 2. 根據扣除結果，建立對應的 Bill 物件
        if remaining_bill > 0:
            bill_notes = f"【額度不足自動補開單】原總費 ${final_amount}，扣除可用已付款預付額度後之差額。({last_year}年度 - {notes})"
            new_bill = Bill(
                contact_id=id,
                amount=remaining_bill,
                status='unpaid',
                notes=bill_notes
            )
        else:
            bill_notes = f"【額度全額扣款成功】原總費 ${final_amount} 已由預付額度全額抵扣完畢。({last_year}年度 - {notes})"
            new_bill = Bill(
                contact_id=id,
                amount=0.0,
                status='paid',
                notes=bill_notes
            )
            
        db.session.add(new_bill)
        
        # 🌟 3. 核心魔法：先 flush 逼出 new_bill.id，此時尚未真正 commit 進入資料庫
        db.session.flush() 
        
        # 🌟 4. 將每一筆扣款流水帳補上剛出爐的 bill_id，並加入 session
        for tx in tx_logs:
            tx.bill_id = new_bill.id
            db.session.add(tx)

        # 記錄流程進度：本年度已用「額度扣款後開立繳費單」開過單，
        # 之後「開立繳費單」就會被鎖住，而「寄送繳費單」則解鎖
        workflow_utils.mark_bill_issued(id, workflow_utils.ACTION_DEDUCT, new_bill.id)

        # 5. 統一提交（Bill、PrepaidAmount 的扣減、QuotaTransaction 流水帳、
        #    流程進度會封裝在同一個交易中）
        db.session.commit()

        # 如果有產生差額繳費單
        if remaining_bill > 0:
            return jsonify({
                'status': 'need_bill',
                'message': f'可用預付額度已扣光！系統已自動將未繳餘額 ${remaining_bill} 元開立未繳繳費單。',
                'detail': details,
                'unpaid_amount': remaining_bill,
                'bill_id': new_bill.id
            }), 200

        # 若全額扣除成功
        return jsonify({
            'status': 'success',
            'message': f"額度全額扣款成功！已成功扣除 ${final_amount} 元，並已寫入扣款歷史紀錄。",
            'detail': details
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'message': '計費扣款程序異常', 'error': str(e)}), 500


@quota_bp.route('/api/contacts/<int:id>/direct_create_bill', methods=['POST'])
def create_bill(id):
    """
    [API] 第二階段：當管理員在前端直接點擊「正式開立繳費單」時，建立 Bill 紀錄
    """
    data = request.get_json() or {}
    amount = data.get('amount')
    notes = data.get('notes', '管理員手動開單')

    if amount is None or float(amount) <= 0:
        return jsonify({'message': '請輸入有效的開單金額'}), 400

    contact = Contact.query.get_or_404(id)

    # 流程順序把關：一定要先寄過確認信，且本年度尚未執行過額度扣款開單
    order_error = workflow_utils.ensure_can_issue_bill(contact, workflow_utils.ACTION_DIRECT)
    if order_error:
        return jsonify({'message': order_error}), 400

    # 金額被人工調整過時，備註必須是管理員自己寫的，不能還是系統自動帶入的那句
    notes_error = validate_amount_and_notes(contact, id, amount, data.get('notes'))
    if notes_error:
        return jsonify({'message': notes_error}), 400

    last_year = datetime.now().year - 1

    try:
        # 核心新增【防呆機制】：手動直接開單前，同樣檢查是否已有該年度帳單
        existing_bill = Bill.query.filter(
            Bill.contact_id == id,
            Bill.status.in_(['unpaid', 'paid']),
            Bill.notes.like(f'%{last_year}%')
        ).first()

        if existing_bill:
            return jsonify({
                'message': f'系統防呆：該帳號已存在 {last_year} 年度的帳務或扣款紀錄 (帳單 ID: {existing_bill.id})，無法重複手動開單。'
            }), 400

        # 自動在備註中加上年度標籤，確保未來的 API 能夠精準識別
        if f"{last_year}" not in notes:
            notes = f"({last_year}年度) {notes}"

        new_bill = Bill(
            contact_id=id,
            amount=round(float(amount), 2),
            status='unpaid',
            notes=notes
        )
        db.session.add(new_bill)
        # 先 flush 逼出 new_bill.id，才能把它記進流程進度
        db.session.flush()

        # 記錄流程進度：本年度已用「開立繳費單」開過單，
        # 之後「額度扣款後開立繳費單」就會被鎖住，而「寄送繳費單」則解鎖
        workflow_utils.mark_bill_issued(id, workflow_utils.ACTION_DIRECT, new_bill.id)

        db.session.commit()

        return jsonify({
            'status': 'success',
            'message': f'成功開立未繳繳費單，金額: ${round(float(amount), 2)} 元！'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': '開立繳費單失敗', 'error': str(e)}), 500


# =========================================================================
# 寄送「確認信範本設定」中編輯好的 HPC 使用量確認信（與寄送繳費單 PDF 是兩件事）
#
# 收件人/副本規則：
#   - 有標記主要聯絡人且能取得 Email -> 主要聯絡人為收件人(to)，其餘聯絡人放副本(cc)
#   - 沒有主要聯絡人可用的 Email -> 找得到的 Email 全部一起放收件人(to)，cc 為空
#   - 「⚙️ 確認信預設副本人員」設定的 Email 一律併入副本(cc)
#
# preview 與 send 共用同一套組裝邏輯，確保「預覽看到的內容」跟「實際寄出的內容」一致。
# =========================================================================
def _build_confirm_email_content(contact):
    """回傳 (result, error_message)；成功時 error_message 為 None，
    result = {'to': [...], 'cc': [...], 'subject': '...', 'html': '...'}"""
    recipients = contact.get_confirm_email_recipients()
    to_emails = recipients['to']
    cc_emails = list(recipients['cc'])

    if not to_emails:
        return None, '找不到聯絡人的 Email，請至「其他聯絡人」欄位確認至少有一筆包含有效 Email 的聯絡資訊。'

    # 併入預設副本人員，並避免跟收件人/既有副本重複
    seen = set(to_emails) | set(cc_emails)
    for email in get_confirm_email_default_cc():
        if email not in seen:
            cc_emails.append(email)
            seen.add(email)

    # 使用量表格需要該聯絡人的正式帳號才能查得到 Accounting 紀錄；
    # 沒有正式帳號時仍允許寄信，只是使用量表格會是空的（不擋信件寄送）。
    formal_account = contact.get_formal_account()
    if formal_account:
        usage = get_account_last_year_usage_details(formal_account)
    else:
        usage = {'usage_year': datetime.now().year - 1, 'usage_rows': [], 'usage_total_su': 0.0}

    # 免費額度 / 學術獎勵額度：來自「⚙️ 設定 → 額度設定」(HPCSetting classification=2)，
    # 讓範本中的數字跟後台設定同步，不用每次調整都要改死範本。
    quota_settings = {item['key']: item['value'] for item in load_hpc_settings_by_classification(2)}
    free_quota = quota_settings.get('free_quota', 0)
    academic_quota = quota_settings.get('academic_quota', 0)

    try:
        template_html = get_confirm_email_template_html()
        rendered_html = render_template_string(
            template_html,
            usage_year=usage['usage_year'],
            usage_total_su=usage['usage_total_su'],
            usage_table=render_usage_table_html(usage),
            year=datetime.now().year,
            free_quota=f'{free_quota:,}',
            academic_quota=f'{academic_quota:,}'
        )
    except Exception as e:
        return None, ('範本渲染失敗，請至「⚙️ 設定 → 確認信範本設定」確認內容格式正確'
                      f'（若範本中仍殘留 {{% for %}} 等舊標籤，請改用 {{{{ usage_table }}}} 或還原預設範本）：{e}')

    subject = f"HPC 運算服務 {usage['usage_year']} 年度使用量確認信"
    return {'to': to_emails, 'cc': cc_emails, 'subject': subject, 'html': rendered_html}, None


@quota_bp.route('/api/contacts/<int:id>/confirm-email-preview', methods=['GET'])
def preview_confirm_email(id):
    """寄送前先產生預覽內容（收件人/副本/主旨/渲染好的 HTML），給前端 modal 顯示確認。"""
    contact = Contact.query.get_or_404(id)
    result, error = _build_confirm_email_content(contact)
    if error:
        return jsonify({'success': False, 'message': error}), 400
    return jsonify(dict(success=True, **result))


@quota_bp.route('/api/contacts/<int:id>/send-confirm-email', methods=['POST'])
def send_confirm_email(id):
    contact = Contact.query.get_or_404(id)
    result, error = _build_confirm_email_content(contact)
    if error:
        return jsonify({'success': False, 'message': error}), 400

    sent = send_hpc_notification_email(result['to'], result['subject'], result['html'], cc=result['cc'])
    if not sent:
        return jsonify({'success': False, 'message': '確認信寄送失敗，請確認 SMTP 設定或稍後再試。'}), 500

    # 記錄流程進度：確認信是開單流程的第一步，寄出後才會解鎖後面兩顆開單按鈕。
    # 確認信允許重寄（例如上次寄錯人），重寄只會更新時間，不影響已走到的步驟。
    workflow_utils.mark_confirm_email_sent(id)
    db.session.commit()

    all_recipients = result['to'] + result['cc']
    return jsonify({'success': True, 'message': f"確認信已成功寄送給：{', '.join(all_recipients)}。"})


# =========================================================================
# 開單流程狀態：四顆按鈕的啟用/停用完全由這支 API 決定
#
#   寄送確認信 → 額度扣款後開立繳費單 ／ 開立繳費單（擇一）→ 寄送繳費單
#
# 前端的 ng-disabled 只是提示，每一支 API 內部都會再檢查一次，
# 所以直接打 API 也跳不過順序。
# =========================================================================
@quota_bp.route('/api/contacts/<int:id>/billing-workflow', methods=['GET'])
def get_billing_workflow(id):
    contact = Contact.query.get_or_404(id)
    unpaid_prepaids = get_unpaid_prepaids(contact.get_formal_account())
    state = workflow_utils.build_workflow_state(contact, has_unpaid_prepaid=bool(unpaid_prepaids))
    state['unpaid_prepaid_total'] = round(sum(float(p.amount or 0) for p in unpaid_prepaids), 2)
    state['unpaid_prepaid_count'] = len(unpaid_prepaids)
    return jsonify(state)


# =========================================================================
# 帳單折扣的「使用／不使用」開關
#
# 折扣（⚙️ 系統設定 → 帳單折扣設定）與「額度扣款後開立繳費單」互斥：
# 折扣是給客戶的減免，額度扣款是拿客戶已經預付的錢來抵，兩者同時成立
# 會變成同一筆費用被折兩次，所以一旦標記為使用折扣，額度扣款就鎖住。
#
# 狀態存在 billing_workflows.discount_applied，前端重新整理後仍記得；
# 前端的 disabled 只是提示，confirm_deduct 內部（ensure_can_issue_bill）
# 會再擋一次，直接打 API 也繞不過去。
# =========================================================================
@quota_bp.route('/api/contacts/<int:id>/billing-discount', methods=['POST'])
def set_billing_discount(id):
    contact = Contact.query.get_or_404(id)
    data = request.get_json() or {}

    applied = data.get('applied')
    if not isinstance(applied, bool):
        return jsonify({'message': 'applied 必須是 true 或 false。'}), 400

    # 要開啟折扣，得先有折扣設定，否則等於標記了一個沒有內容的折扣
    if applied and not load_bill_discount():
        return jsonify({
            'message': '尚未設定帳單折扣，請先至「⚙️ 系統設定 → 帳單折扣設定」填寫門檻金額與折數。'
        }), 400

    workflow, error = workflow_utils.set_discount_applied(contact.id, applied)
    if error:
        return jsonify({'message': error}), 400

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': '折扣狀態儲存失敗', 'error': str(e)}), 500

    unpaid_prepaids = get_unpaid_prepaids(contact.get_formal_account())
    state = workflow_utils.build_workflow_state(contact, has_unpaid_prepaid=bool(unpaid_prepaids))

    return jsonify({
        'success': True,
        'message': '已設定為使用帳單折扣，本年度將無法使用額度扣款。' if applied else '已取消使用帳單折扣。',
        'workflow': state
    }), 200


# =========================================================================
# 寄送繳費單（與寄送確認信是兩條完全獨立的流程）
#
#   - 信件本文：templates/email/bill_notification.html（可在設定中自訂）
#   - 附件    ：templates/quotation/hpc_quotation.html 轉成的 PDF 報價單
#
# 報價單表頭那幾格（客戶名稱／連絡人／連絡電話／電子信箱／報價日期／使用期間）
# 由前端以表格逐格填寫，開啟時會自動帶入聯絡人資料；金額相關的欄位一律
# 以資料庫實算為準，不接受前端覆寫。
#
# preview 與 send 共用 _build_bill_email_content，確保「預覽看到的」
# 就是「實際寄出的」。
# =========================================================================
def _build_bill_email_content(contact, kind, overrides):
    """回傳 (result, error)；result 內含收件人、主旨、通知信 HTML、報價單 HTML 與欄位預設值。"""
    recipients = contact.get_confirm_email_recipients()
    to_emails = recipients['to']
    cc_emails = list(recipients['cc'])

    if not to_emails:
        return None, '找不到聯絡人的 Email，請至「其他聯絡人」欄位確認至少有一筆包含有效 Email 的聯絡資訊。'

    # 併入預設副本人員，並避免跟收件人/既有副本重複
    seen = set(to_emails) | set(cc_emails)
    for email in get_confirm_email_default_cc():
        if email not in seen:
            cc_emails.append(email)
            seen.add(email)

    year = workflow_utils.get_billing_year()
    context, error = build_quotation_context(contact, year, kind=kind, overrides=overrides)
    if error:
        return None, error

    try:
        quotation_html = render_quotation_html(context)
    except Exception as e:
        return None, f'報價單範本渲染失敗：{e}'

    try:
        notification_html = render_bill_notification_html(context)
    except Exception as e:
        return None, ('繳費單通知信範本渲染失敗，請至「⚙️ 設定」確認範本內容格式正確'
                      f'（變數請維持 {{{{ 變數名 }}}} 格式）：{e}')

    # 主旨要能一眼分辨是哪一種單：
    #   一般帳單 → 結算的是「去年度」的實際用量，所以掛帳務年度 (year)
    #   預繳帳單 → 收的是當年度要預繳的款項，與去年度用量無關，所以掛當年度
    # （視窗標題與信件內文仍不特別標示「預繳」，對客戶而言就是一張繳費單。）
    if kind == workflow_utils.KIND_PREPAID:
        subject = f"HPC 運算服務 {datetime.now().year} 年度預繳繳費單"
    else:
        subject = f"HPC 運算服務 {year} 年度繳費單"

    return {
        'to': to_emails,
        'cc': cc_emails,
        'subject': subject,
        'kind': kind,
        'year': year,
        'notification_html': notification_html,
        'quotation_html': quotation_html,
        # 給前端表格用的欄位值（開啟時自動帶入，可逐格修改後再送出）
        'fields': {
            'customer_name': context['customer_name'],
            'contact_person': context['contact_person'],
            'contact_phone': context['contact_phone'],
            'contact_email': context['contact_email'],
            'quote_date': context['quote_date'],
            'usage_period': context['usage_period'],
            # 預繳帳單專用：金額要計入哪一項計算資源
            'prepaid_target': context.get('prepaid_target', '')
        },
        # 預繳帳單可選的計入位置（一般帳單為空清單）
        'prepaid_targets': context.get('prepaid_targets') or [],
        'rows': context['quotation_rows'],
        'total_text': context['total_text'],
        'total': context['total'],
        # 兩種「錢會從帳單上無聲消失」的情況都要講出來：
        #   unmatched 有費率但沒被任何一列格式設定涵蓋到
        #   unpriced  Serverlist 根本沒有該 (server, queue) 的費率，連金額都算不出來
        'unmatched': context['unmatched'],
        'unmatched_amount': context['unmatched_amount'],
        'unpriced': context['unpriced']
    }, None


@quota_bp.route('/api/contacts/<int:id>/bill-email-preview', methods=['GET'])
def preview_bill_email(id):
    """開啟「寄送繳費單」視窗時取得預覽內容與可編輯欄位的預設值。"""
    contact = Contact.query.get_or_404(id)
    kind = request.args.get('kind', workflow_utils.KIND_NORMAL)

    unpaid_prepaids = get_unpaid_prepaids(contact.get_formal_account())
    order_error = workflow_utils.ensure_can_send_quotation(contact, kind, bool(unpaid_prepaids))
    if order_error:
        return jsonify({'success': False, 'message': order_error}), 400

    # 前端會把使用者改過的欄位透過 query string 帶回來重新預覽
    overrides = {key: request.args.get(key) for key in
                 ('customer_name', 'contact_person', 'contact_phone', 'contact_email',
                  'quote_date', 'usage_period', 'prepaid_target')}

    result, error = _build_bill_email_content(contact, kind, overrides)
    if error:
        return jsonify({'success': False, 'message': error}), 400

    return jsonify(dict(success=True, **result))


@quota_bp.route('/api/contacts/<int:id>/send-bill-email', methods=['POST'])
def send_bill_email(id):
    """把繳費單通知信寄出：報價單轉成 PDF 當附件，通知信 HTML 當信件本文。"""
    contact = Contact.query.get_or_404(id)
    data = request.get_json() or {}
    kind = data.get('kind', workflow_utils.KIND_NORMAL)

    unpaid_prepaids = get_unpaid_prepaids(contact.get_formal_account())
    order_error = workflow_utils.ensure_can_send_quotation(contact, kind, bool(unpaid_prepaids))
    if order_error:
        return jsonify({'success': False, 'message': order_error}), 400

    result, error = _build_bill_email_content(contact, kind, data.get('fields') or {})
    if error:
        return jsonify({'success': False, 'message': error}), 400

    pdf_bytes, pdf_error = quotation_html_to_pdf(result['quotation_html'])
    if pdf_error:
        return jsonify({'success': False, 'message': pdf_error}), 500

    filename = build_quotation_filename(contact, {'kind': kind, 'usage_year': result['year']})
    sent, send_error = send_email_with_pdf(
        recipients=result['to'],
        subject=result['subject'],
        html_body=result['notification_html'],
        pdf_bytes=pdf_bytes,
        filename=filename,
        cc=result['cc']
    )

    if not sent:
        return jsonify({
            'success': False,
            'message': f"繳費單寄送失敗，請確認 SMTP 設定或稍後再試。（{send_error}）"
        }), 500

    workflow_utils.mark_quotation_sent(id, kind)
    db.session.commit()

    all_recipients = result['to'] + result['cc']
    return jsonify({
        'success': True,
        'message': f"繳費單已成功寄送給：{', '.join(all_recipients)}。"
    })


@quota_bp.route('/api/contacts/<int:id>/research_bonus', methods=['POST'])
def grant_research_bonus(id):
    """管理員後台連動：合併為單一 API，支援單次批次發放多種類型額度"""
    contact = Contact.query.get_or_404(id)
    formal_account = contact.get_formal_account()
    if not formal_account:
        return jsonify({'message': '該對象尚未對應正式帳號，無法發放額度'}), 400

    # 解析前端傳入的批次資料
    data = request.get_json() or {}
    items = data.get('items', [])
    
    if not items:
        return jsonify({'message': '未偵測到任何發放項目'}), 400

    current_year = datetime.now().year
    amount = 0.0  # 實收金額維持 0.0

    # 統一配置管理
    # 額度金額改成即時讀取「⚙️ 學術獎勵額度與優惠區間」設定（HPCSetting classification=2），
    # 不再寫死 10000 / 1000，否則管理員在設定頁改了數字，這裡發放時還是用舊的固定值。
    quota_settings = {item['key']: item['value'] for item in load_hpc_settings_by_classification(2)}
    bonus_configs = {
        'free': {'label': '免費研究折抵', 'base_amount': float(quota_settings.get('free_quota') or 10000), 'use_quantity': False},
        'academic': {'label': '學術獎勵', 'base_amount': float(quota_settings.get('academic_quota') or 1000), 'use_quantity': True}
    }

    records_to_add = []
    success_details = []

    try:
        for item in items:
            bonus_type = item.get('type')
            if bonus_type not in bonus_configs:
                return jsonify({'message': f'未知的獎勵額度類型: {bonus_type}'}), 400
                
            cfg = bonus_configs[bonus_type]
            
            # 數量解析與防呆
            try:
                quantity = int(item.get('quantity', 1))
            except (ValueError, TypeError):
                return jsonify({'message': f'【{cfg["label"]}】發放數量格式不正確'}), 400

            if quantity <= 0:
                return jsonify({'message': f'【{cfg["label"]}】發放數量必須大於 0'}), 400
            
            if quantity > 10:
                return jsonify({'message': f'【{cfg["label"]}】至多只能採記 10 篇'}), 400

            # 計算動態金額與前綴。
            # 前綴開頭必須沿用共用常數，扣款端 execute_quota_deduction 是靠它
            # 認出「這是研究獎勵額度」而套用限當年折抵與優先扣抵的規則。
            discount = cfg['base_amount'] * quantity if cfg['use_quantity'] else cfg['base_amount']
            bonus_prefix = f"{RESEARCH_BONUS_SOURCE_PREFIX}{bonus_type.upper()}_{current_year}_"

            # 防呆機制：檢查今年是否領過
            existing_bonus = PrepaidAmount.query.filter(
                PrepaidAmount.username == formal_account,
                PrepaidAmount.year == current_year,
                PrepaidAmount.is_history == False,
                PrepaidAmount.source_id.like(f"{bonus_prefix}%")
            ).first()
            
            if existing_bonus:
                return jsonify({'message': f'該帳號在 {current_year} 年度已領取過【{cfg["label"]}】額度，不可重複發放'}), 400

            # 產生此項目的唯一交易追蹤碼
            current_source_id = f"{bonus_prefix}{uuid.uuid4()}"

            # 建立活躍可用額度
            prepaid_active = PrepaidAmount(
                username=formal_account,
                amount=amount,
                discount=discount,
                year=current_year,
                payment_date=datetime.now(),
                is_paid=True,  
                is_history=False,
                source_id=current_source_id
            )
            
            # 建立歷史備份存檔
            prepaid_history = PrepaidAmount(
                username=formal_account,
                amount=amount,
                discount=discount,
                year=current_year,
                payment_date=datetime.now(),
                is_paid=True,
                is_history=True,
                source_id=current_source_id
            )
            
            records_to_add.extend([prepaid_active, prepaid_history])

            # 收集成功訊息文本
            if cfg['use_quantity']:
                detail_msg = f"{int(cfg['base_amount']):,} 元 × {quantity} = 共 {int(discount):,} 元"
            else:
                detail_msg = f"{int(discount):,} 元"
            success_details.append(f"・{cfg['label']}額度: {detail_msg}")

        # 🚀 通過所有防呆後，整批塞入資料庫
        for record in records_to_add:
            db.session.add(record)
        
        db.session.commit()
        
        # 組合最終回傳訊息
        success_message = f"成功匯入 {current_year} 年度研究獎勵額度！\n" + "\n".join(success_details)
        return jsonify({'message': success_message}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'message': '資料庫儲存失敗，請聯繫系統管理員', 'error': str(e)}), 500