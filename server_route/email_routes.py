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


def _split_emails(raw):
    """把 'a@x, b@y' 這種逗號字串拆成去重後的清單（保持原有順序）。"""
    result = []
    for e in (raw or '').split(','):
        e = e.strip()
        if e and e not in result:
            result.append(e)
    return result


def _clean_email_list(values):
    """把前端傳來的陣列清成去重後的字串清單。"""
    result = []
    for e in (values or []):
        if not isinstance(e, str):
            continue
        e = e.strip()
        if e and e not in result:
            result.append(e)
    return result


def _build_send_jobs(to_recipients, cc_recipients, bcc_recipients, account_groups):
    """
    把畫面上的收件人拆成一封封要寄出的信。

    公告信為了隱私，「手動輸入的收件人」必須一人一封，彼此看不到對方的 Email；
    但「帳號新增」進來的同一個帳號屬於同一個團隊，沒有隱私問題，
    所以一個帳號只寄一封：
      - 該帳號有主要聯絡人 → 主要聯絡人放收件人，其餘團隊成員放副本
      - 沒有主要聯絡人     → 全部放收件人（同一封信）
    上面的拆法由前端依勾選狀態算好後放在 account_groups 的 to / cc 中，
    這裡再把畫面上另外填寫的副本（cc_recipients）併進每一封信。

    Returns:
        list[dict]: [{'to': [...], 'cc': [...], 'label': str}, ...]
    """
    jobs = []

    for email in to_recipients:
        # 同時出現在副本／密件副本的地址不再單獨寄一封，避免同一個人收到兩封
        if email in cc_recipients or email in bcc_recipients:
            continue
        jobs.append({'to': [email], 'cc': list(cc_recipients), 'label': email})

    for group in (account_groups or []):
        if not isinstance(group, dict):
            continue
        group_to = _clean_email_list(group.get('to'))
        group_cc = _clean_email_list(group.get('cc'))
        if not group_to:
            continue

        merged_cc = list(group_cc)
        for email in cc_recipients:
            if email not in merged_cc and email not in group_to:
                merged_cc.append(email)

        jobs.append({
            'to': group_to,
            'cc': merged_cc,
            'label': group.get('label') or ', '.join(group_to)
        })

    return jobs


@email_bp.route('/send_email', methods=['POST'])
def send_email():
    data = request.get_json() or {}
    to_recipients_str = data.get('to', '')
    cc_recipients_str = data.get('cc', '')
    bcc_recipients_str = data.get('bcc', '')
    subject = data.get('subject', '')
    body = data.get('body', '')
    account_groups = data.get('accounts') or []

    to_recipients = _split_emails(to_recipients_str)
    cc_recipients = _split_emails(cc_recipients_str)
    bcc_recipients = _split_emails(bcc_recipients_str)

    jobs = _build_send_jobs(to_recipients, cc_recipients, bcc_recipients, account_groups)
    if not jobs:
        return jsonify({'success': False, 'message': '沒有可寄送的收件人。'}), 400

    # 待分組信箱只收「手動輸入」的地址；帳號新增的聯絡人已經在 HPC 帳號管理中維護，
    # 不需要再灌進信箱分組造成重複管理。
    all_recipients_list = list(dict.fromkeys(to_recipients + cc_recipients + bcc_recipients))

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

    is_html = any(tag in body for tag in ['<p', '<div', '<h1', '<br', '<span'])
    failed = []

    try:
        smtp_server, smtp_port, sender_email, sender_password = ensure_smtp_configured()

        context = ssl.create_default_context()
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls(context=context)
            server.login(sender_email, sender_password)

            for job in jobs:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"] = sender_email
                msg["To"] = ', '.join(job['to'])
                if job['cc']:
                    msg["Cc"] = ', '.join(job['cc'])

                msg.attach(MIMEText(body, "html" if is_html else "plain"))

                # 密件副本只放在信封收件人，不寫進標頭，收件人才看不到
                envelope = list(dict.fromkeys(job['to'] + job['cc'] + bcc_recipients))
                try:
                    server.sendmail(sender_email, envelope, msg.as_string())
                except Exception as e:
                    print(f"寄信失敗 ({job['label']}): {e}")
                    failed.append(job['label'])

        if failed:
            return jsonify({
                'success': False,
                'sent_count': len(jobs) - len(failed),
                'message': f"共 {len(jobs)} 封信中有 {len(failed)} 封寄送失敗：{', '.join(failed)}"
            }), 500

        return jsonify({
            'success': True,
            'sent_count': len(jobs),
            'message': f'郵件已成功寄出（共 {len(jobs)} 封）！'
        })
    except Exception as e:
        print(f"寄信失敗: {e}")
        return jsonify({'success': False, 'message': f'寄信失敗，請檢查設定: {e}'}), 500
