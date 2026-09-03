"""Secret handling for DEX-owned optional credentials.

Passwords are stored as plaintext for simplicity.  Fernet encryption has been
removed to eliminate the external key-file dependency that caused provisioning
failures when the key file was unreadable or misconfigured.
"""


class SecretProviderError(RuntimeError):
    pass


class DexSecretProvider:
    def __init__(self, environ=None):
        pass

    def encrypt(self, value):
        if value in (None, ""):
            return None
        return str(value).encode("utf-8")

    def decrypt(self, value):
        if not value:
            return ""
        if isinstance(value, bytes):
            try:
                return value.decode("utf-8")
            except Exception:
                return value.decode("latin-1")
        return str(value)

