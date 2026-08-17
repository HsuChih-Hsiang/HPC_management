import os
import json
import ssl
import smtplib
from database.extensions import db
from database.hpc_model import Accounting, MailboxGroup, MailboxEmail, HPCSetting
from utils.params import SMTP_SERVER, SMTP_PORT, SENDER_EMAIL, SENDER_PASSWORD
from utils.smtp_config import get_smtp_credentials
from email import encoders
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from flask import current_app
from markupsafe import Markup, escape

CONFIRM_EMAIL_TEMPLATE_KEY = 'confirm_email_template'
CONFIRM_EMAIL_DEFAULT_CC_KEY = 'confirm_email_default_cc'



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

def send_hpc_notification_email(recipients, subject, body, cc=None):
    """通用郵件發送函式。recipients 是收件人(To)清單，cc 是副本(Cc)清單（可省略）。"""
    try:
        # 發信帳密改由「設定」頁面管理（存於資料庫、啟動時解密快取），
        # 尚未設定過時會自動退回 .env 的 SENDER_EMAIL / SENDER_PASSWORD。
        sender_email, sender_password = get_smtp_credentials()

        cc = cc or []
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = sender_email
        msg["To"] = ", ".join(recipients)
        if cc:
            msg["Cc"] = ", ".join(cc)

        if any(tag in body for tag in ['<p', '<div', '<h1', '<br', '<span']):
            part = MIMEText(body, "html")
        else:
            part = MIMEText(body, "plain")

        msg.attach(part)

        context = ssl.create_default_context()
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls(context=context)
            server.login(sender_email, sender_password)
            # sendmail 的收件人清單才是實際投遞對象，Cc 標頭只是顯示用，兩者都要帶上才會真的收到信
            server.sendmail(sender_email, recipients + cc, msg.as_string())

        print(f"HPC 通知郵件已成功寄出至 {recipients}" + (f"，副本：{cc}" if cc else "") + "。")
        return True
    except Exception as e:
        print(f"HPC 通知郵件寄送失敗: {e}")
        return False
    

def read_default_confirm_email_template():
    """讀取預設的確認信範本檔案 templates/email/quotation_check_email.html。"""
    default_path = os.path.join(current_app.root_path, 'templates', 'email', 'quotation_check_email.html')
    with open(default_path, 'r', encoding='utf-8') as f:
        return f.read()


def get_confirm_email_template_html():
    """
    讀取「確認信範本設定」的內容：優先讀取資料庫中已儲存的自訂版本
    (HPCSetting.key == 'confirm_email_template')，若尚未自訂過則退回預設檔案
    templates/email/quotation_check_email.html 的內容。

    contact_routes.py 的 GET /api/contacts/confirm-email-template 與寄送確認信
    的功能都要用到同一份範本內容，因此抽成共用函式，避免兩處各存一份讀取邏輯。
    """
    setting = HPCSetting.query.filter_by(key=CONFIRM_EMAIL_TEMPLATE_KEY).first()
    if setting and setting.value:
        return setting.value

    return read_default_confirm_email_template()


def render_usage_table_html(usage):
    """
    在 Python 端組出「使用量表格」的完整 HTML，供確認信範本的 {{ usage_table }} 使用。

    為什麼不直接把 {% for %} 迴圈寫在範本裡讓 Jinja 跑？
    因為範本是用 TinyMCE 所見即所得編輯器編輯的，而 HTML 規範不允許純文字直接
    出現在 <table>/<tbody> 底下（只能在 <td>/<th> 裡）。瀏覽器與 TinyMCE 的
    HTML parser 會把 <tbody> 與 <tr> 之間的 {% for %} 文字「foster parenting」
    搬到整個 <table> 外面，導致迴圈變成空的、資料列跑到迴圈外，範本一存檔就壞掉
    （Jinja 會噴 'row' is undefined）。改成單一個 {{ usage_table }} 佔位符，
    編輯器就沒有可以弄壞的控制標籤了。
    """
    header_cells = [
        ('使用主機', 'left'),
        ('Queue', 'left'),
        ('工作數', 'right'),
        ('Service Unit (SU)', 'right'),
    ]
    cell_style = 'border:1px solid #ddd; padding:8px;'

    html = ['<table style="width:100%; border-collapse: collapse; margin: 10px 0; font-size: 14px;">']
    html.append('<thead><tr style="background-color:#f2f2f2;">')
    for text, align in header_cells:
        html.append(f'<th style="{cell_style} text-align:{align};">{escape(text)}</th>')
    html.append('</tr></thead><tbody>')

    rows = usage.get('usage_rows') or []
    if rows:
        for row in rows:
            html.append('<tr>')
            html.append(f'<td style="{cell_style}">{escape(row.get("host") or "")}</td>')
            html.append(f'<td style="{cell_style}">{escape(row.get("queue") or "")}</td>')
            html.append(f'<td style="{cell_style} text-align:right;">{row.get("job_count") or 0}</td>')
            html.append(f'<td style="{cell_style} text-align:right;">{float(row.get("su") or 0):.2f}</td>')
            html.append('</tr>')
    else:
        html.append(f'<tr><td style="{cell_style} text-align:center; color:#888;" colspan="4">查無使用紀錄</td></tr>')

    html.append('<tr style="font-weight:bold; background-color:#fafafa;">')
    html.append(f'<td style="{cell_style}" colspan="3">總計</td>')
    html.append(f'<td style="{cell_style} text-align:right;">{float(usage.get("usage_total_su") or 0):.2f}</td>')
    html.append('</tr></tbody></table>')

    return Markup(''.join(html))


def get_confirm_email_default_cc():
    """
    讀取「確認信預設副本人員」清單 (HPCSetting.key == 'confirm_email_default_cc')。
    寄送確認信時，這份清單會自動併入 Cc，若尚未設定過則回傳空清單。
    """
    setting = HPCSetting.query.filter_by(key=CONFIRM_EMAIL_DEFAULT_CC_KEY).first()
    if not setting or not setting.value:
        return []
    try:
        emails = json.loads(setting.value)
    except (json.JSONDecodeError, TypeError):
        return []
    return emails if isinstance(emails, list) else []


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


def send_pdf_email(recipient_email, subject, body_text, pdf_bytes, filename="report.pdf"):
    sender_email, sender_password = get_smtp_credentials()

    # 建立多部分郵件物件
    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = recipient_email
    msg['Subject'] = subject

    # 附加信件純文字內文
    msg.attach(MIMEText(body_text, 'plain', 'utf-8'))

    # 建立 PDF 附件物件 (直接讀取記憶體中的 bytes)
    part = MIMEBase('application', 'octet-stream')
    part.set_payload(pdf_bytes)
    
    # 使用 Base64 編碼附件
    encoders.encode_base64(part)
    
    # 設定附件檔名
    part.add_header(
        'Content-Disposition',
        f'attachment; filename="{filename}"'
    )
    msg.attach(part)

    # 透過 SMTP 發送信件
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()  # 啟用安全傳輸
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, recipient_email, msg.as_string())

