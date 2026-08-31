import ast
import json
from flask import current_app
from sqlalchemy import inspect
from database.extensions import db
from database.hpc_model import HPCSetting
from utils.params import DEFAULT_HPC_SETTINGS


def check_billing_tables(app):
    """
    啟動時確認開單流程需要的兩張資料表已建立。

    本專案沒有使用 migration 工具，也沒有呼叫 db.create_all()，新表要靠
    sql/ 底下的檔案手動建立。少了表卻直接查詢時，SQLAlchemy 只會丟出難以
    理解的 ProgrammingError，且會出現在完全無關的 API 上，所以在啟動時
    就先把話講清楚（沿用權限管理／個人資料欄位的既有做法）。
    """
    with app.app_context():
        inspector = inspect(db.engine)
        table_names = set(inspector.get_table_names())
        missing = {'billing_workflows', 'quotation_items'} - table_names
        if missing:
            print('=' * 70)
            print(f"[繳費單流程] 缺少資料表: {', '.join(sorted(missing))}")
            print("請先執行 sql/20260819_add_billing_workflow_and_quotation_items.sql 後再啟動服務。")
            print('=' * 70)
        elif 'discount_applied' not in {c['name'] for c in inspector.get_columns('billing_workflows')}:
            # 欄位已寫進 model，每一次 BillingWorkflow 查詢都會 SELECT 它；
            # 資料庫還沒加的話，錯誤會以難懂的 ProgrammingError 出現在開單流程 API 上。
            print('=' * 70)
            print("[帳單折扣] billing_workflows 缺少 discount_applied 欄位。")
            print("請先執行 sql/20260826_add_billing_workflow_discount_applied.sql 後再啟動服務。")
            print('=' * 70)

        check_serverlist_rates()


def check_serverlist_rates():
    """
    啟動時檢查費率表的資料健康度。

    計價是靠 accounting_price_join() 依 job 年份挑出唯一一筆費率，
    同一個 (server, queue, year) 若重複，它只能以 id 較小者為準 ——
    不會再重複計費，但「到底該用哪個價」已經是人為決定不了的了，
    所以要在啟動時講出來讓人去清資料。

    （同一個 (server, queue) 有多個「不同年份」的費率是正常的調價歷史，
      不在此列。）
    """
    from database.hpc_model import Serverlist
    from sqlalchemy import func

    duplicates = db.session.query(
        Serverlist.server, Serverlist.queue, Serverlist.year, func.count('*').label('n')
    ).group_by(Serverlist.server, Serverlist.queue, Serverlist.year)\
     .having(func.count('*') > 1).all()

    if duplicates:
        print('=' * 70)
        print('[費率設定] serverlist 有同年份重複的費率，計價時只會採用 id 較小的那一筆：')
        for server, queue, year, count in duplicates:
            print(f'    {server}/{queue} {year} 年 共 {count} 筆')
        print('請清理重複資料，確保每個 (server, queue, 年份) 只有一筆費率。')
        print('=' * 70)


def _convert_value_to_type(key, value_str):
    """將資料庫 TEXT 欄位讀出的字串轉為對應型態"""
    setting_info = DEFAULT_HPC_SETTINGS.get(key)
    if not setting_info:
        return value_str

    target_type = setting_info['type']
    try:
        if target_type == int:
            return int(value_str)
        elif target_type == float:
            return float(value_str)
        elif target_type in (list, dict):
            if isinstance(value_str, target_type):
                return value_str
            
            # 優先使用標準 JSON 解析 (適用 json.dumps 寫入的 TEXT)
            try:
                return json.loads(value_str)
            except (json.JSONDecodeError, TypeError):
                # 備案：防止早期資料庫曾寫入 Python 單引號字串
                return ast.literal_eval(value_str)

        return value_str

    except (ValueError, TypeError, SyntaxError) as e:
        type_name = getattr(target_type, '__name__', str(target_type))
        current_app.logger.error(
            f"HPCSetting Key: {key} 的值 '{value_str}' 無法轉換為 {type_name}，使用預設值。錯誤: {e}"
        )
        return setting_info['value']


