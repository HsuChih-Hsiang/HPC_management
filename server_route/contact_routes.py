import json
import csv
from datetime import datetime
from io import StringIO, BytesIO
from sqlalchemy import or_, and_, func, cast, exists, Numeric
from flask import Blueprint, request, jsonify, make_response
from database.extensions import db
from database.hpc_model import (Contact, SecondaryContact, CourseStudent, ContactAccountMapping,
                                Serverlist, UserAccounting, Bill, Accounting, PrepaidAmount, HPCSetting,
                                EMAIL_PATTERN)
from utils.email_utils import (get_confirm_email_template_html, read_default_confirm_email_template,
                                CONFIRM_EMAIL_TEMPLATE_KEY, CONFIRM_EMAIL_DEFAULT_CC_KEY)

contact_bp = Blueprint('contact', __name__)

# 確認信範本設定用的 HPCSetting classification（沿用既有的 key-value 設定表，不另外開表）
CONFIRM_EMAIL_TEMPLATE_CLASSIFICATION = 3

def _parse_datetime_or_none(value):
    """把前端回傳的 'YYYY-MM-DD HH:MM:SS' 字串轉回 datetime，格式不對或空值一律回傳 None。"""
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError):
        return None

@contact_bp.route('/api/contacts', methods=['GET'])
def get_contacts():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    year = request.args.get('year', '')
    is_course = request.args.get('is_course', '').lower() == 'true'
    is_formal = request.args.get('is_formal', '').lower() == 'true'
    is_trial = request.args.get('is_trial', '').lower() == 'true'
    is_payment = request.args.get('is_payment', '').lower() == 'true'
    selected_hosts = request.args.get('hosts', '')  # 接收前端傳來的主機字串
    per_page = 10
    
    # 基本關聯查詢
    query = Contact.query\
        .outerjoin(ContactAccountMapping)\
        .outerjoin(UserAccounting)\
        .outerjoin(SecondaryContact)
        
    filters = []

    # 1. 搜尋功能 (包含次要聯絡人 info)
    if search:
        filters.append(or_(
            Contact.applicant.like(f'%{search}%'),
            Contact.team_name.like(f'%{search}%'),
            Contact.trial_account.like(f'%{search}%'),
            ContactAccountMapping.manual_account.like(f'%{search}%'),
            UserAccounting.username.like(f'%{search}%'),
            SecondaryContact.info.like(f'%{search}%')
        ))

    # 2. 帳號類型篩選 (課程、正式、測試)
    type_filters = []
    if is_course:
        type_filters.append(Contact.is_course_account == True)

    if is_formal:
        type_filters.append(and_(
            Contact.is_course_account == False,
            or_(
                ContactAccountMapping.user_accounting_id != None,
                ContactAccountMapping.manual_account != None
            )
        ))

    if is_trial:
        type_filters.append(and_(
            Contact.is_course_account == False,
            Contact.trial_account != None,
            Contact.trial_account != '',
            or_(
                ContactAccountMapping.id == None,
                and_(
                    ContactAccountMapping.user_accounting_id == None,
                    ContactAccountMapping.manual_account == None
                )
            )
        ))

    if type_filters:
        filters.append(or_(*type_filters))

    # 3. 申請年份篩選
    if year:
        filters.append(Contact.apply_date.like(f'{year}%'))

    # 4. 處理 is_payment 邏輯 (去年度應開立但未開立帳單)
    if is_payment:
        # 2026年執行時，last_year 會自動等於 2025
        last_year = datetime.now().year - 1
        start_of_last_year = datetime(last_year, 1, 1, 0, 0, 0)
        end_of_last_year = datetime(last_year, 12, 31, 23, 59, 59)

        # 條件 A：在 Accounting 表中有去年度的計算紀錄
        has_accounting_last_year = exists().where(
            and_(
                Accounting.username == UserAccounting.username,
                Accounting.begintime >= start_of_last_year,
                Accounting.begintime <= end_of_last_year
            )
        )
        filters.append(has_accounting_last_year)

        # 條件 B：在 Bill 表中完全沒有任何帳單紀錄
        has_no_bill = ~exists().where(Bill.contact_id == Contact.id)
        filters.append(has_no_bill)

    # 5. 修正：主機多選條件篩選
    if selected_hosts:
        host_list = [h.strip() for h in selected_hosts.split(',') if h.strip()]
        host_or_filters = []
        for h in host_list:
            # 關鍵點：將 JSON 欄位透過 cast 轉成 db.Text 再做模糊搜尋，避免 PostgreSQL 噴型態錯誤
            host_or_filters.append(cast(Contact.hosts, db.Text).like(f'%{h}%'))
        
        if host_or_filters:
            filters.append(or_(*host_or_filters))
            
    if filters:
        query = query.filter(*filters)
    
    # 加上 distinct 避免重複
    query = query.distinct().order_by(Contact.apply_date.desc())
    
    pagination = query.paginate(page=page, per_page=per_page)
    return jsonify({
        'records': [c.to_dict() for c in pagination.items],
        'total_pages': pagination.pages,
        'current_page': page
    })

