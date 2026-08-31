import json
import re
from database.extensions import db
from datetime import datetime, date

EMAIL_PATTERN = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')

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

class QuotationItem(db.Model):
    """
    繳費單（報價單）的計算資源列設定 —— 對應 templates/quotation/hpc_quotation.html
    中「計算資源 / 收費係數 / 使用量（核心小時）/ 總價」那張表的每一列。

    機器未來會汰換、也會新增，所以報價單上要出現哪幾列不能寫死在 HTML 裡，
    改由「⚙️ 設定 → 繳費單格式設定」維護：

      label       報價單上顯示的名稱，例如「一般計算節點 i90 主機 (2024)」
      targets     這一列涵蓋哪些 Accounting 紀錄，JSON 格式：
                    [{"server": "i90", "queues": ["cpu", "gpu"]}, ...]
                  queues 留空陣列代表「該 server 底下的所有 queue」。
                  同一個 server 的不同 queue 可能單價不同，需要拆成不同列時，
                  就在 targets 裡各自指定 queue。
      coefficient 報價單「收費係數」欄要顯示的數字；留空 (None) 代表由
                  Serverlist.price 自動帶入（多個 queue 單價不一致時顯示「-」）。
                  ⚠️ 這只影響「顯示」，總價一律以 Serverlist 的實際單價計算，
                  避免有人改了這裡的顯示值就讓帳單金額跟著失真。
      sort_order  報價單上的列順序，數字小的排前面。
      is_active   取消勾選即不出現在報價單上（保留設定不必刪除）。
    """
    __tablename__ = 'quotation_items'

    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(255), nullable=False)
    targets = db.Column(db.Text, nullable=False, default='[]')
    coefficient = db.Column(db.Numeric(10, 4), nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    def get_targets(self):
        """把 targets 欄位解析成 [{'server': str, 'queues': [str, ...]}, ...]，格式壞掉時回傳空清單。"""
        raw = self.targets
        if isinstance(raw, list):
            parsed = raw
        else:
            try:
                parsed = json.loads(raw or '[]')
            except (json.JSONDecodeError, TypeError):
                return []

        if not isinstance(parsed, list):
            return []

        result = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            server = (item.get('server') or '').strip()
            if not server:
                continue
            queues = item.get('queues') or []
            if not isinstance(queues, list):
                queues = []
            result.append({
                'server': server,
                'queues': [str(q).strip() for q in queues if str(q).strip()]
            })
        return result

    def to_dict(self):
        return {
            'id': self.id,
            'label': self.label,
            'targets': self.get_targets(),
            'coefficient': float(self.coefficient) if self.coefficient is not None else None,
            'sort_order': self.sort_order,
            'is_active': bool(self.is_active)
        }

    def __repr__(self):
        return f'<QuotationItem {self.id} {self.label}>'


class BillingWorkflow(db.Model):
    """
    一個聯絡人在某個帳務年度的「開單流程進度」。

    畫面上那四顆按鈕是有先後順序的，而且重新整理網頁後仍要記得走到哪一步，
    所以進度不能只存在前端 scope，必須落地：

        寄送確認信
          └→ 額度扣款後開立繳費單  ／  開立繳費單   （兩者只能擇一）
                └→ 寄送繳費單

    bill_action   'deduct'（額度扣款後開單）或 'direct'（直接開單）；
                  只要其中一個做過，另一個就永遠不能再按。
    quotation_kind 寄送繳費單時選的種類：'normal'（一般帳單）或 'prepaid'（預繳帳單）。
    """
    __tablename__ = 'billing_workflows'

    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(db.Integer, db.ForeignKey('contacts.id'), nullable=False, index=True)
    year = db.Column(db.Integer, nullable=False, index=True)

    confirm_email_sent_at = db.Column(db.DateTime, nullable=True)
    bill_action = db.Column(db.String(20), nullable=True)
    bill_id = db.Column(db.Integer, db.ForeignKey('bills.id'), nullable=True)
    bill_created_at = db.Column(db.DateTime, nullable=True)
    quotation_sent_at = db.Column(db.DateTime, nullable=True)
    quotation_kind = db.Column(db.String(20), nullable=True)

    # 這一年度的帳單是否套用「帳單折扣」（⚙️ 系統設定 → 帳單折扣設定）。
    # 折扣與額度扣款互斥：一旦標記為使用折扣，本年度就不能再走
    # 「額度扣款後開立繳費單」。狀態必須落地，否則重新整理網頁後
    # 前端就忘了，後端也無從擋起（前端 disabled 只是提示）。
    discount_applied = db.Column(db.Boolean, nullable=False, default=False, server_default=db.text('false'))

    __table_args__ = (
        db.UniqueConstraint('contact_id', 'year', name='_contact_year_workflow_uc'),
    )

    def to_dict(self):
        def fmt(dt):
            return dt.strftime('%Y-%m-%d %H:%M:%S') if dt else None

        return {
            'contact_id': self.contact_id,
            'year': self.year,
            'confirm_email_sent': self.confirm_email_sent_at is not None,
            'confirm_email_sent_at': fmt(self.confirm_email_sent_at),
            'bill_action': self.bill_action,
            'bill_id': self.bill_id,
            'bill_created_at': fmt(self.bill_created_at),
            'quotation_sent': self.quotation_sent_at is not None,
            'quotation_sent_at': fmt(self.quotation_sent_at),
            'quotation_kind': self.quotation_kind,
            'discount_applied': bool(self.discount_applied)
        }

    def __repr__(self):
        return f'<BillingWorkflow contact={self.contact_id} year={self.year} action={self.bill_action}>'


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

    def get_confirm_email_recipients(self):
        """
        輔助函式：解析寄送確認信時的收件人 (to) 與副本 (cc) 名單。
        secondary_contacts.info 是自由文字欄位（可能是電話、Email 或其他備註），
        因此用簡單的 Email 正規表示式從內容中擷取。

        規則：
          - 若有標記「主要聯絡人」且能擷取到 Email，主要聯絡人為收件人，
            其餘聯絡人的 Email（若有）放入副本。
          - 若沒有主要聯絡人可用的 Email，則把所有找得到的 Email 一起放入收件人，副本為空。
          - 被關閉寄信 (email_disabled=True) 的聯絡人，無論是否為主要聯絡人一律跳過，
            視同「這個人沒有 Email」。
        找不到 Email 的聯絡人會被忽略；回傳的清單皆已去重。

        Returns:
            dict: {'to': [email, ...], 'cc': [email, ...]}
        """
        primary_email = None
        other_emails = []
        seen = set()

        for sc in self.secondaries:
            if sc.email_disabled:
                continue
            if not sc.info:
                continue
            match = EMAIL_PATTERN.search(sc.info)
            if not match:
                continue
            email = match.group(0)
            if email in seen:
                continue
            seen.add(email)
            if sc.is_primary and primary_email is None:
                primary_email = email
            else:
                other_emails.append(email)

        if primary_email:
            return {'to': [primary_email], 'cc': other_emails}
        return {'to': other_emails, 'cc': []}

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
            'secondary_contacts': [{
                'id': s.id,
                'name': s.name,
                'info': s.info,
                'is_primary': s.is_primary,
                'email_disabled': bool(s.email_disabled),
                'email_toggled_at': s.email_toggled_at.strftime('%Y-%m-%d %H:%M:%S') if s.email_toggled_at else None
            } for s in self.secondaries],
            
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
    email_disabled = db.Column(db.Boolean, nullable=False, default=False)
    email_toggled_at = db.Column(db.TIMESTAMP, nullable=True)

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
    
class PermissionGroup(db.Model):
    """
    權限群組。一個群組可被授予多項功能 (GroupPermission)，
    使用者則歸屬於某一個群組；未歸屬任何群組者視為「尚未開通」。
    """
    __tablename__ = 'permission_groups'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.String(255))
    # is_system=True 的群組（admin）不可刪除、也不可移除其權限，
    # 避免整個系統被改到沒有任何人能進入權限管理頁面而鎖死。
    is_system = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now)

    permissions = db.relationship(
        'GroupPermission', backref='group', cascade='all, delete-orphan', lazy=True
    )
    users = db.relationship('AdUser', backref='group', lazy=True)

    def feature_keys(self):
        """依群組自訂的排序回傳功能代碼，此順序即該群組成員的側邊欄順序。"""
        return [
            p.feature_key
            for p in sorted(self.permissions, key=lambda x: (x.sort_order, x.id))
        ]

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description or '',
            'is_system': bool(self.is_system),
            'features': self.feature_keys(),
            'user_count': len(self.users)
        }

    def __repr__(self):
        return f'<PermissionGroup {self.name}>'


