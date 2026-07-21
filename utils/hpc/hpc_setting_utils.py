import ast
import json
from flask import current_app
from database.extensions import db
from database.hpc_model import HPCSetting
from utils.params import DEFAULT_HPC_SETTINGS


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
        elif target_type == list:
            if isinstance(value_str, list):
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


def save_hpc_settings(settings):
    """將設定字典存入資料庫"""
    with current_app.app_context():
        # 從輸入字典提取 classification，若沒帶入則預設給 1
        target_classification = settings.get('classification', 1)

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