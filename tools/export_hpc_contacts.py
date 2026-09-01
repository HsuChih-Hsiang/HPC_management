# -*- coding: utf-8 -*-
"""
匯出「HPC 帳號管理」清單（本機執行的離線工具，不經過網頁與 API）。

匯出內容 = 網頁清單上看得到的所有欄位（含「其他資訊」彈窗裡的研究內容／
使用軟體／計算資源／備註，以及剩餘額度）＋ 網頁上只有在編輯視窗才看得到的
聯絡人資訊（主要／次要聯絡人、是否停用寄信、確認信的收件人與副本名單）。

注意：匯出檔會包含測試帳號密碼與課程學生密碼（網頁清單上本來就會顯示），
請當成機敏檔案保管，不要放進版控或共用資料夾。

用法
----
    # 全部匯出成 CSV（預設檔名 hpc_accounts_<時間>.csv，Excel 可直接開）
    python tools/export_hpc_contacts.py

    # 指定檔名、只匯出 2025 年申請的、只要正式帳號
    python tools/export_hpc_contacts.py -o 2025.csv --year 2025 --type formal

    # 匯出 JSON（欄位與 CSV 相同，適合再餵給其他程式）
    python tools/export_hpc_contacts.py --format json -o accounts.json

    # 另外產出一份「一列一位聯絡人」的檔案，方便做通訊錄
    python tools/export_hpc_contacts.py --contacts-file persons.csv

連線資訊沿用專案根目錄的 .env（DATABASE_URI），不需要另外設定。
"""
import argparse
import csv
import json
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 這支程式可能在任何工作目錄下執行，先把專案根目錄的 .env 讀進來；
# 之後 utils.params 再呼叫一次 load_dotenv() 也不會覆蓋（預設不覆寫既有環境變數）。
from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, '.env'))

from flask import Flask
from sqlalchemy import or_

from database.extensions import db
from database.hpc_model import Contact, ContactAccountMapping, SecondaryContact, UserAccounting
from utils.params import DATABASE_URI

# 同一格內要放多筆資料時用換行分隔（Excel 儲存格內換行，比逗號好讀，也不怕內容本身有逗號）
MULTI_SEP = '\n'


def create_app():
    """建立只為了連資料庫的最小 Flask app（不註冊任何路由，也不啟動排程）。"""
    if not DATABASE_URI:
        raise SystemExit('找不到 DATABASE_URI，請確認專案根目錄的 .env 是否存在且已設定。')

    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URI
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    return app


def account_type(record):
    """與網頁一致的帳號分類：課程 > 正式 > 試用（見 static/js/contact_manager.ctrl.js）。"""
    if record['is_course_account']:
        return '課程帳號'
    if record['formal_account']:
        return '正式帳號'
    return '試用帳號'


def quota_cell(record, value):
    """課程帳號與試用帳號在網頁上額度欄顯示 '-'，匯出比照辦理，避免被誤讀成 0。"""
    if record['is_course_account'] or not record['formal_account']:
        return '-'
    return value or 0


def format_person(person):
    """把一位聯絡人整理成單行文字：姓名｜聯絡資訊｜主要/次要｜已停用寄信"""
    parts = [
        person.get('name') or '(未填姓名)',
        person.get('info') or '',
        '主要聯絡人' if person.get('is_primary') else '次要聯絡人',
    ]
    if person.get('email_disabled'):
        parts.append('已停用寄信')
    return '｜'.join(p for p in parts if p)


def build_row(contact, record):
    """組出一列匯出資料（dict，鍵的順序即 CSV 欄位順序）。"""
    persons = record['secondary_contacts']
    primary = next((p for p in persons if p.get('is_primary')), None)
    others = [p for p in persons if p is not primary]
    # 收件人／副本的判斷邏輯直接沿用寄確認信那一套，避免匯出的名單與實際寄信對不上
    recipients = contact.get_confirm_email_recipients()

    student_pairs = [
        '{}／{}'.format(s['account'] or '', s['password'] or '')
        for s in record['course_students']
    ]

    return {
        'ID': record['id'],
        '申請團隊': record['team_name'] or '',
        '單位(課程)': record['dept_level1'] or '',
        '申請人': record['applicant'] or '',
        '帳號類型': account_type(record),
        '測試帳號': record['trial_account'] or '',
        '測試帳號密碼': record['trail_account_password'] or '',
        '正式帳號': record['formal_account'] or '',
        '使用主機': ', '.join(record['hosts'] or []),
        '申請時間': record['apply_date'] or '',
        '測試期限': record['test_deadline'] or '',
        '剩餘優惠額度': quota_cell(record, record['discount_remaining']),
        '剩餘總額度': quota_cell(record, record['total_remaining']),
        '研究內容': record['research_content'] or '',
        '使用軟體': record['used_software'] or '',
        '計算資源': record['calc_resource'] or '',
        '備註': record['notes'] or '',
        '聯絡資訊': record['contact_info'] or '',
        '主要聯絡人': (primary or {}).get('name') or '',
        '主要聯絡人資訊': (primary or {}).get('info') or '',
        '主要聯絡人已停用寄信': '是' if (primary or {}).get('email_disabled') else '',
        '聯絡人數': len(persons),
        '其他聯絡人': MULTI_SEP.join(format_person(p) for p in others),
        '確認信收件人': ', '.join(recipients['to']),
        '確認信副本': ', '.join(recipients['cc']),
        '課程學生帳號': MULTI_SEP.join(student_pairs),
    }


