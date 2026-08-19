import json
from utils.hpc.hpc_setting_utils import load_hpc_settings_by_classification
from sqlalchemy import func, cast, Numeric, and_, or_, exists
from sqlalchemy.orm import aliased
from database.extensions import db
from database.hpc_model import (Accounting, PrepaidAmount, NotificationHistory, Serverlist,
                                QuotationItem)
from datetime import datetime, timedelta
from utils.params import RESEARCH_BONUS_SOURCE_PREFIX


def is_research_bonus(source_id):
    """判斷一筆 PrepaidAmount 是否為系統發放的研究獎勵額度（而非使用者自費儲值）。"""
    return bool(source_id) and source_id.startswith(RESEARCH_BONUS_SOURCE_PREFIX)


# =========================================================================
# 計價用的 Accounting ↔ Serverlist 連結條件
#
# ⚠️ 這是全站唯一該用來算錢的 join 條件，所有計價查詢都必須經過它。
#
# 為什麼不能只 join (host = server AND queue = queue)：
#   Serverlist 是「費率歷史表」，同一個 (server, queue) 會因為調價而存在
#   多筆不同年份的紀錄。例如 n98/v100 就有 2.00 (2022) 與 2.10 (2024) 兩筆。
#   只比對 server + queue 的話，同一筆 job 會同時對到這兩列，
#   金額被加總成 4.10 倍 —— 這曾造成 2025 年度 n98/v100 多計約 20 萬元。
#
# 取價規則：
#   以該筆 job 的結束年份 Y 為準，取「年份 <= Y 之中最新的那一筆費率」。
#   亦即 2023 年的 job 用 2022 年的費率，2025 年的 job 用 2024 年的費率。
#
#   年份晚於 Y 的費率紀錄一律忽略，不當退路。所以若該 queue 一筆
#   year <= Y 的費率都沒有，這段用量就「不計費」——這是刻意的：
#   新機器在試辦期收費起算本來就比較晚（例如 i73 / i90-large 的費率是
#   2026 年，2026 年以前的用量屬於試辦期，不該收錢）。
#
#   ⚠️ 不計費不等於可以無聲消失。這些用量會由 get_unpriced_usage() 撈出來，
#   在開立繳費單的預覽視窗中明列，讓開單的人知道「有這段用量但沒有收費」。
#   若某台機器其實是「費率表建太晚」而非試辦期（例如 h81 有 2017 年的用量
#   但最早費率是 2022 年），正確做法是去 serverlist 補一筆早年的費率，
#   而不是讓程式去猜。
#
#   同年份又重複（理論上不該發生）時以 id 較小者為準，
#   確保任何情況下每筆 job 都只會對到「剛好一列」費率。
# =========================================================================
def accounting_price_join():
    """
    回傳 Accounting join Serverlist 時要用的 ON 條件（已內含唯一費率的篩選）。

    用法：
        query.join(Serverlist, accounting_price_join())

    比較的年份一律取自 Accounting.endtime，與各處統計的歸屬年份定義一致。
    因為這是 inner join，沒有適用費率的用量會自然被排除（＝不計費）。
    """
    target_year = func.extract('year', Accounting.endtime)

    # other = 同一個 (server, queue) 中「同樣適用、但更接近該年份」的費率紀錄；
    # 只要存在這樣的紀錄，目前這筆就不該被選中。
    other = aliased(Serverlist)

    other_is_better = or_(
        # 一樣不晚於目標年份的前提下，年份越新越適合
        other.year > Serverlist.year,
        # 年份完全相同時以 id 較小者為準，避免重複資料再次造成重複計費
        and_(other.year == Serverlist.year, other.id < Serverlist.id),
    )

    return and_(
        Accounting.host == Serverlist.server,
        Accounting.queue == Serverlist.queue,
        # 晚於用量年份的費率直接忽略
        Serverlist.year <= target_year,
        ~exists().where(and_(
            other.server == Serverlist.server,
            other.queue == Serverlist.queue,
            other.year <= target_year,
            other_is_better
        ))
    )


