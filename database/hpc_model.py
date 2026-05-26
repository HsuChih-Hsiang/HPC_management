import json
from database.extensions import db
from datetime import datetime, date

class Accounting(db.Model):
    __tablename__ = 'accounting'
    jobid = db.Column(db.Text, primary_key=True)
    host = db.Column(db.Text)
    username = db.Column(db.Text)
    jobname = db.Column(db.Text)
    queue = db.Column(db.Text)
    begintime = db.Column(db.TIMESTAMP)
    endtime = db.Column(db.TIMESTAMP)
    status = db.Column(db.Integer)
    mem = db.Column(db.BigInteger)
    cores = db.Column(db.Integer)
    wtime = db.Column(db.Integer)
    gpu = db.Column(db.Integer)
    filename = db.Column(db.Text)
    inserttime = db.Column(db.TIMESTAMP)

class Serverlist(db.Model):
    __tablename__ = 'serverlist'
    id = db.Column(db.Integer, primary_key=True)
    server = db.Column(db.Text)
    queue = db.Column(db.Text)
    price = db.Column(db.Numeric(10, 2))
    type = db.Column(db.Text)
    update_time = db.Column(db.TIMESTAMP)
    status = db.Column(db.Boolean)
    year = db.Column(db.Integer)

class UserList(db.Model):
    __tablename__ = 'userlist'

    id = db.Column(db.Integer, primary_key=True, autoincrement=False)
    username = db.Column(db.Text, nullable=True)
    name = db.Column(db.Text, nullable=True)
    department = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f'<UserList {self.username} ({self.name})>'

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "name": self.name,
            "department": self.department
        }

class PrepaidAmount(db.Model):
    __tablename__ = 'prepaid_amounts'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False) 
    amount = db.Column(db.Float(precision=53), nullable=False, default=0.0) 
    year = db.Column(db.Integer, nullable=True)                      # 儲值所屬年份
    payment_date = db.Column(db.DateTime, nullable=True)

    # 💡 注意：因為現在要允許一個 username 有多個年份的紀錄，
    # 必須將原本的唯一索引 (unique=True) 拔除，改為 username + year 的聯合唯一索引
    __table_args__ = (
        db.Index('ix_prepaid_amounts_username_year', username, year, unique=True),
    )

    def __repr__(self):
        return f'<PrepaidAmount (id={self.id}, username={self.username}, year={self.year}, amount=${self.amount})>'

class NotificationHistory(db.Model):
    __tablename__ = 'notification_history'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False, index=True)
    notification_type = db.Column(db.Integer, nullable=False) # e.g., 0: 'prepaid', 1: 'threshold', 2: 'growth'
    notified_at = db.Column(db.DateTime, default=datetime.now())
    year = db.Column(db.Integer, nullable=False, index=True)
    message = db.Column(db.Text, nullable=True) 
    amount = db.Column(db.Float, nullable=True)

    def __repr__(self):
        return f'<NotificationHistory {self.username} - {self.notification_type} on {self.notified_at}>'

class HPCSetting(db.Model):
    __tablename__ = 'hpc_settings'

    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text)

    def __repr__(self):
        return f'<HPCSetting (key={self.key}, value={self.value})>'

class MailboxGroup(db.Model):
    __tablename__ = 'mailbox_groups'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    owner_username = db.Column(db.String(80), nullable=False, index=True)
    emails = db.relationship('MailboxEmail', backref='group', cascade="all, delete-orphan", lazy=True)

    __table_args__ = (
        db.UniqueConstraint('name', 'owner_username', name='_user_group_uc'),
    )

    def __repr__(self):
        return f'<MailboxGroup {self.name} (Owner: {self.owner_username})>'

class MailboxEmail(db.Model):
    __tablename__ = 'mailbox_emails'
    
    id = db.Column(db.Integer, primary_key=True)
    email_address = db.Column(db.String(255), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey('mailbox_groups.id'), nullable=False)

    def __repr__(self):
        return f'<MailboxEmail {self.email_address}>'
    
