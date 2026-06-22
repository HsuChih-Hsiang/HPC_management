from flask import current_app
from database.extensions import db
from database.hpc_model import HPCSetting
from utils.params import DEFAULT_HPC_SETTINGS


def _convert_value_to_type(key, value_str):
    """將資料庫讀出的字串值轉換為正確的 Python 型別"""
    setting_info = DEFAULT_HPC_SETTINGS.get(key)
    if not setting_info:
        return value_str # 如果不是預設的 key，直接返回字串
    
    target_type = setting_info['type']
    try:
        if target_type == int:
            return int(value_str)
        elif target_type == float:
            return float(value_str)
        # 如果是其他型別，可以繼續新增判斷
        return value_str
    except ValueError:
        current_app.logger.error(f"HPCSetting Key: {key} 的值 '{value_str}' 無法轉換為 {target_type.__name__}，使用預設值。")
        return setting_info['value']


def load_hpc_settings():
    """從資料庫加載所有設定，如果不存在則創建預設值"""
    settings_dict = {}
    
    # 確保應用程式上下文存在
    with current_app.app_context():
        existing_settings = HPCSetting.query.all()
        existing_keys = {s.key: s for s in existing_settings}

        for key, info in DEFAULT_HPC_SETTINGS.items():
            if key not in existing_keys:
                default_value = str(info['value'])
                new_setting = HPCSetting(
                    key=key, 
                    value=default_value, 
                    description=info['desc']
                )
                db.session.add(new_setting)
                settings_dict[key] = info['value']
            else:
                db_setting = existing_keys[key]
                settings_dict[key] = _convert_value_to_type(key, db_setting.value)
        
        db.session.commit()
        
    return settings_dict


def save_hpc_settings(settings):
    """將設定字典存入資料庫"""
    with current_app.app_context():
        for key, value in settings.items():
            # 找到現有設定或創建新設定
            setting_obj = HPCSetting.query.filter_by(key=key).first()
            
            if setting_obj:
                # 更新現有值，將其轉換為字串儲存
                setting_obj.value = str(value)
            else:
                # 如果是新的 key (非預設的)，則新增
                new_setting = HPCSetting(
                    key=key, 
                    value=str(value), 
                    description=f"自定義設定: {key}"
                )
                db.session.add(new_setting)
        
        db.session.commit()