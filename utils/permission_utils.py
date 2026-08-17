"""
權限控管

概念：
  功能 (feature)  ── 對應側邊欄的一個項目，例如 hpc_usage
  群組 (group)    ── 一組功能的集合，例如 admin
  使用者          ── 歸屬於一個群組；未歸屬者 = 尚未開通，只能看到等候頁面

保護範圍同時涵蓋「頁面」與「API」：
  - 頁面：沒有權限就不會出現在側邊欄，直接打網址也會被擋
  - API ：以 endpoint 對應到所需功能，沒有權限一律回 403

擋人的實作在 app.py 的 before_request，統一入口避免有漏網之魚。
"""

from sqlalchemy import inspect
from database.extensions import db
from database.hpc_model import AdUser, PermissionGroup, GroupPermission

ADMIN_GROUP_NAME = 'admin'

# ============================================================
# 功能清單（順序即側邊欄顯示順序）
# 新增頁面時在這裡加一筆，並補上底下的 endpoint 對應。
# ============================================================
FEATURES = [
    {'key': 'batch_sending',   'label': '寄送郵件',     'icon': '📨', 'path': '/batch_sending'},
    {'key': 'edit_templates',  'label': '編輯模板',     'icon': '📝', 'path': '/edit-templates'},
    {'key': 'mailbox_manager', 'label': '信箱管理',     'icon': '📬', 'path': '/mailbox-manager'},
    {'key': 'hpc_contact',     'label': 'HPC帳號管理',  'icon': '👥', 'path': '/hpc-contact'},
    {'key': 'hpc_usage',       'label': 'HPC 用量通知', 'icon': '📊', 'path': '/hpc-usage'},
    {'key': 'setting',         'label': '設定',         'icon': '⚙️', 'path': '/setting'},
    {'key': 'permission',      'label': '權限管理',     'icon': '🔑', 'path': '/permission'},
]

ALL_FEATURE_KEYS = [f['key'] for f in FEATURES]
FEATURE_BY_KEY = {f['key']: f for f in FEATURES}

# 不需要任何權限就能存取的 endpoint（登入流程、等候頁面、登出）
PUBLIC_ENDPOINTS = {
    'static',
    'routes.login_page',
    'routes.pending_approval',
    'login.login',
    'login.callback',
    'login.logout',
    'login.check_session',
    'permission.get_my_permissions',
}

# 頁面 endpoint → 所需功能
PAGE_FEATURE_MAP = {
    'routes.batch_sending':   'batch_sending',
    'routes.edit_templates':  'edit_templates',
    'routes.mailbox_manager': 'mailbox_manager',
    'routes.hpc_contact':     'hpc_contact',
    'routes.hpc_usage':       'hpc_usage',
    'routes.setting':         'setting',
    'routes.permission':      'permission',
}

# Blueprint → 預設所需功能。
# 用 blueprint 當預設值的好處是：日後在既有 blueprint 新增 API，
# 會自動被納入保護，而不是預設全開。
BLUEPRINT_FEATURE_MAP = {
    'email':      'batch_sending',
    'template':   'edit_templates',
    'mailbox':    'mailbox_manager',
    'contact':    'hpc_contact',
    'quota':      'hpc_contact',
    'hpc':        'hpc_usage',
    'setting':    'setting',
    'permission': 'permission',
}

# 跨頁面共用的 API：除了 blueprint 預設值之外，額外允許的功能。
# 例如「寄送郵件」頁面需要讀取信箱與模板清單，但不應因此獲得
# 信箱管理／模板編輯的修改權限，所以多數只開放 GET。
ENDPOINT_EXTRA_FEATURES = {
    # 寄送郵件頁：讀取收件信箱分組、讀取郵件模板
    'mailbox.get_mailboxes':                  {'features': {'batch_sending'},  'methods': {'GET'}},
    'template.handle_templates':              {'features': {'batch_sending'},  'methods': {'GET'}},
    # HPC 用量通知頁的「確認信預設副本人員」設定，與帳號管理頁共用同一份設定
    'contact.get_confirm_email_default_cc':   {'features': {'hpc_usage'},      'methods': None},
    'contact.save_confirm_email_default_cc':  {'features': {'hpc_usage'},      'methods': None},
    # HPC 帳號管理頁需要主機清單、帳號搜尋與額度設定
    'hpc.search_users':                       {'features': {'hpc_contact'},    'methods': {'GET'}},
    'hpc.get_server_list':                    {'features': {'hpc_contact'},    'methods': {'GET'}},
    'hpc.hpc_quota_settings':                 {'features': {'hpc_contact'},    'methods': None},
}


def get_required_features(endpoint, method='GET'):
    """
    回傳存取此 endpoint 所需的功能集合（其中任一項有權限即可通過）。
    回傳空集合代表此 endpoint 不需權限。
    """
    if not endpoint or endpoint in PUBLIC_ENDPOINTS:
        return set()

    required = set()

    if endpoint in PAGE_FEATURE_MAP:
        required.add(PAGE_FEATURE_MAP[endpoint])

    blueprint = endpoint.split('.')[0]
    if blueprint in BLUEPRINT_FEATURE_MAP:
        required.add(BLUEPRINT_FEATURE_MAP[blueprint])

    extra = ENDPOINT_EXTRA_FEATURES.get(endpoint)
    if extra:
        allowed_methods = extra['methods']
        if allowed_methods is None or method in allowed_methods:
            required |= extra['features']

    return required


