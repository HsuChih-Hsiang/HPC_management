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