def get_hpc_user_and_total_usage_with_details():
    """
    計算每個帳號在當年度和【今年初至今】的總費用，並提供每個 server 的明細。

    Args:
        check_period_days (int, optional): 原本用於計算近期用量，現已改為計算今年初至今，此參數可留空。

    Returns:
        tuple: 包含當年度用量和今年初至今用量的字典。
               每個字典的 key 是使用者名稱，value 是一個包含 'total_price' 和 'details' 的字典。
    """
    current_year = datetime.now().year
    
    # 關鍵修改：將近期計算的起點，設定為當年度的 1 月 1 日 0 點 0 分 0 秒
    recent_period_start = datetime(current_year, 1, 1, 0, 0, 0)
    
    # 執行 SQL 聯結查詢，並計算每個使用者在每個 server 上的花費
    base_query = db.session.query(
        Accounting.username,
        Serverlist.server,
        func.sum(
            (Accounting.cores * (Accounting.wtime / 3600)) * Serverlist.price
        ).label('total_price')
    # 計價一律走 accounting_price_join()：它除了比對 server + queue，
    # 還會從該 (server, queue) 的多筆歷史費率中挑出唯一一筆適用的價格
    ).join(Serverlist, accounting_price_join()).group_by(
        Accounting.username, Serverlist.server
    )
    
    # 過濾出當年度的資料（依據年份標籤）
    yearly_results = base_query.filter(
        func.extract('year', Accounting.endtime) == current_year
    ).all()

    # 過濾出今年初到現在的資料（依據時間戳記大於等於 1/1）
    recent_results = base_query.filter(
        Accounting.endtime >= recent_period_start
    ).all()

    # 將查詢結果轉換為所需的巢狀字典格式
    yearly_usage = {}
    for row in yearly_results:
        if row.username not in yearly_usage:
            yearly_usage[row.username] = {
                'total_price': 0.0,
                'details': {}
            }
        
        cost = float(row.total_price)
        yearly_usage[row.username]['total_price'] += cost
        yearly_usage[row.username]['details'][row.server] = cost

    # 這邊算出來的就是「今年初至今」的數據了
    recent_usage = {}
    for row in recent_results:
        if row.username not in recent_usage:
            recent_usage[row.username] = {
                'total_price': 0.0,
                'details': {}
            }

        cost = float(row.total_price)
        recent_usage[row.username]['total_price'] += cost
        recent_usage[row.username]['details'][row.server] = cost
        
    return yearly_usage, recent_usage

def get_hpc_user_and_total_usage(check_period_days):
    """
    計算每個帳號在當年度和指定時間範圍內的總費用。
    
    Args:
        check_period_days (int): 用於計算近一段時間用量的天數。
    
    Returns:
        tuple: 包含當年度用量和近期用量的字典，格式為
               (yearly_usage, recent_usage)
               例如: ({'user1': 1000, 'user2': 500}, {'user1': 50, 'user2': 20})
    """
    
    current_year = datetime.now().year
    
    # 計算時間點
    recent_period_start = datetime.now() - timedelta(days=check_period_days)
    
    # 執行 SQL 聯結查詢並計算費用
    # 計算 job 執行的小時數 (wtime / 3600)
    # 計價一律走 accounting_price_join()（唯一費率，見該函式說明）
    yearly_results = db.session.query(
        Accounting.username,
        func.sum(
            (Accounting.cores * (Accounting.wtime / 3600)) * Serverlist.price
        ).label('total_price')
    ).join(Serverlist, accounting_price_join()).filter(
        func.extract('year', Accounting.endtime) == current_year
    ).group_by(Accounting.username).all()

    recent_results = db.session.query(
        Accounting.username,
        func.sum(
            (Accounting.cores * (Accounting.wtime / 3600)) * Serverlist.price
        ).label('total_price')
    ).join(Serverlist, accounting_price_join()).filter(
        Accounting.endtime >= recent_period_start
    ).group_by(Accounting.username).all()

    # 將查詢結果轉換為字典格式
    yearly_usage = {row.username: float(row.total_price) for row in yearly_results}
    recent_usage = {row.username: float(row.total_price) for row in recent_results}
    
    return yearly_usage, recent_usage

