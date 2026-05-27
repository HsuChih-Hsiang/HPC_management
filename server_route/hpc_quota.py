from flask import request, jsonify, Blueprint
from decimal import Decimal
from database.extensions import db
from database.hpc_model import Contact, PrepaidAmount, Accounting, Serverlist, Bill
from sqlalchemy import and_, func, cast, Numeric
from datetime import datetime, date

quota_bp = Blueprint('quota', __name__)

@quota_bp.route('/api/contacts/<int:id>/quota', methods=['PUT'])
def add_contact_quota(id):
    """管理員後台提交：新增特定年份的購買額度"""
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

    # 自動附加 20% 的優惠額度入庫 (總額 = 購買實收 + 20% 優惠)
    discount_rate = 0.20
    total_added = amount + round(amount * discount_rate, 2)

    try:
        # 尋找該正式帳號在「該購買年份」是否已有現成紀錄
        prepaid = PrepaidAmount.query.filter_by(username=formal_account, year=purchase_year).first()
        
        if not prepaid:
            prepaid = PrepaidAmount(
                username=formal_account,
                amount=total_added,
                year=purchase_year,
                payment_date=datetime.combine(purchase_date, datetime.min.time())
            )
            db.session.add(prepaid)
        else:
            prepaid.amount += total_added
            prepaid.payment_date = datetime.combine(purchase_date, datetime.min.time())

        db.session.commit()
        return jsonify({'message': '額度新增成功'}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'message': '資料庫儲存失敗', 'error': str(e)}), 500


# =========================================================================
# 3. 核心計費扣款邏輯 (Deduct Logic)
# =========================================================================

def deduct_quota_for_bill(contact_id, bill_amount, bill_date_str):
    """
    實進實出扣款邏輯：直接扣減對應年份的 PrepaidAmount.amount
    """
    contact = Contact.query.get(contact_id)
    if not contact:
        return False, "找不到該聯絡人"

    formal_account = contact.get_formal_account()
    if not formal_account:
        return False, "該聯絡人未對應正式帳號"

    try:
        remaining_bill = float(bill_amount)
        if remaining_bill <= 0:
            return True, "無需扣款"

        # 依年份由舊到新排序，找出還有錢的儲值紀錄
        prepaids = PrepaidAmount.query.filter(
            PrepaidAmount.username == formal_account,
            PrepaidAmount.amount > 0
        ).order_by(PrepaidAmount.year.asc()).all()

        for p in prepaids:
            if remaining_bill <= 0:
                break

            # 檢驗過期日 (購買年 + 2 的 01-31)
            expire_date_str = f"{p.year + 2}-01-31"
            if expire_date_str < bill_date_str:
                continue  # 已過期的額度，跳過不扣

            # 實質執行扣除
            if p.amount >= remaining_bill:
                p.amount = round(p.amount - remaining_bill, 2)
                remaining_bill = 0.0
            else:
                remaining_bill = round(remaining_bill - p.amount, 2)
                p.amount = 0.0

        if remaining_bill > 0:
            db.session.rollback()
            return False, "扣款失敗：各年份適用之可用餘額不足"

        db.session.commit()
        return True, "扣款成功"

    except Exception as e:
        db.session.rollback()
        return False, f"計費扣款程序異常: {str(e)}"
    