def build_person_rows(record):
    """一列一位聯絡人的扁平資料，方便直接拿來做通訊錄或群發名單。"""
    return [{
        '聯絡人ID': person['id'],
        '帳號ID': record['id'],
        '申請團隊': record['team_name'] or '',
        '申請人': record['applicant'] or '',
        '正式帳號': record['formal_account'] or '',
        '測試帳號': record['trial_account'] or '',
        '帳號類型': account_type(record),
        '聯絡人姓名': person.get('name') or '',
        '聯絡人資訊': person.get('info') or '',
        '是否主要聯絡人': '是' if person.get('is_primary') else '',
        '已停用寄信': '是' if person.get('email_disabled') else '',
        '寄信開關異動時間': person.get('email_toggled_at') or '',
    } for person in record['secondary_contacts']]


def query_contacts(year=None, account_type_filter=None, search=None):
    """
    撈出要匯出的聯絡人。篩選條件與網頁清單同義
    （server_route/contact_routes.py 的 get_contacts），但這裡不分頁，一次撈完。
    """
    query = (Contact.query
             .outerjoin(ContactAccountMapping)
             .outerjoin(UserAccounting))

    if year:
        query = query.filter(Contact.apply_date.like('{}%'.format(year)))

    if search:
        like = '%{}%'.format(search)
        query = query.outerjoin(SecondaryContact).filter(or_(
            Contact.applicant.like(like),
            Contact.team_name.like(like),
            Contact.trial_account.like(like),
            ContactAccountMapping.manual_account.like(like),
            UserAccounting.username.like(like),
            SecondaryContact.info.like(like),
        ))

    contacts = query.distinct().order_by(Contact.apply_date.desc()).all()

    # 「正式／試用」要看 get_formal_account() 的結果（同時涵蓋系統帳號與手動填的帳號），
    # 用 SQL 表達會很囉嗦；資料量不大，就在 Python 這邊過濾，語意也跟畫面完全一致。
    if account_type_filter:
        wanted = {'course': '課程帳號', 'formal': '正式帳號', 'trial': '試用帳號'}[account_type_filter]
        contacts = [c for c in contacts if account_type({
            'is_course_account': c.is_course_account,
            'formal_account': c.get_formal_account(),
        }) == wanted]

    return contacts


def write_csv(path, rows):
    if not rows:
        print('沒有符合條件的資料，未產生 {}。'.format(path))
        return False
    # utf-8-sig：帶 BOM，Excel 直接雙擊開啟才不會變成亂碼
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return True


def write_json(path, rows):
    if not rows:
        print('沒有符合條件的資料，未產生 {}。'.format(path))
        return False
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    return True


def main():
    parser = argparse.ArgumentParser(description='匯出 HPC 帳號管理清單（含聯絡人資訊）')
    parser.add_argument('-o', '--output', help='輸出檔名，預設 hpc_accounts_<時間>.<副檔名>')
    parser.add_argument('--format', choices=['csv', 'json'], default='csv', help='輸出格式，預設 csv')
    parser.add_argument('--year', help='只匯出這一年申請的（比對申請時間開頭，例如 2025）')
    parser.add_argument('--type', dest='account_type', choices=['course', 'formal', 'trial'],
                        help='只匯出某一種帳號類型')
    parser.add_argument('--search', help='關鍵字（申請人／團隊／帳號／聯絡人資訊），與網頁搜尋同義')
    parser.add_argument('--contacts-file',
                        help='另外輸出一份「一列一位聯絡人」的檔案（格式同 --format）')
    args = parser.parse_args()

    ext = 'json' if args.format == 'json' else 'csv'
    output = args.output or 'hpc_accounts_{}.{}'.format(datetime.now().strftime('%Y%m%d_%H%M%S'), ext)
    write = write_json if args.format == 'json' else write_csv

    app = create_app()
    with app.app_context():
        contacts = query_contacts(args.year, args.account_type, args.search)
        print('共取得 {} 筆帳號資料，整理中…'.format(len(contacts)))

        rows = []
        person_rows = []
        for contact in contacts:
            # to_dict() 會順帶算出剩餘額度與各種歷史紀錄，屬於逐筆查詢，資料多時會稍慢
            record = contact.to_dict()
            rows.append(build_row(contact, record))
            person_rows.extend(build_person_rows(record))

    if write(output, rows):
        print('已輸出 {} 筆帳號資料 -> {}'.format(len(rows), os.path.abspath(output)))

    if args.contacts_file and write(args.contacts_file, person_rows):
        print('已輸出 {} 位聯絡人 -> {}'.format(len(person_rows), os.path.abspath(args.contacts_file)))

    print('提醒：檔案內含測試帳號與課程學生密碼，請妥善保管。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