class EmailTemplate(db.Model):
    __tablename__ = 'email_templates'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    subject = db.Column(db.String(255))
    html = db.Column(db.Text, nullable=False)
    owner_username = db.Column(db.String(80), nullable=False, index=True)

    __table_args__ = (
        db.UniqueConstraint('name', 'owner_username', name='_user_template_uc'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'subject': self.subject,
            'html': self.html
        }

    def __repr__(self):
        return f'<EmailTemplate {self.name} (Owner: {self.owner_username})>'
    
class Contact(db.Model):
    __tablename__ = 'contacts'
    id = db.Column(db.Integer, primary_key=True)
    team_name = db.Column(db.String(100)) 
    dept_level1 = db.Column(db.String(100))
    applicant = db.Column(db.String(100))
    apply_date = db.Column(db.String(20))
    trial_account = db.Column(db.String(100)) 
    trail_account_password = db.Column(db.String(100))
    hosts = db.Column(db.Text)                
    test_deadline = db.Column(db.String(20)) 
    research_content = db.Column(db.Text)
    used_software = db.Column(db.String(255))
    calc_resource = db.Column(db.String(255))
    notes = db.Column(db.Text)
    contact_info = db.Column(db.Text)
    is_course_account = db.Column(db.Boolean, default=False)
    
    # 關聯
    secondaries = db.relationship('SecondaryContact', backref='main', cascade="all, delete-orphan")
    course_students = db.relationship('CourseStudent', backref='main_contact', cascade="all, delete-orphan")
    account_mapping = db.relationship('ContactAccountMapping', backref='contact', uselist=False, cascade="all, delete-orphan")

    def get_formal_account(self):
        """輔助函式：動態取得此聯絡人的正式帳號"""
        if self.account_mapping:
            if self.account_mapping.user_accounting:
                return self.account_mapping.user_accounting.username
            elif self.account_mapping.manual_account:
                return self.account_mapping.manual_account
        return ""

    def to_dict(self):
        formal_account = self.get_formal_account()

        total_remaining = 0.0          # 所有可用年份的總剩餘額度累加
        discount_remaining = 0.0       # 所有「未過期」年份的可用總額度累加
        discount_details = []          # 按年份拆解的儲值明細陣列
        consumption_history = []       # 結合原本 Accounting 的消費扣款紀錄

        if formal_account:
            # 1. 撈出該帳號所有的儲值紀錄（實進實出，此時的 amount 是扣掉消費後的餘額）
            prepaids = PrepaidAmount.query.filter_by(username=formal_account).order_by(PrepaidAmount.year.asc()).all()
            today_str = date.today().isoformat()

            for p in prepaids:
                # 依據 p.year 推算該年額度的固定截止日
                expire_year = p.year + 2
                expire_date_str = f"{expire_year}-01-31"
                is_expired = today_str > expire_date_str
                
                # 動態反推該年份「目前剩餘」的自費與優惠 (按 1:0.2 比例，優惠佔總額 1/6)
                discount_amt = round(p.amount * (0.20 / 1.20), 2)
                purchase_amt = round(p.amount - discount_amt, 2)
                
                total_remaining += p.amount
                if not is_expired:
                    discount_remaining += p.amount

                discount_details.append({
                    'purchase_year': p.year,
                    'total_amount': round(p.amount, 2),        # 該年目前剩餘總額度
                    'purchase_amount': purchase_amt,           # 該年目前剩餘購買額度
                    'discount_amount': discount_amt,           # 該年目前剩餘優惠額度
                    'expire_date': expire_date_str,
                    'is_expired': is_expired
                })

            # 2. 💡 活用現有資料：從 Accounting 撈出該使用者的歷史計算紀錄，作為消費日期與消費額度參考
            # 此處假設你已有計算好的帳單。若有獨立的 Bill 表更好；若無，可透過 Accounting 動態加總或撈取月結單
            # 以下示範：捞取該使用者在 Accounting 的工作紀錄（按月份或日期排序），提供管理員對帳
            # 實務上通常會配合一個「已出帳扣款」的紀錄欄位，這裡回傳格式供前端直接渲染：
            from database.extensions import db
            from sqlalchemy import text
            
            # 這裡提供一個標準對帳結構，可根據你實際的出帳規則（如按月、按件）取得消費日期與金額
            # 範例：從資料庫查詢該帳號的扣款日誌或歷史工作花費
            # consumption_history 格式：{'amount': 500, 'bill_date': '2026-04-30', 'notes': '2026年04月 Hpc 運算扣款'}
            
        return {
            'id': self.id,
            'team_name': self.team_name,
            'dept_level1': self.dept_level1,
            'applicant': self.applicant,
            'apply_date': self.apply_date,
            'formal_account': formal_account,
            'trial_account': self.trial_account,
            'trail_account_password': self.trail_account_password,
            'hosts': json.loads(self.hosts or '[]') if isinstance(self.hosts, str) else (self.hosts or []),
            'test_deadline': self.test_deadline,
            'contact_info': self.contact_info,
            'research_content': self.research_content,
            'used_software': self.used_software,
            'calc_resource': self.calc_resource,
            'notes': self.notes,
            'is_course_account': self.is_course_account,
            'course_students': [{'account': s.student_account, 'password': s.student_password} for s in self.course_students],
            'secondary_contacts': [{'name': s.name, 'info': s.info} for s in self.secondaries],
            
            # 核心額度資料
            'total_remaining': round(total_remaining, 2),          # 實質剩餘總計
            'discount_remaining': round(discount_remaining, 2),    # 目前可用額度總計（排除過期）
            'discount_details': discount_details,                  # 按年份列出的自費、優惠、總額
            'consumption_history': consumption_history             # 歷史消費與日期明細
        }

class SecondaryContact(db.Model):
    __tablename__ = 'secondary_contacts'
    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(db.Integer, db.ForeignKey('contacts.id'))
    name = db.Column(db.String(100))
    info = db.Column(db.String(255))

class CourseStudent(db.Model):
    __tablename__ = 'course_students'
    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(db.Integer, db.ForeignKey('contacts.id')) # 關聯到 Contact 表
    student_account = db.Column(db.String(100))
    student_password = db.Column(db.String(100))

    def __repr__(self):
        return f'<CourseStudent {self.student_account}>'
    
class ContactAccountMapping(db.Model):
    __tablename__ = 'contact_account_mapping'
    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(db.Integer, db.ForeignKey('contacts.id'), nullable=False)
    user_accounting_id = db.Column(db.Integer, db.ForeignKey('user_accounting.id'), nullable=True)
    manual_account = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=db.func.now())

    # 關聯到 UserAccounting 模型
    user_accounting = db.relationship('UserAccounting', backref='contact_mappings')
    
class UserAccounting(db.Model):
    __tablename__ = 'user_accounting'

    id = db.Column(
        db.Integer, 
        db.Sequence('annual_report_id_seq'), 
        primary_key=True, 
        autoincrement=True
    )
    
    username = db.Column(db.Text, nullable=False, unique=True)

    def __init__(self, username):
        self.username = username

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username
        }

def init_db(app):
    db.init_app(app)
    with app.app_context():
        db.create_all()