@contact_bp.route('/api/contacts/years', methods=['GET'])
def get_contact_years():
    years_query = db.session.query(
        func.substr(Contact.apply_date, 1, 4).label('year')
    ).distinct().order_by(func.substr(Contact.apply_date, 1, 4).desc()).all()
    
    years = [y[0] for y in years_query if y[0]]
    
    return jsonify(years)
#8, 13, , 17, 24, 27, 35
@contact_bp.route('/api/contacts', methods=['POST'])
def add_contact():
    data = request.json
    new_c = Contact(
        team_name=data.get('team_name'),
        dept_level1=data.get('dept_level1'),
        applicant=data.get('applicant'),
        apply_date=data.get('apply_date'),
        trial_account=data.get('trial_account'),
        trail_account_password=data.get('trail_account_password'),
        test_deadline=data.get('test_deadline'),
        hosts=json.dumps(data.get('hosts', [])), 
        research_content=data.get('research_content'),
        used_software=data.get('used_software'),
        calc_resource=data.get('calc_resource'),
        notes=data.get('notes'),
        is_course_account=data.get('is_course_account', False)
    )

    formal_val = data.get('formal_account')
    if formal_val:
        mapping = ContactAccountMapping(contact=new_c)
        if isinstance(formal_val, int) or (isinstance(formal_val, str) and formal_val.isdigit()):
            mapping.user_accounting_id = int(formal_val)
        else:
            mapping.manual_account = str(formal_val)
        db.session.add(mapping)

    for sc in data.get('secondary_contacts', []):
        new_c.secondaries.append(SecondaryContact(
            name=sc.get('name', ''),
            info=sc.get('info', ''),
            is_primary=sc.get('is_primary', False),
            email_disabled=sc.get('email_disabled', False),
            email_toggled_at=_parse_datetime_or_none(sc.get('email_toggled_at'))
        ))

    for cs in data.get('course_students', []):
        new_c.course_students.append(CourseStudent(
            student_account=cs.get('account'), 
            student_password=cs.get('password')
        ))
    
    db.session.add(new_c)
    db.session.commit()
    return jsonify({'success': True})

@contact_bp.route('/api/contacts/<int:id>', methods=['DELETE'])
def delete_contact(id):
    c = Contact.query.get_or_404(id)
    db.session.delete(c)
    db.session.commit()
    return jsonify({'success': True})

@contact_bp.route('/api/contacts/<int:id>', methods=['GET'])
def get_contact(id):
    if request.method == 'GET':
        contact = Contact.query.get_or_404(id)
        return jsonify(contact.to_dict())
    
import json

@contact_bp.route('/api/contacts/hosts', methods=['GET'])
def get_all_hosts():
    # 只檢查是否為 NULL，移除資料庫端的空字串比較
    results = db.session.query(Contact.hosts).filter(
        Contact.hosts.isnot(None)
    ).all()
    
    unique_hosts = set()
    
    for row in results:
        host_data = row[0] 
        
        # 情況 A：如果 SQLAlchemy 自動幫你轉成 Python 的 list 或 dict 了
        if isinstance(host_data, (list, dict)):
            # 如果裡面放的是 ['hostA', 'hostB'] 這樣的字串陣列
            if isinstance(host_data, list):
                for item in host_data:
                    if isinstance(item, str) and item.strip():
                        unique_hosts.add(item.strip())
            continue
            
        # 情況 B：如果拿出來依然是字串 (可能是 JSON 字串或舊資料的逗號分隔字串)
        if isinstance(host_data, str):
            host_str = host_data.strip()
            if not host_str:
                continue
                
            # 嘗試解析是否為 JSON 字串
            try:
                parsed = json.loads(host_str)
                if isinstance(parsed, list):
                    for item in parsed:
                        if isinstance(item, str) and item.strip():
                            unique_hosts.add(item.strip())
                    continue
            except (json.JSONDecodeError, TypeError):
                # 如果解析失敗，代表它是傳統的 "host1, host2" 逗號分隔字串
                pass
            
            # 處理傳統逗號分隔文字
            items = [item.strip() for item in host_str.split(',') if item.strip()]
            unique_hosts.update(items)
        
    return jsonify(sorted(list(unique_hosts)))

