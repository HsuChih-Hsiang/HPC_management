import io
from flask import request, jsonify, Blueprint, render_template
from xhtml2pdf import pisa
from database.extensions import db
from database.hpc_model import Contact, PrepaidAmount, Accounting, Serverlist, Bill
from sqlalchemy import and_, func, cast, Numeric
from datetime import datetime, date
from  utils.email_utils import send_pdf_email
import uuid

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

    if 50001 <= amount <= 100000: 
        discount_rate = 0.75
    elif amount > 100000:
        discount_rate = 0.36
    else:
        discount_rate = 1
    discount = abs(amount / discount_rate - amount)

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

def execute_quota_deduction(contact_id, total_charge, bill_date_str):
    """
    核心扣款邏輯（純運算與額度扣減，不進行 db.session.commit()）
    回傳: (is_success, remaining_bill, deducted_details, message)
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

    # 撈出該帳號所有有餘額的年度紀錄，由舊到新排序
    # 🌟 核心修正點：強制加上 PrepaidAmount.is_paid == True，沒付款的紀錄絕對不可以扣抵！
    prepaids = PrepaidAmount.query.filter(
        PrepaidAmount.username == formal_account,
        PrepaidAmount.is_paid == True,  
        (PrepaidAmount.amount > 0) | (PrepaidAmount.discount > 0)
    ).order_by(PrepaidAmount.year.asc()).all()

    # 篩選出未過期的儲值紀錄 (購買年 + 2 的 12-31 之前)
    valid_prepaids = []
    for p in prepaids:
        expire_year = p.year + 2 if p.year else datetime.now().year
        expire_date_str = f"{expire_year}-12-31"
        if expire_date_str >= bill_date_str:
            valid_prepaids.append(p)

    deducted_details = []

    # 🌟 階段一：優先扣除「優惠額度 (discount)」
    for p in valid_prepaids:
        if remaining_bill <= 0:
            break
        if p.discount > 0:
            if p.discount >= remaining_bill:
                deducted_details.append(f"從 {p.year} 年優惠額度扣除 ${remaining_bill} 元")
                p.discount = round(p.discount - remaining_bill, 2)
                remaining_bill = 0.0
            else:
                deducted_details.append(f"從 {p.year} 年優惠額度扣除 ${p.discount} 元 (已扣完)")
                remaining_bill = round(remaining_bill - p.discount, 2)
                p.discount = 0.0

    # 🌟 階段二：若還有殘額，才扣除「自費金額 (amount)」
    for p in valid_prepaids:
        if remaining_bill <= 0:
            break
        if p.amount > 0:
            if p.amount >= remaining_bill:
                deducted_details.append(f"從 {p.year} 年自費金額扣除 ${remaining_bill} 元")
                p.amount = round(p.amount - remaining_bill, 2)
                remaining_bill = 0.0
            else:
                deducted_details.append(f"從 {p.year} 年自費金額扣除 ${p.amount} 元 (已扣完)")
                remaining_bill = round(remaining_bill - p.amount, 2)
                p.amount = 0.0

    return True, remaining_bill, deducted_details, "額度扣減運算完成"
    

# =========================================================================
# 1. 動態計算該帳號尚未扣款的「建議帳單金額」 (供管理員核對)
# =========================================================================
@quota_bp.route('/api/contacts/<int:id>/calculate_pending_bill', methods=['GET'])
def calculate_pending_bill(id):
    contact = Contact.query.get_or_404(id)
    formal_account_info = contact.get_formal_account()
    
    username = formal_account_info if isinstance(formal_account_info, str) else getattr(formal_account_info, 'username', None)
    if not username:
        return jsonify({'suggested_amount': 0.0, 'notes': '未對應正式帳號，無法試算'}), 200

    last_year = datetime.now().year - 1
    
    try:
        result = db.session.query(
            func.sum((Accounting.cores * (cast(Accounting.wtime, Numeric) / 3600)) * Serverlist.price).label('total_price'),
            func.count(Accounting.jobid).label('job_count')
        ).join(
            Serverlist, Accounting.host == Serverlist.server
        ).filter(
            Accounting.username == username,
            func.extract('year', Accounting.endtime) == last_year
        ).first()

        final_amount = round(float(result.total_price or 0), 2)
        job_count = result.job_count or 0
        notes = f"{last_year} 年度合計 {job_count} 筆作業，系統自動統計費用。"

        return jsonify({
            'suggested_amount': final_amount,
            'bill_date': datetime.now().strftime('%Y-%m-%d'),
            'notes': notes
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'message': '計算失敗', 'error': str(e)}), 500


# =========================================================================
# 2. 接受管理員確認後的「正式扣款」 (拆分為兩階段：先扣款、後手動開單)
# =========================================================================
@quota_bp.route('/api/contacts/<int:id>/confirm_deduct', methods=['POST'])
def confirm_deduct(id):
    """
    [API] 第一階段：只執行額度扣減，若餘額不足不自動開單，而是回傳未繳餘額
    """
    data = request.get_json() or {}
    final_amount = data.get('final_amount')
    bill_date_str = data.get('bill_date') or date.today().isoformat()
    notes = data.get('notes', '管理員核定扣款')

    if final_amount is None or final_amount < 0:
        return jsonify({'message': '請輸入有效的扣款金額'}), 400
    if final_amount == 0:
        return jsonify({'message': '扣款金額為 0，無需執行'}), 200

    try:
        # 執行額度扣減（扣到 0 元為止）
        success, remaining_bill, details, msg = execute_quota_deduction(id, final_amount, bill_date_str)
        
        if not success:
            return jsonify({'message': msg}), 400

        # 🌟 核心修改：不論有沒有扣光，都先提交(Commit)這一次的額度變更
        db.session.commit()

        # 🌟 如果額度不夠扣，不自動建單，而是回傳 need_bill 狀態與剩餘金額給前端顯示
        if remaining_bill > 0:
            return jsonify({
                'status': 'need_bill',
                'message': f'可用預付額度已扣光！尚有未繳餘額 ${remaining_bill} 元。',
                'detail': details,
                'unpaid_amount': remaining_bill,
                'suggested_notes': f"【額度不足補開單】原總費 ${final_amount}，扣除可用已付款預付額度後之差額。({notes})"
            }), 200

        # 若全額扣除成功
        return jsonify({
            'status': 'success',
            'message': f"額度全額扣款成功！已成功扣除 ${final_amount} 元。",
            'detail': details
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'message': '計費扣款程序異常', 'error': str(e)}), 500


@quota_bp.route('/api/contacts/<int:id>/create_bill', methods=['POST'])
def create_bill(id):
    """
    [API] 第二階段：當管理員在前端點擊「正式開立繳費單」時，才建立 Bill 紀錄
    """
    data = request.get_json() or {}
    amount = data.get('amount')
    notes = data.get('notes', '管理員手動開單')

    if amount is None or float(amount) <= 0:
        return jsonify({'message': '請輸入有效的開單金額'}), 400

    try:
        new_bill = Bill(
            contact_id=id,
            amount=round(float(amount), 2),
            status='unpaid',
            notes=notes
        )
        db.session.add(new_bill)
        db.session.commit()
        return jsonify({
            'status': 'success',
            'message': f'成功開立未繳繳費單，金額: ${round(float(amount), 2)} 元！'
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': '開立繳費單失敗', 'error': str(e)}), 500


# =========================================================================
# 3. 智慧直接扣款 (多用於系統排程自動扣、或是快速簡易扣款)
# =========================================================================
@quota_bp.route('/api/contacts/<int:contact_id>/smart_deduct', methods=['POST'])
def smart_deduct_quota(contact_id):
    """
    [API] 系統智慧直接扣款 (餘額不足時不開立帳單，直接阻擋並提示)
    """
    Contact.query.get_or_404(contact_id) 
    data = request.get_json() or {}
    total_charge = float(data.get('amount', 0))
    bill_date_str = date.today().isoformat()

    if total_charge <= 0:
        return jsonify({"status": "success", "message": "金額不大於 0，無需扣款"}), 200

    try:
        # 執行額度扣減
        success, remaining_bill, details, msg = execute_quota_deduction(contact_id, total_charge, bill_date_str)
        
        if not success:
            return jsonify({'status': 'error', 'message': msg}), 400

        # 🌟 保持與前一版一樣：自動扣款「不允許自動開立帳單」
        if remaining_bill > 0:
            db.session.rollback()  # 把剛剛扣掉的預算吐回去，不予執行
            return jsonify({
                "status": "error",
                "message": f"自動扣款失敗：現有可用預付額度不足以支付總額 ${total_charge} 元。請至管理後台由管理員核對並手動確認開單。"
            }), 400

        # 額度足夠，扣款成功才提交
        db.session.commit()
        return jsonify({
            "status": "success",
            "message": f"智慧扣款成功！已成功扣除 ${total_charge} 元。",
            "detail": details
        }), 200
            
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": f"系統處理失敗: {str(e)}"}), 500

@quota_bp.route('/api/contacts/send-quotation', methods=['POST'])
def send_hpc_quotation():
    try:
        post_data = request.get_json()
        if not post_data:
            return jsonify({"status": "error", "message": "缺少 JSON 請求內文"}), 400

        # 取得收件者與模板資料
        recipient = post_data.get("recipient")
        if not recipient:
            return jsonify({"status": "error", "message": "缺少收件者 email (recipient)"}), 400

        title = post_data.get("title", "自動生成報告")
        executor = post_data.get("executor", "系統管理員")
        date = post_data.get("date", "2026-05-28")
        items = post_data.get("items", [])

        # Step 1: Jinja2 渲染 HTML
        rendered_html = render_template(
            'quotation/quotation.html', 
            title=title, 
            executor=executor, 
            date=date, 
            items=items
        )

        # Step 2: xhtml2pdf 轉成 PDF bytes (不落地)
        pdf_buffer = io.BytesIO()
        pisa_status = pisa.pisaDocument(
            src=io.BytesIO(rendered_html.encode('utf-8')),
            dest=pdf_buffer
        )

        if pisa_status.err:
            return jsonify({"status": "error", "message": "PDF 轉換失敗"}), 500

        pdf_bytes = pdf_buffer.getvalue()

        # Step 3: 呼叫寄信函式
        email_subject = f"【系統自動通知】{title}"
        email_body = f"您好：\n\n附件為系統自動產生的「{title}」，請查收。\n\n此信件為系統自動發送，請勿直接回信。"
        
        send_pdf_email(
            recipient_email=recipient,
            subject=email_subject,
            body_text=email_body,
            pdf_bytes=pdf_bytes,
            filename="hpc_report.pdf"
        )

        return jsonify({"status": "success", "message": f"成功生成 PDF 並已寄送至 {recipient}"}), 200

    except Exception as e:
        return jsonify({"status": "error", "message": f"伺服器錯誤: {str(e)}"}), 500