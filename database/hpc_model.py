import json
from database.extensions import db
from datetime import datetime, date
from cryptography.fernet import Fernet

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
    username = db.Column(db.String(80), nullable=False)
    amount = db.Column(db.Float(precision=53), nullable=False, default=0.0)
    discount = db.Column(db.Float(precision=53), nullable=False, default=0.0)
    year = db.Column(db.Integer, nullable=True)
    payment_date = db.Column(db.DateTime, nullable=True)
    is_paid = db.Column(db.Boolean, default=False, nullable=False)
    is_history = db.Column(db.Boolean, default=False, nullable=False)
    source_id = db.Column(db.String(100), nullable=False)

    # 注意：因為現在要允許一個 username 有多個年份的紀錄，
    # 必須將原本的唯一索引 (unique=True) 拔除，改為 username + year 的聯合唯一索引
    __table_args__ = (
        db.Index('ix_prepaid_amounts_username_year', username, year, unique=False),
        db.Index('ix_prepaid_amounts_source_id', source_id, unique=False),
    )

    def __repr__(self):
        return f'<PrepaidAmount (id={self.id}, username={self.username}, year={self.year}, amount=${self.amount})>'
    
class Bill(db.Model):
    __tablename__ = 'bills'

    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(db.Integer, db.ForeignKey('contacts.id'))
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='unpaid') # unpaid, paid, cancelled
    created_at = db.Column(db.DateTime, default=datetime.now)
    notes = db.Column(db.String(255))

    def __repr__(self):
        return f"<Bill(id={self.id}, contact_id={self.contact_id}, amount={self.amount}, status='{self.status}')>"
    
class QuotaTransaction(db.Model):
    __tablename__ = 'quota_transactions'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False, index=True)
    bill_id = db.Column(db.Integer, db.ForeignKey('bills.id'), nullable=True)
    prepaid_id = db.Column(db.Integer, db.ForeignKey('prepaid_amounts.id'), nullable=True)
    
    # 異動類型：'charge' (管理員儲值), 'bonus' (學術獎勵), 'deduct' (帳單扣款), 'refund' (退款)
    tx_type = db.Column(db.String(20), nullable=False)
    amount_changed = db.Column(db.Float, default=0.0, nullable=False)
    discount_changed = db.Column(db.Float, default=0.0, nullable=False)
    description = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    def __repr__(self):
        return f"<QuotaTransaction(id={self.id}, username='{self.username}', type='{self.tx_type}', bill={self.bill_id})>"

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
    classification = db.Column(db.Integer, nullable=False)

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
    used_software = db.Column(db.String(1000))
    calc_resource = db.Column(db.String(1000))
    notes = db.Column(db.Text)
    contact_info = db.Column(db.Text)
    is_course_account = db.Column(db.Boolean, default=False)
    
    # 關聯
    secondaries = db.relationship('SecondaryContact', backref='main', cascade="all, delete-orphan")
    course_students = db.relationship('CourseStudent', backref='main_contact', cascade="all, delete-orphan")
    account_mapping = db.relationship('ContactAccountMapping', backref='contact', uselist=False, cascade="all, delete-orphan")
    bills = db.relationship('Bill', backref='contact', cascade="all, delete-orphan")

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

        total_remaining = 0.0          # 所有可用年份的總剩餘額度累加（自費 + 優惠）
        discount_remaining = 0.0       # 所有「未過期」年份的可用【優惠額度】累加
        discount_details = []          # 按年份拆解的儲值明細陣列（僅包含用於計算的活耀額度）
        consumption_history = []       # 🌟 真正對應 QuotaTransaction 的流水帳歷史紀錄
        recharge_history = []          # 僅包含歷史存檔 (is_history=True) 的完整清單
        bills_data = []                # 🌟 新增：真正對應 Bill 表的繳費單明細紀錄

        if formal_account:
            # 1. 撈出該帳號所有的儲值紀錄（由舊到新排序）
            prepaids = PrepaidAmount.query.filter_by(username=formal_account).order_by(PrepaidAmount.year.asc()).all()
            today_str = date.today().isoformat()

            yearly_data = {}
            for p in prepaids:
                is_p_paid = getattr(p, 'is_paid', False)
                is_p_history = getattr(p, 'is_history', False)

                # 修正點 1：只將真正的歷史資料 (is_history=True) 塞入「儲值歷史紀錄」
                if is_p_history:
                    recharge_history.append({
                        'id': p.id,
                        'year': p.year if p.year is not None else 0,
                        'amount': round(float(p.amount or 0), 2),
                        'discount': round(float(p.discount or 0), 2),
                        'payment_date': p.payment_date.strftime('%Y-%m-%d') if p.payment_date else '',
                        'is_paid': is_p_paid,
                        'is_history': True,
                        'source_id': getattr(p, 'source_id', '')
                    })
                
                # 修正點 2：非歷史資料 (is_history=False) 走這裏，且只有「已付款」才納入活躍額度基算
                else:
                    if is_p_paid:
                        y = p.year if p.year is not None else 0
                        if y not in yearly_data:
                            yearly_data[y] = {'purchase': 0.0, 'discount': 0.0}
                        
                        yearly_data[y]['purchase'] += float(p.amount or 0)
                        yearly_data[y]['discount'] += float(p.discount or 0)

            # 將歸戶後的活耀年份資料依序處理
            for y, v in sorted(yearly_data.items()):
                expire_year = y + 2
                expire_date_str = f"{expire_year}-12-31"
                is_expired = today_str > expire_date_str
                
                # 該活耀年份的剩餘總額 = 實付剩餘 + 優惠剩餘
                year_total = v['purchase'] + v['discount']
                
                total_remaining += year_total
                
                # 核心修正點：如果是未過期年份，改為「只累加優惠額度 (discount)」而非總額 (year_total)
                if not is_expired:
                    discount_remaining += v['discount']

                discount_details.append({
                    'purchase_year': y,
                    'total_amount': round(year_total, 2),        
                    'purchase_amount': round(v['purchase'], 2),   
                    'discount_amount': round(v['discount'], 2),   
                    'expire_date': expire_date_str,
                    'is_expired': is_expired
                })

            # 將儲值歷史紀錄按照日期由新到舊排序
            recharge_history.sort(key=lambda x: x['payment_date'] or '', reverse=True)

            # 🌟 修正點 3：從資料庫撈出該正式帳號真正的 QuotaTransaction 流水帳，給前端 【A-3】 渲染
            txs = QuotaTransaction.query.filter_by(username=formal_account).order_by(QuotaTransaction.created_at.desc()).all()
            for tx in txs:
                consumption_history.append({
                    'id': tx.id,
                    'tx_type': tx.tx_type,  # 'deduct', 'charge', 'bonus', 'refund'
                    'amount_changed': round(float(tx.amount_changed or 0), 2),
                    'discount_changed': round(float(tx.discount_changed or 0), 2),
                    'description': tx.description or '',
                    'bill_id': tx.bill_id,
                    'created_at': tx.created_at.strftime('%Y-%m-%d %H:%M:%S') if tx.created_at else ''
                })

        # 🌟 修正點 4：整合 Bill 表的邏輯，獨立打包成 bills_data 給前端 【A-4】 表格渲染
        for b in self.bills:
            if b.status != 'cancelled':
                bills_data.append({
                    'id': b.id,
                    'amount': round(float(b.amount or 0), 2),
                    'created_at': b.created_at.strftime('%Y-%m-%d') if b.created_at else '',
                    'notes': b.notes or '',
                    'status': b.status  # 'paid', 'unpaid'
                })
        
        # 繳費單按開單日期由新到舊排序
        bills_data.sort(key=lambda x: x['created_at'], reverse=True)

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
            'secondary_contacts': [{'name': s.name, 'info': s.info, 'is_primary': s.is_primary} for s in self.secondaries],
            
            # 核心數據分流輸出結果
            'total_remaining': round(total_remaining, 2),          
            'discount_remaining': round(discount_remaining, 2),    
            'discount_details': discount_details,                  
            'recharge_history': recharge_history,                  
            'consumption_history': consumption_history,            # 🌟 現在這裡裝的是正確的 QuotaTransaction 清單了！
            'bills': bills_data                                    # 🌟 新增：完美對應前端 【A-4】 billsTableBody
        }