@contact_bp.route('/api/contacts/<int:id>', methods=['PUT'])
def update_contact(id):
    data = request.json
    contact = Contact.query.get_or_404(id)
    contact.team_name = data.get('team_name')
    contact.dept_level1 = data.get('dept_level1')
    contact.applicant = data.get('applicant')
    contact.apply_date = data.get('apply_date')
    contact.trial_account = data.get('trial_account')
    contact.trail_account_password = data.get('trail_account_password')
    contact.test_deadline = data.get('test_deadline')
    contact.hosts = json.dumps(data.get('hosts', []))
    contact.research_content = data.get('research_content')
    contact.used_software = data.get('used_software')
    contact.calc_resource = data.get('calc_resource')
    contact.notes = data.get('notes')
    contact.is_course_account = data.get('is_course_account', False)

    formal_val = data.get('formal_account')
    if formal_val:
        if not contact.account_mapping:
            contact.account_mapping = ContactAccountMapping(contact_id=id)
        
        mapping = contact.account_mapping
        if isinstance(formal_val, int) or (isinstance(formal_val, str) and formal_val.isdigit()):
            mapping.user_accounting_id = int(formal_val)
            mapping.manual_account = None
        else:
            mapping.manual_account = str(formal_val)
            mapping.user_accounting_id = None
    else:
        if contact.account_mapping:
            db.session.delete(contact.account_mapping)
    
    SecondaryContact.query.filter_by(contact_id=id).delete()
    for sc in data.get('secondary_contacts', []):
        contact.secondaries.append(SecondaryContact(
            name=sc.get('name', ''),
            info=sc.get('info', ''),
            is_primary=sc.get('is_primary', False),
            # 這裡刪掉重建整批 SecondaryContact，email_disabled/email_toggled_at 若不從前端
            # 一起帶回來就會被重置成預設值，等於白關；前端送出表單時務必把這兩個欄位一起帶上。
            email_disabled=sc.get('email_disabled', False),
            email_toggled_at=_parse_datetime_or_none(sc.get('email_toggled_at'))
        ))

    CourseStudent.query.filter_by(contact_id=id).delete()
    for cs in data.get('course_students', []):
        contact.course_students.append(CourseStudent(
            student_account=cs.get('account'), 
            student_password=cs.get('password')
        ))
    
    db.session.commit()
    return jsonify({'success': True})