def get_account_last_year_usage_details(username):
    """
    計算單一帳號「去年度」依主機+queue分組的 HPC 使用量明細，供確認信範本
    (templates/email/quotation_check_email.html) 的動態使用量表格使用。

    計算公式與 hpc_quota_routes.calculate_pending_bill / contact_routes.get_hpc_statistics
    保持一致：SU = cores * (wtime 秒數 / 3600) * 該主機當時的單價。

    注意：Serverlist 同一個 server 可能有多筆不同 queue 的價格設定，
    因此 join 條件除了 host 還必須帶上 queue，否則同一筆 Accounting
    job 會同時對到該 host 底下的多個 queue 價格，造成總額被重複加總、灌水。

    Returns:
        dict: {
            'usage_year': int,                 去年度年份
            'usage_rows': [{'host', 'queue', 'job_count', 'su'}, ...],  依主機+queue分組明細
            'usage_total_su': float            該帳號去年度總 SU
        }
    """
    last_year = datetime.now().year - 1

    results = db.session.query(
        Accounting.host,
        Accounting.queue,
        func.count(Accounting.jobid).label('job_count'),
        func.sum((Accounting.cores * (cast(Accounting.wtime, Numeric) / 3600)) * Serverlist.price).label('su')
    ).join(
        Serverlist, accounting_price_join()
    ).filter(
        Accounting.username == username,
        func.extract('year', Accounting.endtime) == last_year
    ).group_by(Accounting.host, Accounting.queue).order_by(Accounting.host, Accounting.queue).all()

    usage_rows = [
        {
            'host': row.host,
            'queue': row.queue,
            'job_count': row.job_count or 0,
            'su': round(float(row.su or 0), 2)
        }
        for row in results
    ]
    usage_total_su = round(sum(row['su'] for row in usage_rows), 2)

    return {
        'usage_year': last_year,
        'usage_rows': usage_rows,
        'usage_total_su': usage_total_su
    }

def get_account_year_usage_by_server_queue(username, year):
    """
    計算單一帳號在指定年度、依「主機 + queue」分組的核心小時數與金額。

    這是繳費單（報價單）計價的原始資料。既有的
    get_account_last_year_usage_details() 只回傳金額 (SU)，
    但報價單的表格需要「使用量（核心小時）」與「收費係數」兩欄分開顯示，
    所以這裡把核心小時 (cores * wtime/3600) 與金額 (核心小時 * 單價)
    一起撈出來，並附上該 queue 的單價供合併時判斷。

    ⚠️ Serverlist 同一個 server 會有多筆不同 queue 的價格設定，
    join 一定要同時比對 host 與 queue，否則同一筆 job 會對到該 host
    底下的每一個 queue 價格，金額被重複加總而灌水。
    這個規則在 calculate_pending_bill / get_hpc_statistics /
    get_hpc_user_and_total_usage_with_details 都是一致的。

    Returns:
        list[dict]: [{'server', 'queue', 'price', 'job_count', 'core_hours', 'amount'}, ...]
    """
    core_hours_expr = func.sum(Accounting.cores * (cast(Accounting.wtime, Numeric) / 3600))

    results = db.session.query(
        Accounting.host.label('server'),
        Accounting.queue.label('queue'),
        Serverlist.price.label('price'),
        func.count(Accounting.jobid).label('job_count'),
        core_hours_expr.label('core_hours'),
        func.sum((Accounting.cores * (cast(Accounting.wtime, Numeric) / 3600)) * Serverlist.price).label('amount')
    ).join(
        Serverlist, accounting_price_join()
    ).filter(
        Accounting.username == username,
        func.extract('year', Accounting.endtime) == year
    ).group_by(
        Accounting.host, Accounting.queue, Serverlist.price
    ).order_by(Accounting.host, Accounting.queue).all()

    return [
        {
            'server': row.server,
            'queue': row.queue,
            'price': float(row.price or 0),
            'job_count': row.job_count or 0,
            'core_hours': round(float(row.core_hours or 0), 2),
            'amount': round(float(row.amount or 0), 2)
        }
        for row in results
    ]