# =========================================================================
# 1. 動態計算該帳號尚未扣款的「建議帳單金額」 (供管理員核對)
# =========================================================================
@quota_bp.route('/api/contacts/<int:id>/calculate_pending_bill', methods=['GET'])
def calculate_pending_bill(id):
    """
    [API] 整合統計邏輯：計算指定單一帳號「去年」整年度的 HPC 運算費用
    """
    # 1. 取得聯絡人與其對應的正式帳號
    contact = Contact.query.get_or_404(id)
    formal_account_info = contact.get_formal_account()
    
    # 統一處理字串或物件回傳
    username = formal_account_info if isinstance(formal_account_info, str) else getattr(formal_account_info, 'username', None)
    
    if not username:
        return jsonify({'suggested_amount': 0.0, 'notes': '未對應正式帳號，無法試算'}), 200

    # 2. 設定去年區間
    last_year = datetime.now().year - 1
    
    try:
        # 3. 使用整合後的 ORM 統計邏輯
        # 這裡直接 JOIN Serverlist，並依據該 User 在 Accounting 表中的紀錄進行加總
        result = db.session.query(
            func.sum(
                (Accounting.cores * (cast(Accounting.wtime, Numeric) / 3600)) * Serverlist.price
            ).label('total_price'),
            func.count(Accounting.jobid).label('job_count')
        ).join(
            Serverlist, Accounting.host == Serverlist.server
        ).filter(
            Accounting.username == username,
            func.extract('year', Accounting.endtime) == last_year,
            Accounting.status == 1  # 確保只計算成功完成的任務
        ).first()

        # 4. 解析結果
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
# 2. 接受管理員變更後的金額，按下確認後才「正式扣款」 (實進實出)
# =========================================================================
@quota_bp.route('/api/contacts/<int:id>/confirm_deduct', methods=['POST'])
def confirm_deduct(id):
    """
    [API] 管理員手動核對並修改金額後，按下「確認扣款」才真正執行的路由
    """
    data = request.get_json() or {}
    final_amount = data.get('final_amount')      # 管理員在前端修改調整後的最終金額
    bill_date_str = data.get('bill_date')        # 帳單歸屬日期 (用以比對額度是否過期)
    notes = data.get('notes', '系統扣款')

    if final_amount is None or final_amount < 0:
        return jsonify({'message': '請輸入有效的扣款金額'}), 400
    if final_amount == 0:
        return jsonify({'message': '扣款金額為 0，無需執行'}), 200

    contact = Contact.query.get_or_404(id)
    formal_account = contact.get_formal_account()
    if not formal_account:
        return jsonify({'message': '該聯絡人未對應正式帳號，無法扣款'}), 400

    if not bill_date_str:
        bill_date_str = date.today().isoformat()

    try:
        remaining_bill = float(final_amount)

        # 撈出該帳號所有還有餘額（amount > 0）的年度紀錄，由舊到新（年分小到大）排序
        prepaids = PrepaidAmount.query.filter(
            PrepaidAmount.username == formal_account,
            PrepaidAmount.amount > 0
        ).order_by(PrepaidAmount.year.asc()).all()

        deducted_details = []

        for p in prepaids:
            if remaining_bill <= 0:
                break

            # 依據該筆紀錄的儲值年份，定義它的過期截止日（購買年 + 2 的 1/31）
            expire_date_str = f"{p.year + 2}-01-31"

            # 隔離防禦：如果這筆年度額度已經過期，則跳過不扣
            if expire_date_str < bill_date_str:
                continue

            # 實質執行扣除
            if p.amount >= remaining_bill:
                p.amount = round(p.amount - remaining_bill, 2)
                deducted_details.append(f"從 {p.year} 年額度扣除 {remaining_bill} 元")
                remaining_bill = 0.0
            else:
                deducted_amount = p.amount
                remaining_bill = round(remaining_bill - p.amount, 2)
                p.amount = 0.0
                deducted_details.append(f"從 {p.year} 年額度扣除 {deducted_amount} 元 (已扣完)")

        # 檢查是否全數扣除完畢
        if remaining_bill > 0:
            if remaining_bill > 0:
                # 這裡直接新增一筆「待繳款」的紀錄
                # 假設您選擇新增一個 bill_record 的處理方式
                new_record = Accounting(
                    contact_id=id,
                    amount=remaining_bill,
                    is_paid=False,  # 標記為尚未繳費
                    notes=f"餘額不足，產生繳費單: {notes}",
                    date=bill_date_str
                )
                db.session.add(new_record)
                
                # 完成提交 (同時包含了前面的額度扣除與這裡的待繳紀錄)
                db.session.commit()
                return jsonify({
                    'message': '額度已扣除，剩餘金額已新增為待繳帳單',
                    'detail': deducted_details,
                    'unpaid_amount': remaining_bill
                }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'message': '計費扣款程序異常', 'error': str(e)}), 500
    
@quota_bp.route('/api/contacts/<int:contact_id>/smart_deduct', methods=['POST'])
def smart_deduct_quota(contact_id):
    contact = Contact.query.get_or_44(contact_id) # 假設您的聯絡人模型是 Contact
    data = request.get_json() or {}
    
    total_charge = float(data.get('amount', 0))
    notes = data.get('notes', '')
    
    # 假設聯絡人模型上有儲存當前可用餘額的欄位，例如 contact.current_quota
    current_balance = float(contact.current_quota or 0)
    
    try:
        # 情境 1：餘額充足，直接全額扣款
        if current_balance >= total_charge:
            contact.current_quota = current_balance - total_charge
            
            # 紀錄一筆扣款流水紀錄 (視您的系統架構而定)
            # log_quota_history(contact_id, amount=-total_charge, type='deduct', notes=notes)
            
            db.session.commit()
            return jsonify({
                "status": "success", 
                "message": f"額度扣款成功！已成功扣除 ${total_charge} 元，目前剩餘額度: ${contact.current_quota:.2f} 元。"
            })
            
        # 情境 2：餘額不足，執行複合銷帳 (扣至 0 元 + 餘額轉未繳帳單)
        else:
            remaining_bill_amount = total_charge - current_balance
            
            # 1. 預付額度全部歸零
            contact.current_quota = 0.0
            
            # 2. 自動將不夠的差額，建立一筆『待繳 (unpaid)』的繳費單
            auto_bill = Bill(
                contact_id=contact_id,
                amount=remaining_bill_amount,
                status='unpaid',
                notes=f"【額度不足自動轉單】原總費 ${total_charge}，扣除預付 ${current_balance} 後之差額。({notes})"
            )
            
            db.session.add(auto_bill)
            db.session.commit()
            
            return jsonify({
                "status": "warning",
                "message": f"預付額度不足！已自動扣除現有額度 ${current_balance} 元（額度已歸零），並針對剩餘差額 ${remaining_bill_amount:.2f} 元自動開立了一張未繳繳費單。"
            })
            
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": f"系統處理失敗: {str(e)}"}), 500