class SecondaryContact(db.Model):
    __tablename__ = 'secondary_contacts'
    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(db.Integer, db.ForeignKey('contacts.id'))
    name = db.Column(db.String(100))
    info = db.Column(db.String(255))
    is_primary = db.Column(db.Boolean, default=False, nullable=True)

    def __repr__(self):
        status = "Primary" if self.is_primary else "Secondary"
        return f"<SecondaryContact {self.id} ({self.name or '未命名'}, {status})>"

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

    def __repr__(self):
        acc_info = f"SystemID:{self.user_accounting_id}" if self.user_accounting_id else f"Manual:'{self.manual_account}'"
        return f"<ContactAccountMapping {self.id} (ContactID:{self.contact_id} -> {acc_info})>"
    
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
    
class AdUser(db.Model):
    __tablename__ = 'ad_user'
    
    id = db.Column(db.Integer, primary_key=True)
    google_id = db.Column(db.String(128), unique=True, nullable=False) 
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(100))
    smtp_encrypted_token = db.Column(db.LargeBinary, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<AdUser {self.email}>'
    
    def set_smtp_config(self, config_dict, secret_key):
        """將 dict 加密並存入資料庫"""
        f = Fernet(secret_key)
        json_data = json.dumps(config_dict).encode('utf-8')
        self.smtp_encrypted_token = f.encrypt(json_data)

    def get_smtp_config(self, secret_key):
        """從資料庫取出並解密回 dict"""
        if not self.smtp_encrypted_token:
            return None
        f = Fernet(secret_key)
        decrypted_data = f.decrypt(self.smtp_encrypted_token)
        return json.loads(decrypted_data.decode('utf-8'))

def init_db(app):
    db.init_app(app)
    with app.app_context():
        db.create_all()