def get_effective_rates(year):
    """
    取出指定年度每個 (server, queue) 實際適用的單價。

    取價規則與 accounting_price_join() 完全一致：只看年份 <= year 的費率，
    取其中最新的一筆；一筆都沒有的 (server, queue) 不會出現在結果裡
    （代表該年度不收費）。只是改在 Python 端算 —— serverlist 只有十來筆，
    沒必要為了這件事再繞一次 SQL。

    這是給報價單「收費係數」欄用的：係數應該反映『設定的費率』，
    而不是『這次剛好用到的費率』。否則某一列今年用量是 0 時就沒有價格可推，
    報價單上會印出一個空的係數，跟原本的報價單長得不一樣。

    Returns:
        dict: {(server, queue): float price}
    """
    rates = {}
    for row in Serverlist.query.all():
        if not row.server:
            continue
        row_year = row.year if row.year is not None else 0
        # 晚於目標年份的費率忽略（該年度尚未開始收費）
        if row_year > year:
            continue

        key = (row.server, row.queue)
        current = rates.get(key)
        # 年份越新越適合；同年份時以 id 較小者為準
        if current is None or (row_year, -(row.id or 0)) > (
                (current.year if current.year is not None else 0), -(current.id or 0)):
            rates[key] = row

    return {key: float(row.price or 0) for key, row in rates.items()}


def get_display_rates(year):
    """
    報價單「收費係數」欄要顯示的單價。

    與 get_effective_rates() 的差別只有一個：當某個 (server, queue) 在該年度
    還沒有生效的費率時（試辦期尚未起算收費，例如 i73 的費率是 2026 年、
    但現在在開 2025 年度的帳單），這裡會退而顯示最接近的那一筆費率。

    ⚠️ 這只影響「顯示」，不影響任何金額：
    計費一律走 accounting_price_join()，年份晚於用量的費率仍然完全不採計，
    所以那些 queue 的使用量與總價依舊是 0（並且會列在「未計費用量」中）。
    這樣報價單既能當價目表看（客戶看得到那台機器多少錢），
    又不會因此多收一毛錢。
    """
    rates = dict(get_effective_rates(year))

    fallback = {}
    for row in Serverlist.query.all():
        if not row.server:
            continue
        key = (row.server, row.queue)
        if key in rates:
            continue
        row_year = row.year if row.year is not None else 0
        current = fallback.get(key)
        # 都晚於目標年份時，取年份最接近（最小）的那一筆
        if current is None or (row_year, -(row.id or 0)) < (
                (current.year if current.year is not None else 0), -(current.id or 0)):
            fallback[key] = row

    for key, row in fallback.items():
        rates[key] = float(row.price or 0)

    return rates


def get_unpriced_usage(username, year):
    """
    找出該帳號在指定年度「沒有適用費率、因此不會被計費」的用量。

    有兩種情況會落到這裡，兩者都是 inner join 直接排除、完全不計費：
      1. Serverlist 裡根本沒有這個 (server, queue) —— 例如 ngc3/workq、i90/vasp
      2. 有這個 (server, queue)，但費率年份全都晚於用量年份 —— 試辦期尚未起算收費
         （例如 i73 / i90-large 的費率是 2026 年，2026 年以前屬試辦期）

    金額算不出來（沒有適用費率），但一定要讓開單的人知道「有這段用量沒收錢」，
    否則帳單短收是看不出來的。開立繳費單時會把這份清單一起顯示出來。

    Returns:
        list[dict]: [{'server', 'queue', 'job_count', 'core_hours'}, ...]
    """
    results = db.session.query(
        Accounting.host.label('server'),
        Accounting.queue.label('queue'),
        func.count(Accounting.jobid).label('job_count'),
        func.sum(Accounting.cores * (cast(Accounting.wtime, Numeric) / 3600)).label('core_hours')
    ).filter(
        Accounting.username == username,
        func.extract('year', Accounting.endtime) == year,
        ~exists().where(and_(
            Serverlist.server == Accounting.host,
            Serverlist.queue == Accounting.queue,
            # 費率年份晚於用量年份的不算數，與 accounting_price_join() 一致
            Serverlist.year <= func.extract('year', Accounting.endtime)
        ))
    ).group_by(Accounting.host, Accounting.queue).order_by(Accounting.host, Accounting.queue).all()

    return [
        {
            'server': row.server,
            'queue': row.queue,
            'job_count': row.job_count or 0,
            'core_hours': round(float(row.core_hours or 0), 2)
        }
        for row in results
    ]


