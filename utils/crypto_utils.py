import os
import base64
import hashlib
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization, hashes
from utils.params import KEY_DIR, PRIVATE_KEY_PATH, SECRET_KEY

_cached_private_key = None


def _generate_and_store_private_key():
    """產生新的 RSA 私鑰、寫入檔案並存入記憶體快取。"""
    global _cached_private_key

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048
    )
    pem_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        # 注意：私鑰要用 PrivateFormat，不是 PublicFormat。
        # PublicFormat 底下根本沒有 PKCS8 這個成員，寫錯會丟 AttributeError，
        # 而且是在 open(..., 'wb') 之後才炸，會留下一個 0 bytes 的壞掉金鑰檔。
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )

    # 先把 PEM 內容產生完成再開檔寫入，避免中途出錯留下空檔案
    with open(PRIVATE_KEY_PATH, 'wb') as key_file:
        key_file.write(pem_bytes)

    _cached_private_key = private_key
    return True


def key_generate():
    global _cached_private_key

    # 1. 檢查並建立資料夾
    if not os.path.exists(KEY_DIR):
        try:
            os.makedirs(KEY_DIR, exist_ok=True)
        except Exception as e:
            print(f"無法建立資料夾 {KEY_DIR}: {e}，請檢查權限。")
            return False

    # 2. 嘗試讀取現有私鑰
    if os.path.exists(PRIVATE_KEY_PATH) and os.path.getsize(PRIVATE_KEY_PATH) > 0:
        print("發現現有的 RSA 私鑰檔案，正在載入至記憶體快取...")
        try:
            with open(PRIVATE_KEY_PATH, 'rb') as key_file:
                _cached_private_key = serialization.load_pem_private_key(
                    key_file.read(),
                    password=None
                )
            return True
        except Exception as e:
            # 檔案存在但內容損毀（例如先前寫入中斷留下的空檔或壞檔）。
            # 直接回傳 False 會讓整個 RSA 功能永久失效，因此改為重新產生一把。
            print(f"載入私鑰檔案失敗: {e}，將重新產生新的 RSA 金鑰。")

    # 3. 沒有金鑰、或既有金鑰損毀，一律產生新的
    print("正在產生新的 RSA 金鑰並寫入檔案 ...")
    try:
        _generate_and_store_private_key()
        print("RSA 新私鑰已成功儲存並載入記憶體。")
        return True
    except Exception as e:
        print(f"產生或寫入私鑰檔案失敗: {e}")
        return False


def get_public_key_pem():
    global _cached_private_key

    # 防呆：如果快取是空的，先執行一次初始化
    if _cached_private_key is None:
        key_generate()
        
    if _cached_private_key is None:
        raise RuntimeError("RSA 私鑰未正確載入，無法推導公鑰。")

    # 3. 統一從私鑰推導出公鑰，並轉成 PEM 格式字串
    public_key_obj = _cached_private_key.public_key()
    public_pem = public_key_obj.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode('utf-8')
    
    return public_pem


def decrypt_frontend_data(encrypted_b64_str):
    global _cached_private_key
    
    # 防呆：如果快取是空的，先執行一次初始化
    if _cached_private_key is None:
        key_generate()

    if _cached_private_key is None:
        print("解密失敗: RSA 私鑰未載入，無法執行解密作業。")
        return None

    try:
        # 將前端傳來的 Base64 字串轉回 bytes
        encrypted_bytes = base64.b64decode(encrypted_b64_str)

        # 進行 RSA 解密
        decrypted = _cached_private_key.decrypt(
            encrypted_bytes,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        return decrypted.decode('utf-8')
    except Exception as e:
        print(f"RSA 解密失敗: {e} (可能是密文損壞或金鑰不匹配)")
        return None


# ============================================================
# 靜態儲存加密 (Fernet)
#
# RSA 只負責「前端 → 後端」的傳輸保護；資料要寫進資料庫時改用
# 對稱式的 Fernet 加密，解密時不需要另外保管一組金鑰。
#
# 注意：Fernet 要求金鑰必須是 32 bytes 的 url-safe base64 字串，
# 而專案 .env 裡的 SECRET_KEY 是 128 字元的隨機字串，不符合格式
# （直接丟給 Fernet() 會噴 ValueError）。因此這裡用 SHA-256 把
# SECRET_KEY 雜湊成固定 32 bytes 再做 base64 編碼，
# 如此可沿用既有的 SECRET_KEY，不必額外新增環境變數。
# ============================================================

def _get_fernet():
    """由 SECRET_KEY 推導出一把合法且固定的 Fernet 金鑰。"""
    if not SECRET_KEY:
        raise RuntimeError("SECRET_KEY 未設定，無法進行資料加密。")

    digest = hashlib.sha256(SECRET_KEY.encode('utf-8')).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_for_storage(plain_text):
    """將明文加密成可存進資料庫 TEXT 欄位的字串。"""
    if plain_text is None:
        return None
    return _get_fernet().encrypt(str(plain_text).encode('utf-8')).decode('utf-8')


def decrypt_from_storage(token):
    """將資料庫中的密文還原為明文；失敗時回傳 None。"""
    if not token:
        return None
    try:
        return _get_fernet().decrypt(str(token).encode('utf-8')).decode('utf-8')
    except (InvalidToken, ValueError, TypeError) as e:
        print(f"儲存資料解密失敗: {e} (可能是 SECRET_KEY 變更或密文損壞)")
        return None