def get_user_ordered_features(user_id):
    """
    取得該使用者所屬群組被授予的功能代碼，並依群組自訂的排序回傳。
    未指派群組回傳空清單。
    回傳 list（有順序）而非 set，因為側邊欄要照這個順序顯示。
    """
    if not user_id:
        return []

    user = db.session.get(AdUser, user_id)
    if not user or not user.group_id:
        return []

    rows = GroupPermission.query.filter_by(group_id=user.group_id).order_by(
        GroupPermission.sort_order.asc(), GroupPermission.id.asc()
    ).all()
    return [r.feature_key for r in rows]


def get_user_features(user_id):
    """權限檢查用：回傳功能代碼的集合（不含順序）。"""
    return set(get_user_ordered_features(user_id))


def get_sidebar_features(feature_keys):
    """
    回傳要顯示在側邊欄的項目。
    傳入 list 時依照該順序排列（群組自訂順序）；
    傳入 set 等無序容器時，退回 FEATURES 的預設順序。
    """
    if isinstance(feature_keys, (list, tuple)):
        return [FEATURE_BY_KEY[k] for k in feature_keys if k in FEATURE_BY_KEY]

    return [f for f in FEATURES if f['key'] in feature_keys]


def get_landing_path(feature_keys):
    """
    決定登入後要導向哪一頁：取該使用者側邊欄的第一個功能。
    完全沒有權限則導向等候開通頁面。
    不能寫死導向 /batch_sending，否則沒有「寄送郵件」權限的使用者
    一登入就會撞上 403。
    """
    available = get_sidebar_features(feature_keys)
    if not available:
        return '/pending-approval'
    return available[0]['path']


def init_permission_groups(app):
    """
    系統啟動時確保 admin 群組存在、且擁有全部功能。

    另外做一次防鎖死保護：若目前沒有任何使用者屬於 admin 群組，
    就把現有的使用者全部指派為 admin。這是為了避免權限功能上線後，
    既有帳號因為 group_id 是 NULL 而全部被擋在門外、
    連權限管理頁面都進不去，形成無人可解的死鎖。
    """
    with app.app_context():
        # 這兩張表需要手動建立（專案沒有使用 migration 工具，也沒有呼叫 db.create_all()）。
        # 若尚未建立就直接查詢，SQLAlchemy 會丟出不易理解的 ProgrammingError，
        # 因此先檢查並給出明確的指示。
        inspector = inspect(db.engine)
        existing_tables = set(inspector.get_table_names())
        missing = {'permission_groups', 'group_permissions'} - existing_tables
        if missing:
            print('=' * 70)
            print(f"[權限管理] 缺少資料表: {', '.join(sorted(missing))}")
            print("請先執行 sql/20260817_add_permission_tables.sql 建立資料表後再啟動服務。")
            print('=' * 70)
            return

        if 'group_id' not in {c['name'] for c in inspector.get_columns('ad_user')}:
            print('=' * 70)
            print("[權限管理] ad_user 缺少 group_id 欄位，")
            print("請先執行 sql/20260817_add_permission_tables.sql 後再啟動服務。")
            print('=' * 70)
            return

        if 'sort_order' not in {c['name'] for c in inspector.get_columns('group_permissions')}:
            print('=' * 70)
            print("[權限管理] group_permissions 缺少 sort_order 欄位（側邊欄排序功能所需）。")
            print("請先執行 sql/20260817_02_add_feature_sort_order.sql 後再啟動服務。")
            print('=' * 70)
            return

        admin = PermissionGroup.query.filter_by(name=ADMIN_GROUP_NAME).first()
        if not admin:
            admin = PermissionGroup(
                name=ADMIN_GROUP_NAME,
                description='系統管理員，擁有全部功能權限',
                is_system=True
            )
            db.session.add(admin)
            db.session.flush()
            print("已建立預設 admin 權限群組。")

        # admin 一律補齊所有功能（日後新增功能時自動獲得）。
        # 補進去的排序接在現有項目後面，才不會打亂管理員已經調整過的順序。
        existing = {p.feature_key for p in admin.permissions}
        next_order = max((p.sort_order for p in admin.permissions), default=-1) + 1
        for key in ALL_FEATURE_KEYS:
            if key not in existing:
                db.session.add(GroupPermission(
                    group_id=admin.id, feature_key=key, sort_order=next_order
                ))
                next_order += 1

        # 清掉已不存在於 FEATURES 的舊功能，避免殘留無效資料
        for p in list(admin.permissions):
            if p.feature_key not in ALL_FEATURE_KEYS:
                db.session.delete(p)

        db.session.commit()

        # 防鎖死：沒有任何 admin 使用者時，將既有帳號全部設為 admin
        admin_user_count = AdUser.query.filter_by(group_id=admin.id).count()
        if admin_user_count == 0:
            orphan_users = AdUser.query.all()
            if orphan_users:
                for u in orphan_users:
                    u.group_id = admin.id
                db.session.commit()
                print(f"偵測到尚無 admin 使用者，已將現有 {len(orphan_users)} 個帳號指派為 admin。")