def init_hpc_settings(app):
    """檢查資料庫設定，不存在則初始化寫入 TEXT 欄位"""
    with app.app_context():
        existing_settings = HPCSetting.query.all()
        existing_keys = {s.key for s in existing_settings}
        new_added = False

        for key, info in DEFAULT_HPC_SETTINGS.items():
            if key not in existing_keys:
                raw_val = info['value']
                
                # 若為 list/dict，轉為標準 JSON 字串再存入 TEXT 欄位
                if isinstance(raw_val, (list, dict)):
                    default_value = json.dumps(raw_val)
                else:
                    default_value = str(raw_val)

                new_setting = HPCSetting(
                    key=key, 
                    value=default_value, 
                    description=info['desc'],
                    classification=info.get('classification', 1)
                )
                db.session.add(new_setting)
                new_added = True

        if new_added:
            db.session.commit()

def load_hpc_settings_by_classification(target_classification=None):
    """
    從資料庫讀取 HPC 設定並按 classification 歸類。
    若指定 target_classification，則僅回傳該類別的設定清單。
    """
    result = {}

    with current_app.app_context():
        # 如果指定了 target_classification，只向資料庫查詢該類別，提升查詢效率
        query = HPCSetting.query
        if target_classification is not None:
            query = query.filter_by(classification=target_classification)
            
        settings = query.all()

        for setting in settings:
            cls_id = setting.classification

            if cls_id not in result:
                result[cls_id] = []

            result[cls_id].append({
                'key': setting.key,
                'value': _convert_value_to_type(setting.key, setting.value),
                'description': setting.description,
                'classification': cls_id
            })

    # 若指定特定分類，回傳該分類的 List；否則回傳以 classification 為 Key 的 Dict
    if target_classification is not None:
        return result.get(target_classification, [])

    return result


BILL_DISCOUNT_KEY = 'bill_discount'


def load_bill_discount():
    """
    讀出「開帳單折扣」設定（⚙️ 系統設定 → 帳單折扣設定）。

    回傳 {'min_amount': float, 'discount': float}；尚未設定或資料壞掉一律回傳
    空字典，讓呼叫端一眼看出「沒設定」。discount 存的是折數（8.5 = 8.5 折）。
    """
    for item in load_hpc_settings_by_classification(2):
        if item.get('key') != BILL_DISCOUNT_KEY:
            continue

        value = item.get('value')
        if not isinstance(value, dict):
            return {}

        min_amount = value.get('min_amount')
        discount = value.get('discount')
        if min_amount is None or discount is None:
            return {}

        try:
            return {'min_amount': float(min_amount), 'discount': float(discount)}
        except (ValueError, TypeError):
            return {}

    return {}


def save_hpc_settings(settings):
    """將設定字典存入資料庫"""
    with current_app.app_context():
        # 'classification' 只是用來指定「這批設定」要歸類到哪個分類，
        # 它本身不是一筆設定 key，複製一份字典後把它拿掉，
        # 避免被底下的迴圈當成一般設定寫進 HPCSetting 表（多出一筆 key='classification' 的髒資料）。
        settings = dict(settings)
        target_classification = settings.pop('classification', 1)

        for key, value in settings.items():
            # 找到現有設定或創建新設定
            setting_obj = HPCSetting.query.filter_by(key=key).first()
            
            if setting_obj:
                # 更新現有值與分類
                setting_obj.value = str(value)
                setting_obj.classification = target_classification  # 修正：同步更新現有物件的分類
            else:
                # 如果是新的 key (非預設的)，則新增
                new_setting = HPCSetting(
                    key=key, 
                    value=str(value), 
                    description=f"自定義設定: {key}",
                    classification=target_classification  # 修正：補上 classification
                )
                db.session.add(new_setting)
        
        db.session.commit()