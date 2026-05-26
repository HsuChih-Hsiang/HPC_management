import ssl
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import request, jsonify, Blueprint

from utils import params
from utils.email_utils import load_mailboxes, save_mailboxes

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
    unassigned_group = next((g for g in saved_mailboxes if g['id'] == params.UNASSIGNED_GROUP_ID), None)
    if not unassigned_group:
        unassigned_group = {
            'id': params.UNASSIGNED_GROUP_ID,
            'name': params.UNASSIGNED_GROUP_NAME,
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
        context = ssl.create_default_context()
        with smtplib.SMTP(params.SMTP_SERVER, params.SMTP_PORT) as server:
            server.starttls(context=context)
            server.login(params.SENDER_EMAIL, params.SENDER_PASSWORD)
            for email in all_recipients_list:
                if email in cc_recipients or email in bcc_recipients:
                    continue

                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"] = params.SENDER_EMAIL
                msg["To"] = email 
                
                if cc_recipients_str:
                    msg["Cc"] = cc_recipients_str
                if any(tag in body for tag in ['<p', '<div', '<h1', '<br', '<span']):
                    part = MIMEText(body, "html")
                else:
                    part = MIMEText(body, "plain")
                
                msg.attach(part)
                email = [email] + cc_recipients + bcc_recipients
                server.sendmail(params.SENDER_EMAIL, email, msg.as_string())
        
        return jsonify({'success': True, 'message': '郵件已成功寄出！'})
    except Exception as e:
        print(f"寄信失敗: {e}")
        return jsonify({'success': False, 'message': f'寄信失敗，請檢查設定: {e}'}), 500