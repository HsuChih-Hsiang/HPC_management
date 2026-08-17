import ssl
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import request, jsonify, Blueprint
from utils.params import UNASSIGNED_GROUP_ID, UNASSIGNED_GROUP_NAME
from utils.email_utils import load_mailboxes, save_mailboxes
# SMTP 連線資訊統一透過 ensure_smtp_configured() 取得（來源為「設定」頁面的資料庫設定），
# 不可再直接匯入 utils.params 的常數，
# 否則使用者在畫面上改了發信設定，這支寄信 API 仍會走到舊值。
from utils.smtp_config import ensure_smtp_configured

email_bp = Blueprint('email', __name__)

@email_bp.route('/send_email', methods=['POST'])
def send_email():
    data = request.get_json()
    to_recipients_str = data.get('to', '')
    cc_recipients_str = data.get('cc', '')
    bcc_recipients_str = data.get('bcc', '')
    subject = data.get('subject', '')
    body = data.get('body', '')

    to_recipients = [e.strip() for e in to_recipients_str.split(',') if e.strip()]
    cc_recipients = [e.strip() for e in cc_recipients_str.split(',') if e.strip()]
    bcc_recipients = [e.strip() for e in bcc_recipients_str.split(',') if e.strip()]
    
    all_recipients_set = set(to_recipients + cc_recipients + bcc_recipients)
    all_recipients_list = list(all_recipients_set)

    saved_mailboxes = load_mailboxes("admin")
    unassigned_group = next((g for g in saved_mailboxes if g['id'] == UNASSIGNED_GROUP_ID), None)
    if not unassigned_group:
        unassigned_group = {
            'id': UNASSIGNED_GROUP_ID,
            'name': UNASSIGNED_GROUP_NAME,
            'emails': []
        }
        saved_mailboxes.append(unassigned_group)

    updated = False
    for email in all_recipients_list:
        if not email:
            continue
        in_any_group = any(email in group['emails'] for group in saved_mailboxes)
        if not in_any_group:
            unassigned_group['emails'].append(email)
            updated = True
    
    unassigned_group['emails'] = list(set(unassigned_group['emails']))
    if updated:
        save_mailboxes("admin", saved_mailboxes)
        print("已將新的信箱新增至待分組信箱。")

    try:
        smtp_server, smtp_port, sender_email, sender_password = ensure_smtp_configured()

        context = ssl.create_default_context()
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls(context=context)
            server.login(sender_email, sender_password)
            for email in all_recipients_list:
                if email in cc_recipients or email in bcc_recipients:
                    continue

                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"] = sender_email
                msg["To"] = email 
                
                if cc_recipients_str:
                    msg["Cc"] = cc_recipients_str
                if any(tag in body for tag in ['<p', '<div', '<h1', '<br', '<span']):
                    part = MIMEText(body, "html")
                else:
                    part = MIMEText(body, "plain")
                
                msg.attach(part)
                email = [email] + cc_recipients + bcc_recipients
                server.sendmail(sender_email, email, msg.as_string())
        
        return jsonify({'success': True, 'message': '郵件已成功寄出！'})
    except Exception as e:
        print(f"寄信失敗: {e}")
        return jsonify({'success': False, 'message': f'寄信失敗，請檢查設定: {e}'}), 500