@contact_bp.route('/api/contacts/mail-accounts', methods=['GET'])
def search_mail_accounts():
    """
    給「寄送 HTML 電子郵件」頁面的「帳號新增」用：搜尋帳號並回傳該帳號底下所有聯絡人的 Email。

    收件人怎麼拆（to / cc）由前端依勾選狀況即時計算，這裡只負責把原始資料吐出來：
      - is_primary   ：主要聯絡人，前端會把他放收件人、其餘的放副本
      - email_disabled：已被關閉寄信的聯絡人，一律不可勾選（等同不寄給他）
    沒有任何可擷取 Email 的帳號不會出現在清單中，避免使用者選了一個空的帳號。
    """
    search = (request.args.get('search') or '').strip()
    limit = request.args.get('limit', 50, type=int)
    limit = max(1, min(limit, 200))

    query = Contact.query\
        .outerjoin(ContactAccountMapping)\
        .outerjoin(UserAccounting)\
        .outerjoin(SecondaryContact)

    if search:
        query = query.filter(or_(
            Contact.applicant.like(f'%{search}%'),
            Contact.team_name.like(f'%{search}%'),
            Contact.trial_account.like(f'%{search}%'),
            ContactAccountMapping.manual_account.like(f'%{search}%'),
            UserAccounting.username.like(f'%{search}%'),
            SecondaryContact.name.like(f'%{search}%'),
            SecondaryContact.info.like(f'%{search}%')
        ))

    contacts = query.distinct().order_by(Contact.apply_date.desc()).limit(limit).all()

    results = []
    for c in contacts:
        formal_account = c.get_formal_account()
        trial_account = (c.trial_account or '').strip()

        if formal_account:
            account, account_type = formal_account, '正式帳號'
        elif trial_account:
            account, account_type = trial_account, ('課程帳號' if c.is_course_account else '測試帳號')
        else:
            account, account_type = (c.team_name or c.applicant or f'#{c.id}'), '未配帳號'

        members = []
        seen = set()
        # 主要聯絡人排在最前面，方便使用者一眼看出這封信會寄給誰
        for sc in sorted(c.secondaries, key=lambda s: (not bool(s.is_primary), s.id or 0)):
            if not sc.info:
                continue
            match = EMAIL_PATTERN.search(sc.info)
            if not match:
                continue
            email = match.group(0)
            if email in seen:
                continue
            seen.add(email)
            members.append({
                'id': sc.id,
                'name': sc.name or '',
                'email': email,
                'is_primary': bool(sc.is_primary),
                'email_disabled': bool(sc.email_disabled)
            })

        if not members:
            continue

        results.append({
            'contact_id': c.id,
            'account': account,
            'account_type': account_type,
            'team_name': c.team_name or '',
            'applicant': c.applicant or '',
            'members': members
        })

    return jsonify(results)

@contact_bp.route('/api/contacts/secondary-contacts/<int:id>/toggle-email', methods=['POST'])
def toggle_secondary_contact_email(id):
    """開關「寄信給這個聯絡人」，並記錄這次切換的時間點。"""
    sc = SecondaryContact.query.get_or_404(id)
    sc.email_disabled = not sc.email_disabled
    sc.email_toggled_at = datetime.now()
    db.session.commit()

    return jsonify({
        'success': True,
        'id': sc.id,
        'email_disabled': sc.email_disabled,
        'email_toggled_at': sc.email_toggled_at.strftime('%Y-%m-%d %H:%M:%S'),
        'message': (f'已關閉寄送給「{sc.name or sc.info}」的信件' if sc.email_disabled
                    else f'已重新開啟寄送給「{sc.name or sc.info}」的信件')
    })

@contact_bp.route('/api/contacts/hpc-statistics', methods=['GET'])
def get_hpc_statistics():
    current_year = datetime.now().year
    years = [current_year, current_year - 1, current_year - 2]
    
    result = []
    
    for year in sorted(years, reverse=True):
        year_str = str(year)
        
        # 1. 訪談人數 (該年度 apply_date 開頭為該年份，且扣除課程帳號)
        interview_count = Contact.query.filter(
            Contact.apply_date.like(f"{year_str}%"),
            (Contact.is_course_account == False) | (Contact.is_course_account.is_(None))
        ).count()

        # 2. 測試人數 (有 apply_date 且 trial_account 不為空/Null)
        trial_count = Contact.query.filter(
            Contact.apply_date.like(f"{year_str}%"),
            Contact.trial_account.isnot(None),
            Contact.trial_account != ''
        ).count()
        
        # 3. 正式使用人數 (該年度 Contact 有綁定 ContactAccountMapping)
        formal_count = Contact.query.join(ContactAccountMapping).filter(
            Contact.apply_date.like(f"{year_str}%")
        ).count()

        # 4. 課程帳號數量 (is_course_account 為 True)
        course_count = Contact.query.filter(
            Contact.apply_date.like(f"{year_str}%"),
            Contact.is_course_account == True
        ).count()
        
        # 5. 預繳總額
        total_receivable = db.session.query(
            func.coalesce(func.sum(PrepaidAmount.amount), 0)
        ).filter(
            PrepaidAmount.year == year,
            PrepaidAmount.is_paid == True,      # 排除未繳費 (is_paid == False)
            PrepaidAmount.is_history == False   # 排除歷史紀錄 (is_history == True)
        ).scalar()
        
        # 6. 使用費總額 (採用你提供的計算式，依 endtime 歸屬年份)
        usage_query = db.session.query(
            func.sum((Accounting.cores * (cast(Accounting.wtime, Numeric) / 3600)) * Serverlist.price).label('total_price'),
            func.count(Accounting.jobid).label('job_count')
        ).join(
            # Serverlist 同一個 server 可能有多筆不同 queue 的價格，join 一定要帶上 queue，
            # 否則同一筆 job 會對到多筆價格造成金額被重複加總
            Serverlist, and_(Accounting.host == Serverlist.server, Accounting.queue == Serverlist.queue)
        ).filter(
            func.extract('year', Accounting.endtime) == year,
            or_(
                Accounting.username.notlike('gst%'),
                Accounting.username.is_(None)
            )
        ).first()

        total_price = usage_query.total_price if usage_query and usage_query.total_price is not None else 0
        
        result.append({
            "year": year,
            "interview_count": interview_count,
            "trial_count": trial_count,
            "formal_count": formal_count,
            "course_count": course_count,
            "total_receivable": round(float(total_receivable), 2),
            "usage_amount": round(float(total_price), 2)
        })
        
    return jsonify({
        "status": "success",
        "data": result
    })

