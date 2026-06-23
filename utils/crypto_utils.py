import os
import base64
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization, hashes
from utils.params import KEY_DIR, PRIVATE_KEY_PATH

_cached_private_key = None


def key_generate():
    global _cached_private_key

    # 1. 檢查並建立資料夾
    if not os.path.exists(KEY_DIR):
        try:
            os.makedirs(KEY_DIR, exist_ok=True)
        except Exception as e:
            print(f"無法建立資料夾 {KEY_DIR}: {e}，請檢查權限。")
            return False

    # 2. 嘗試讀取或產生私鑰
    if os.path.exists(PRIVATE_KEY_PATH):
        print("發現現有的 RSA 私鑰檔案，正在載入至記憶體快取...")
        try:
            with open(PRIVATE_KEY_PATH, 'rb') as key_file:
                _cached_private_key = serialization.load_pem_private_key(
                    key_file.read(),
                    password=None
                )
            return True
        except Exception as e:
            print(f"載入私鑰檔案失敗: {e}")
            return False
    else:
        print("未發現 RSA 私鑰，正在產生新金鑰並存入 /source ...")
        try:
            private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048
            )
            # 將新產生的私鑰寫入檔案
            with open(PRIVATE_KEY_PATH, 'wb') as key_file:
                key_file.write(
                    private_key.private_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PublicFormat.PKCS8,
                        encryption_algorithm=serialization.NoEncryption()
                    )
                )
            # 存入快取
            _cached_private_key = private_key
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