def get_default_quotation_items():
    """
    尚未在「⚙️ 設定 → 繳費單格式設定」建立任何列時的退路：
    直接把 Serverlist 裡啟用中的主機，依 server 各成一列（涵蓋其所有 queue）。

    這樣至少不會因為忘了設定就印出一張沒有任何計算資源的報價單；
    管理員之後在設定頁建立自己的列（例如把多台機器合併成
    「GPU/Phi 計算節點」一列）之後，就會改用設定的內容。
    """
    servers = db.session.query(Serverlist.server).filter_by(status=True).distinct().all()
    items = []
    for index, row in enumerate(sorted(s[0] for s in servers if s[0])):
        items.append({
            'id': None,
            'label': row,
            'targets': [{'server': row, 'queues': []}],
            'coefficient': None,
            'sort_order': index,
            'is_active': True
        })
    return items


def load_quotation_item_configs():
    """讀取啟用中的繳費單格式設定；一筆都沒有時退回 get_default_quotation_items()。"""
    items = QuotationItem.query.filter_by(is_active=True)\
        .order_by(QuotationItem.sort_order.asc(), QuotationItem.id.asc()).all()
    if items:
        return [item.to_dict() for item in items]
    return get_default_quotation_items()


def _usage_matches_target(usage_row, target):
    """判斷一筆 (server, queue) 用量是否屬於某個設定列的涵蓋範圍。"""
    if usage_row['server'] != target['server']:
        return False
    # queues 留空 = 該 server 底下的所有 queue
    if not target['queues']:
        return True
    return usage_row['queue'] in target['queues']


def build_quotation_rows(username, year):
    """
    把帳號在指定年度的用量，依「繳費單格式設定」合併成報價單上的每一列。

    一個 server 可能有多個 queue、不同 queue 單價也不同，因此：
      - 使用量（核心小時）= 該列涵蓋的所有 queue 核心小時加總
      - 總價             = 各 queue 各自「核心小時 × 該 queue 單價」後加總
                           （不是「合併後的核心小時 × 單一係數」，
                             否則混價的列會算錯錢）
      - 收費係數         = 設定裡填的顯示值；沒填時，若該列涵蓋的 queue
                           單價一致就顯示該單價，不一致則顯示 None
                           （前端／範本會印成「-」），避免印出一個
                           「係數 × 使用量 ≠ 總價」的誤導數字。

    有兩種「錢會從帳單上消失」的情況，都必須讓開單的人看得到：
      unmatched  有費率、也算得出金額，但沒有被任何一列設定涵蓋到
                 → 去「繳費單格式設定」補一列即可
      unpriced   Serverlist 裡根本沒有這個 (server, queue) 的費率，
                 連金額都算不出來 → 要先去補費率設定

    Returns:
        dict: {
            'rows': [{'label', 'coefficient', 'core_hours', 'amount'}, ...],
            'subtotal': float,      各列總價加總
            'unmatched': [{'server', 'queue', 'core_hours', 'amount'}, ...],
            'unmatched_amount': float,
            'unpriced': [{'server', 'queue', 'job_count', 'core_hours'}, ...]
        }
    """
    result = build_quotation_rows_from_usage(
        get_account_year_usage_by_server_queue(username, year), year
    )
    result['unpriced'] = get_unpriced_usage(username, year)
    return result