@contact_bp.route('/api/contacts/confirm-email-template', methods=['GET'])
def get_confirm_email_template():
    # default=1 時忽略資料庫中已儲存的版本，直接回傳預設檔案內容
    # （提供「還原預設範本」用，例如自訂版本被編輯器改壞導致無法渲染時）
    if request.args.get('default') == '1':
        return jsonify({'html': read_default_confirm_email_template(), 'is_default': True})

    setting = HPCSetting.query.filter_by(key=CONFIRM_EMAIL_TEMPLATE_KEY).first()
    html = get_confirm_email_template_html()
    return jsonify({'html': html, 'is_default': not (setting and setting.value)})

@contact_bp.route('/api/contacts/confirm-email-template', methods=['POST'])
def save_confirm_email_template():
    data = request.get_json() or {}
    html = data.get('html')

    if not html or not html.strip():
        return jsonify({'success': False, 'message': '範本內容不能為空。'}), 400

    setting = HPCSetting.query.filter_by(key=CONFIRM_EMAIL_TEMPLATE_KEY).first()
    if setting:
        setting.value = html
    else:
        setting = HPCSetting(
            key=CONFIRM_EMAIL_TEMPLATE_KEY,
            value=html,
            description='確認信範本 (HTML，含 {{ }} 供 Python 端渲染)',
            classification=CONFIRM_EMAIL_TEMPLATE_CLASSIFICATION
        )
        db.session.add(setting)

    db.session.commit()
    return jsonify({'success': True, 'message': '確認信範本已成功儲存。'})

@contact_bp.route('/api/contacts/confirm-email-default-cc', methods=['GET'])
def get_confirm_email_default_cc():
    setting = HPCSetting.query.filter_by(key=CONFIRM_EMAIL_DEFAULT_CC_KEY).first()
    emails = []
    if setting and setting.value:
        try:
            emails = json.loads(setting.value)
        except (json.JSONDecodeError, TypeError):
            emails = []
    return jsonify({'emails': emails if isinstance(emails, list) else []})

@contact_bp.route('/api/contacts/confirm-email-default-cc', methods=['POST'])
def save_confirm_email_default_cc():
    data = request.get_json() or {}
    emails = data.get('emails', [])

    if not isinstance(emails, list):
        return jsonify({'success': False, 'message': '格式不正確。'}), 400

    cleaned = []
    seen = set()
    for raw in emails:
        if not isinstance(raw, str):
            continue
        email = raw.strip()
        if not email or email in seen:
            continue
        if not EMAIL_PATTERN.fullmatch(email):
            return jsonify({'success': False, 'message': f'「{email}」不是有效的 Email 格式。'}), 400
        seen.add(email)
        cleaned.append(email)

    setting = HPCSetting.query.filter_by(key=CONFIRM_EMAIL_DEFAULT_CC_KEY).first()
    value = json.dumps(cleaned)
    if setting:
        setting.value = value
    else:
        setting = HPCSetting(
            key=CONFIRM_EMAIL_DEFAULT_CC_KEY,
            value=value,
            description='確認信預設副本收件人清單 (JSON list)',
            classification=CONFIRM_EMAIL_TEMPLATE_CLASSIFICATION
        )
        db.session.add(setting)

    db.session.commit()
    return jsonify({'success': True, 'message': '預設副本人員已成功儲存。'})