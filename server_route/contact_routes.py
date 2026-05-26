from flask import Blueprint, request, jsonify, make_response
from database.extensions import db
from database.hpc_model import Contact, SecondaryContact, CourseStudent, ContactAccountMapping, UserAccounting
from sqlalchemy import or_, and_, func
import json
import csv
from io import StringIO, BytesIO

contact_bp = Blueprint('contact', __name__)

@contact_bp.route('/api/contacts', methods=['GET'])
def get_contacts():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    year = request.args.get('year', '')
    is_course = request.args.get('is_course', '').lower() == 'true'
    is_formal = request.args.get('is_formal', '').lower() == 'true'
    is_trial = request.args.get('is_trial', '').lower() == 'true'
    per_page = 10
    
    query = Contact.query.outerjoin(ContactAccountMapping).outerjoin(UserAccounting)
    filters = []

    if search:
       filters.append(or_(
            Contact.applicant.like(f'%{search}%'),
            Contact.team_name.like(f'%{search}%'),
            Contact.trial_account.like(f'%{search}%'),
            ContactAccountMapping.manual_account.like(f'%{search}%'),
            UserAccounting.username.like(f'%{search}%')
        ))

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
            Contact.is_course_account == False,      # 非課程帳號
            Contact.trial_account != None,           # 測試帳號欄位不為空
            Contact.trial_account != '',             # 測試帳號欄位不為空字串
            or_(
                # 情況 A: 完全沒有 Mapping 紀錄
                ContactAccountMapping.id == None,    
                # 情況 B: 有 Mapping 紀錄，但正式帳號 ID 與 手動紀錄皆為空
                and_(
                    ContactAccountMapping.user_accounting_id == None,
                    ContactAccountMapping.manual_account == None
                )
            )
        ))

    if type_filters:
        filters.append(or_(*type_filters))

    if year:
        filters.append(Contact.apply_date.like(f'{year}%'))

    if filters:
        query = query.filter(*filters)
    
    query = query.order_by(Contact.apply_date.desc())
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
        new_c.secondaries.append(SecondaryContact(name=sc['name'], info=sc['info']))

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
        contact.secondaries.append(SecondaryContact(name=sc['name'], info=sc['info']))

    CourseStudent.query.filter_by(contact_id=id).delete()
    for cs in data.get('course_students', []):
        contact.course_students.append(CourseStudent(
            student_account=cs.get('account'), 
            student_password=cs.get('password')
        ))
    
    db.session.commit()
    return jsonify({'success': True})

# --- 新增：一鍵匯出 CSV API ---
@contact_bp.route('/api/contacts/export', methods=['GET'])
def export_contacts():
    contacts = Contact.query.all()
    
    # 建立 CSV 內容
    output = StringIO()
    # 寫入 UTF-8 BOM 以防 Excel 開啟亂碼
    output.write(u'\ufeff')
    writer = csv.writer(output)
    
    # 標題列
    writer.writerow(['申請團隊', '一級單位', '申請人', '申請日期', '正式帳號', '帳號名稱', '使用主機', '測試期限', '其他聯絡人'])
    
    for c in contacts:
        hosts_str = ", ".join(json.loads(c.hosts or '[]'))
        sc_str = "; ".join([f"{s.name}({s.info})" for s in c.secondaries])
        writer.writerow([
            c.team_name, c.dept_level1, c.applicant, c.apply_date, 
            c.formal_account, c.account_name, hosts_str, c.test_deadline, sc_str
        ])
    
    response = make_response(output.getvalue())
    response.headers["Content-Disposition"] = "attachment; filename=contacts_export.csv"
    response.headers["Content-type"] = "text/csv; charset=utf-8"
    return response