def build_empty_quotation_rows(year):
    """
    只要報價單的版面骨架與費率，不帶任何用量。

    預繳帳單用得到：它賣的是額度而不是既有用量，但版面要跟一般帳單一模一樣，
    所以先取得同一套「計算資源」列與係數，再把預繳金額放到指定的那一格。
    """
    return build_quotation_rows_from_usage([], year)


def build_quotation_rows_from_usage(usage_rows, year):
    """依「繳費單格式設定」把給定的用量合併成報價單的每一列（見 build_quotation_rows）。"""
    configs = load_quotation_item_configs()
    # 係數欄用「顯示用費率」：試辦期尚未起算收費的機器也要看得到價目，
    # 但金額仍來自 usage_rows（走嚴格的 accounting_price_join），所以不會多收錢
    rates = get_display_rates(year)

    matched_keys = set()
    rows = []

    for config in configs:
        targets = config.get('targets') or []

        # 這一列涵蓋、且有費率可顯示的 (server, queue)
        covered = {
            (server, queue): price
            for (server, queue), price in rates.items()
            if any(server == t['server'] and (not t['queues'] or queue in t['queues'])
                   for t in targets)
        }

        # 這一列涵蓋到的用量，逐 queue 收集
        usage_by_key = {}
        for usage in usage_rows:
            if not any(_usage_matches_target(usage, t) for t in targets):
                continue
            key = (usage['server'], usage['queue'])
            matched_keys.add(key)
            bucket = usage_by_key.setdefault(key, {'core_hours': 0.0, 'amount': 0.0})
            bucket['core_hours'] += usage['core_hours']
            bucket['amount'] += usage['amount']

        core_hours = round(sum(b['core_hours'] for b in usage_by_key.values()), 2)
        amount = round(sum(b['amount'] for b in usage_by_key.values()), 2)

        override = config.get('coefficient')
        if override is not None:
            # 設定裡指定了顯示用係數：整列就以那個數字呈現，不再拆分
            entries = [{
                'coefficient': override,
                'queues': sorted({queue for _, queue in covered}),
                'core_hours': core_hours,
                'amount': amount
            }]
        elif covered:
            # 沒指定係數時，依「費率」把這一列拆成數個子項。
            # 同一列可能涵蓋單價不同的 queue（例如 i73 的 large=0.22、workq=0.26），
            # 過去這種情況只能印一個 '-'，因為印任何單一數字都會讓
            # 「係數 × 使用量 ≠ 總價」。改成拆開之後，每個子項各自成立，
            # 報價單上「計算資源」那一格會跨列合併，係數則逐項列出並附註 queue。
            grouped = {}
            for (server, queue), price in covered.items():
                bucket = grouped.setdefault(price, {'queues': [], 'core_hours': 0.0, 'amount': 0.0})
                bucket['queues'].append(queue)
                used = usage_by_key.get((server, queue))
                if used:
                    bucket['core_hours'] += used['core_hours']
                    bucket['amount'] += used['amount']

            entries = [{
                'coefficient': price,
                'queues': sorted(set(bucket['queues'])),
                'core_hours': round(bucket['core_hours'], 2),
                'amount': round(bucket['amount'], 2)
            } for price, bucket in sorted(grouped.items())]
        else:
            # 這一列涵蓋的 queue 該年度都沒有費率（例如試辦期尚未起算收費）
            entries = [{
                'coefficient': None,
                'queues': [],
                'core_hours': core_hours,
                'amount': amount
            }]

        rows.append({
            'label': config.get('label') or '',
            'entries': entries,
            'core_hours': core_hours,
            'amount': amount
        })

    unmatched = [
        {
            'server': u['server'],
            'queue': u['queue'],
            'core_hours': u['core_hours'],
            'amount': u['amount']
        }
        for u in usage_rows
        if (u['server'], u['queue']) not in matched_keys
    ]

    return {
        'rows': rows,
        'subtotal': round(sum(r['amount'] for r in rows), 2),
        'unmatched': unmatched,
        'unmatched_amount': round(sum(u['amount'] for u in unmatched), 2),
        # 呼叫端若需要「查無費率的用量」，由 build_quotation_rows() 補上
        'unpriced': []
    }


