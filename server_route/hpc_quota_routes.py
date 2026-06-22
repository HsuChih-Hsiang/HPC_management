import io
import uuid
from xhtml2pdf import pisa
from flask import request, jsonify, Blueprint, render_template, send_file
from database.extensions import db
from database.hpc_model import Contact, PrepaidAmount, Accounting, Serverlist, Bill, QuotaTransaction
from sqlalchemy import func, cast, Numeric
from datetime import datetime, date
from utils.email_utils import send_pdf_email


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
        if p.source_id and p.source_id.startswith('RESEARCH_BONUS_'):
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
            is_research = "研究更新" if p.source_id and p.source_id.startswith('RESEARCH_BONUS_') else "儲值"
            
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
@quota_bp.route('/api/contacts/<int:id>/calculate_pending_bill', methods=['GET'])
def calculate_pending_bill(id):
    contact = Contact.query.get_or_404(id)
    formal_account_info = contact.get_formal_account()
    
    username = formal_account_info if isinstance(formal_account_info, str) else getattr(formal_account_info, 'username', None)
    if not username:
        return jsonify({'suggested_amount': 0.0, 'notes': '未對應正式帳號，無法試算'}), 200

    last_year = datetime.now().year - 1
    
    try:
        # 核心新增：優先判斷之前有沒有開過「扣款後因額度不足自動補開」的帳單
        # 透過關鍵字『額度不足自動補開單』與『特定年份』進行精準比對
        existing_bill = Bill.query.filter(
            Bill.contact_id == id,
            Bill.notes.like('%額度不足自動補開單%'),
            Bill.notes.like(f'%{last_year}%'),  # 👈 確保是針對同一個計算年份
            Bill.status.in_(['unpaid', 'paid']) # 排除已取消 (cancelled) 的帳單
        ).order_by(Bill.created_at.desc()).first()

        if existing_bill:
            # 1. 若該帳單為「未繳費」，直接改成顯示該帳單剩餘金額
            if existing_bill.status == 'unpaid':
                return jsonify({
                    'suggested_amount': round(float(existing_bill.amount), 2),
                    'bill_date': existing_bill.created_at.strftime('%Y-%m-%d'),
                    'notes': f"⚠️ 系統提示：該帳號先前已執行過扣款，此金額為【未繳費】的差額帳單內容 (帳單 ID: {existing_bill.id})。"
                }), 200
            
            # 2. 若該帳單「已繳費」，直接顯示 0.0 元
            elif existing_bill.status == 'paid':
                return jsonify({
                    'suggested_amount': 0.0,
                    'bill_date': datetime.now().strftime('%Y-%m-%d'),
                    'notes': f"✅ 系統提示：該年度扣款後補開的差額帳單 (帳單 ID: {existing_bill.id}) 【已完成繳費】，此年度無需再執行扣款。"
                }), 200

        # -----------------------------------------------------------------
        # 若先前「沒有」開過相關帳單，才執行原本的 HPC 使用量動態計算邏輯
        # -----------------------------------------------------------------
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
            
        # 5. 統一提交（Bill、PrepaidAmount 的扣減、QuotaTransaction 流水帳會封裝在同一個交易中）
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
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'message': f'成功開立未繳繳費單，金額: ${round(float(amount), 2)} 元！'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': '開立繳費單失敗', 'error': str(e)}), 500


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
        bill_date = post_data.get("date") or date.today().isoformat()
        items = post_data.get("items", [])
        
        # 🌟 新增控制參數：是否僅為預覽模式 (預設為 False)
        preview_only = post_data.get("preview", False)

        # Step 1: Jinja2 渲染 HTML
        rendered_html = render_template(
            'quotation/quotation.html', 
            title=title, 
            executor=executor, 
            date=bill_date, 
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

        pdf_buffer.seek(0)
        pdf_bytes = pdf_buffer.getvalue()

        # 🌟 核心新增：如果是預覽模式，直接將 PDF 檔案流回傳給前端瀏覽器
        if preview_only:
            return send_file(
                io.BytesIO(pdf_bytes),
                mimetype='application/pdf',
                as_attachment=False,  # False 表示讓瀏覽器直接線上開啟，而非強制下載
                download_name=f"preview_{bill_date}.pdf"
            )

        # Step 3: 呼叫寄信函式 (非預覽模式，執行真正寄信)
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
    bonus_configs = {
        'free': {'label': '免費研究折抵', 'base_amount': 10000.0, 'use_quantity': False},
        'academic': {'label': '學術獎勵', 'base_amount': 1000.0, 'use_quantity': True}
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

            # 計算動態金額與前綴
            discount = cfg['base_amount'] * quantity if cfg['use_quantity'] else cfg['base_amount']
            bonus_prefix = f"RESEARCH_{bonus_type.upper()}_{current_year}_"

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