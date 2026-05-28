import ssl
import smtplib
from database.extensions import db
from database.hpc_model import Accounting
from utils import params
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import current_app
from database.extensions import db
from database.hpc_model import MailboxGroup, MailboxEmail
from jinja2 import Environment, FileSystemLoader
from xhtml2pdf import pisa
import datetime

def load_mailboxes(username):
    """根據使用者名稱加載其專屬的信箱分組"""
    with current_app.app_context():
        # 只篩選該使用者的群組
        groups = MailboxGroup.query.filter_by(owner_username=username).all()
        
        # 預設初始化邏輯（若該使用者尚無任何群組）
        if not groups:
            default_group = MailboxGroup(name="待分組信箱", owner_username=username)
            db.session.add(default_group)
            db.session.commit()
            groups = [default_group]

        result = []
        for g in groups:
            result.append({
                "id": g.id,
                "name": g.name,
                "emails": [e.email_address for e in g.emails]
            })
        return result

def save_mailboxes(username, mailboxes_data):
    """將特定使用者的信箱分組資料存入資料庫"""
    with current_app.app_context():
        try:
            # 獲取該使用者目前在 DB 中的所有群組名稱，用於比對刪除
            current_user_groups = MailboxGroup.query.filter_by(owner_username=username).all()
            current_group_names = {g.name: g for g in current_user_groups}
            
            input_group_names = [g['name'] for g in mailboxes_data]

            # 1. 處理刪除：如果 DB 有但輸入資料沒有，則刪除該群組
            for name, group_obj in current_group_names.items():
                if name not in input_group_names:
                    db.session.delete(group_obj)

            # 2. 處理新增或更新
            for group_data in mailboxes_data:
                group_name = group_data['name']
                
                if group_name in current_group_names:
                    group = current_group_names[group_name]
                else:
                    group = MailboxGroup(name=group_name, owner_username=username)
                    db.session.add(group)
                    db.session.flush() # 取得新 ID

                # 更新信箱列表：清空並重新插入
                MailboxEmail.query.filter_by(group_id=group.id).delete()
                for email_addr in group_data.get('emails', []):
                    new_email = MailboxEmail(email_address=email_addr, group_id=group.id)
                    db.session.add(new_email)
            
            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"使用者 {username} 儲存 Mailboxes 失敗: {e}")
            return False

def send_hpc_notification_email(recipients, subject, body):
    """通用郵件發送函式"""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = params.SENDER_EMAIL
        msg["To"] = ", ".join(recipients)

        if any(tag in body for tag in ['<p', '<div', '<h1', '<br', '<span']):
            part = MIMEText(body, "html")
        else:
            part = MIMEText(body, "plain")
        
        msg.attach(part)
        
        context = ssl.create_default_context()
        with smtplib.SMTP(params.SMTP_SERVER, params.SMTP_PORT) as server:
            server.starttls(context=context)
            server.login(params.SENDER_EMAIL, params.SENDER_PASSWORD)
            server.sendmail(params.SENDER_EMAIL, recipients, msg.as_string())
        
        print(f"HPC 通知郵件已成功寄出至 {recipients}。")
        return True
    except Exception as e:
        print(f"HPC 通知郵件寄送失敗: {e}")
        return False
    

def get_user_email_from_db(username):
    """
    從資料庫中根據使用者名稱查詢其 email 地址。
    請根據實際的資料庫連接和查詢語法進行修改。
    """
    # 假設這裡使用一個名為 `db_session` 的資料庫連接
    # 假設你的資料表名為 `users`，使用者名稱欄位為 `username`，email 欄位為 `email`
    user = db.session.query(Accounting).filter_by(username=username).first()
    if user:
        return user.email
    return None

def generate_ntuspace_invoice():
    invoice_data = {
        "buyer_name": "國立臺灣大學 財務管理處",
        "date": datetime.date.today().strftime("%Y-%m-%d"),
        "invoice_number": "NTUSpace-2026-05001",
        "vendor_name": "國立臺灣大學 計算機及資訊網路中心",
        "vendor_contact": "許智翔", 
        "items": [
            {
                "name": "NTU Space 雲端空間擴充租用 (100GB) - 年租",
                "unit": "式",
                "quantity": 1,
                "unit_price": 1200
            }
        ],
        "memo": "1. 本報價單報價金額已含 5% 營業稅。\n2. 空間擴充將於費用核銷確認後，3 個工作天內於 NTU Space 系統開通。\n3. 如有任何技術問題，請聯繫計資中心。"
    }

    total_amount = sum(item['quantity'] * item['unit_price'] for item in invoice_data['items'])
    invoice_data['total_amount'] = total_amount

    env = Environment(loader=FileSystemLoader('.'))
    template = env.get_template('ntuspace_template.html')
    rendered_html = template.render(invoice_data)

    # 改用 xhtml2pdf 輸出檔案
    output_filename = "NTU_Space雲端儲存空間報價單_財務管理處.pdf"
    print("正在使用 xhtml2pdf 產生報價單 PDF...")
    
    with open(output_filename, "wb") as result_file:
        pisa_status = pisa.CreatePDF(rendered_html, dest=result_file)
        
    if not pisa_status.err:
        print(f"✅ 成功產生報價單：{output_filename}")
    else:
        print("❌ PDF 產生失敗")