def get_usage_and_prepaid_data_db(min_usage_threshold=10000):
    """
    【資料庫版本】
    整合HPC年度用量、預繳金額和年度通知狀態。

    Args:
        min_usage_threshold (float): 本年度使用量 (SU) 顯示門檻，只有超過此門檻的帳號
            才會被列入清單，供 /api/hpc-usage/prepaid 讓前端動態調整（預設 10000）。
    """
    current_year = datetime.now().year
    
    # 1. 獲取年度總用量 (這部分不變)
    yearly_usage, _ = get_hpc_user_and_total_usage_with_details()
    
    # 2. 從資料庫獲取預繳金額（自費金額 + 優惠額度）
    # 只計入「已付款 (is_paid=True) 且非歷史封存 (is_history=False)」的紀錄，
    # 且同一帳號可能有多筆年度紀錄要加總，
    # 邏輯對齊 database/hpc_model.py 的 Contact.to_dict() 中 total_remaining 的算法，
    # 確保這裡跟聯絡人管理頁面看到的「剩餘總額度」定義一致。
    prepaid_records = PrepaidAmount.query.filter_by(is_paid=True, is_history=False).all()
    prepaid_amounts = {}
    for record in prepaid_records:
        prepaid_amounts[record.username] = (
            prepaid_amounts.get(record.username, 0.0)
            + float(record.amount or 0)
            + float(record.discount or 0)
        )
    
    # 3. 從資料庫獲取今年已通知預繳金額超額的使用者
    notified_users_records = db.session.query(NotificationHistory.username).filter(
        NotificationHistory.year == current_year,
        NotificationHistory.notification_type == 0
    ).distinct().all()
    notified_this_year = {record.username for record in notified_users_records}

    # 4. 組合資料
    combined_data = []
    all_users = set(yearly_usage.keys()) | set(prepaid_amounts.keys())

    for user in all_users:
        if user.startswith('gst'):
            continue

        usage_data = yearly_usage.get(user, {'total_price': 0.0})
        yearly_usage_rounded = round(usage_data['total_price'], 2)
        
        if yearly_usage_rounded > min_usage_threshold :
            prepaid = prepaid_amounts.get(user, 0.0)
            
            combined_data.append({
                'username': user,
                'yearly_usage': yearly_usage_rounded,
                'prepaid_amount': float(prepaid),
                'notified': user in notified_this_year
            })
    
    return combined_data

def update_prepaid_amount_db(username, amount):
    """【資料庫版本】更新或建立使用者的預繳金額紀錄。"""
    record = PrepaidAmount.query.filter_by(username=username).first()
    if record:
        record.amount = amount
    else:
        record = PrepaidAmount(username=username, amount=amount)
        db.session.add(record)
    db.session.commit()


def calculate_prepaid_quota(deposit_amount):
    """
    根據預繳金額計算最終獲得的額度
    :param deposit_amount: 預繳金額 (例如 60000)
    :return: 計算後的總額度 (四捨五入或取整數)
    """
    # 1. 從 DB 取出設定清單
    settings_list = load_hpc_settings_by_classification(2)
    
    # 2. 從 List 中找到 key 為 'discount' 的那一筆資料
    discount_item = next((item for item in settings_list if item.get('key') == 'discount'), {})
    discounts_raw = discount_item.get('value', [])
    
    # 3. 解析 discounts (處理字串或直接是 List/Dict 的情況)
    if isinstance(discounts_raw, str):
        try:
            discounts = json.loads(discounts_raw)
        except json.JSONDecodeError:
            discounts = []
    elif isinstance(discounts_raw, list):
        discounts = discounts_raw
    else:
        discounts = []

    # 4. 動態 If-Else 判斷與算式套用
    for rule in discounts:
        if not isinstance(rule, dict):
            continue
            
        min_amount = rule.get('min_amount', 0)
        divisor = rule.get('divisor', 1.0)
        
        if deposit_amount >= min_amount:
            if divisor != 0:
                return round(deposit_amount / divisor)
            break

    # 若未達任何優惠門檻，回傳原始預繳金額
    return deposit_amount