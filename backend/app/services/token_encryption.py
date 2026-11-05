"""
Token Encryption Service
Provides secure Fernet symmetric encryption and decryption for OAuth access and refresh tokens.
Keys are deterministically derived from APP_SECRET_KEY so tokens can be decrypted across worker restarts.
"""
import base64
import hashlib
from typing import Optional
from cryptography.fernet import Fernet
import structlog

from app.core.config import settings

logger = structlog.get_logger()


def _get_fernet_cipher() -> Fernet:
    """Derive a 32-byte URL-safe base64 key from APP_SECRET_KEY for Fernet."""
    secret = settings.APP_SECRET_KEY or settings.JWT_SECRET_KEY or "gtm-production-secret-fallback-key-32b"
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_token(plain_token: Optional[str]) -> Optional[str]:
    """Encrypt plain text token to Fernet ciphertext string."""
    if not plain_token:
        return None
    try:
        cipher = _get_fernet_cipher()
        encrypted_bytes = cipher.encrypt(plain_token.encode("utf-8"))
        return encrypted_bytes.decode("utf-8")
    except Exception as e:
        logger.error("Failed to encrypt OAuth token", error=str(e))
        raise RuntimeError("Token encryption failure") from e


def decrypt_token(encrypted_token: Optional[str]) -> Optional[str]:
    """Decrypt Fernet ciphertext string back to plain text token."""
    if not encrypted_token:
        return None
    try:
        cipher = _get_fernet_cipher()
        decrypted_bytes = cipher.decrypt(encrypted_token.encode("utf-8"))
        return decrypted_bytes.decode("utf-8")
    except Exception as e:
        logger.error("Failed to decrypt OAuth token", error=str(e))
        raise RuntimeError("Token decryption failure") from e