class GroupPermission(db.Model):
    """群組被授予的單一功能；feature_key 對應 utils/permission_utils.py 的 FEATURES。"""
    __tablename__ = 'group_permissions'

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('permission_groups.id'), nullable=False)
    feature_key = db.Column(db.String(50), nullable=False)
    # 側邊欄顯示順序，數字小的排前面；由權限管理頁面拖動排序後寫入
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    __table_args__ = (
        db.UniqueConstraint('group_id', 'feature_key', name='_group_feature_uc'),
    )

    def __repr__(self):
        return f'<GroupPermission group={self.group_id} feature={self.feature_key}>'


class AdUser(db.Model):
    """登入使用者（Google OAuth），由 login_routes.py 建立與查詢。"""
    __tablename__ = 'ad_user'

    id = db.Column(db.Integer, primary_key=True)
    google_id = db.Column(db.String(128), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(100))
    # 使用者自行填寫的聯絡信箱，與上面的 Google 登入帳號無關。
    # email 欄位只用來辨識身分（且有 unique 限制），要實際聯絡本人請用這個欄位。
    contact_email = db.Column(db.String(120))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # 未指派群組 (NULL) = 等待管理員開通權限，登入後只會看到等候頁面
    group_id = db.Column(db.Integer, db.ForeignKey('permission_groups.id'), nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'name': self.name or '',
            'contact_email': self.contact_email or '',
            'group_id': self.group_id,
            'group_name': self.group.name if self.group else None,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else ''
        }

    def __repr__(self):
        return f'<AdUser {self.email}>'

def init_db(app):
    db.init_app(app)
    with app.app_context():
        db.create_all()