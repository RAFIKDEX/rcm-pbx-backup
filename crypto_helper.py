import os
import base64
try:
    from cryptography.fernet import Fernet
except ImportError:
    import subprocess
    subprocess.run(["pip3", "install", "cryptography"])
    from cryptography.fernet import Fernet

KEY_FILE = "/etc/asterisk/.rcm_storage_key"

def get_cipher():
    if not os.path.exists(KEY_FILE):
        key = Fernet.generate_key()
        with open(KEY_FILE, "wb") as f:
            f.write(key)
        os.chmod(KEY_FILE, 0o600)
    else:
        with open(KEY_FILE, "rb") as f:
            key = f.read()
    return Fernet(key)

def encrypt_secret(secret_str):
    if not secret_str:
        return ""
    cipher = get_cipher()
    return cipher.encrypt(secret_str.encode()).decode()

def decrypt_secret(encrypted_str):
    if not encrypted_str:
        return ""
    cipher = get_cipher()
    try:
        return cipher.decrypt(encrypted_str.encode()).decode()
    except Exception:
        return ""
