import base64
import copy
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from .config import settings


ENCRYPTED_PREFIX = "enc:v1:"
_KDF_CONTEXT = b"baby-growth:ai-api-key:v1\x00"


class SecretStorageError(RuntimeError):
    pass


def _materials() -> list[str]:
    values = [settings.DATA_ENCRYPTION_KEY, settings.SECRET_KEY]
    return list(dict.fromkeys(value for value in values if value))


def _fernet(material: str) -> Fernet:
    digest = hashlib.sha256(_KDF_CONTEXT + material.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def is_encrypted_secret(value: str) -> bool:
    return bool(value and value.startswith(ENCRYPTED_PREFIX))


def encrypt_secret(value: str) -> str:
    plaintext = str(value or "")
    if not plaintext:
        return ""
    materials = _materials()
    if not materials:
        raise SecretStorageError("缺少 AI API Key 加密材料")
    token = _fernet(materials[0]).encrypt(plaintext.encode("utf-8")).decode("ascii")
    return ENCRYPTED_PREFIX + token


def _decrypt_with_index(value: str) -> tuple[str, int]:
    token = value.removeprefix(ENCRYPTED_PREFIX).encode("ascii", errors="strict")
    for index, material in enumerate(_materials()):
        try:
            plaintext = _fernet(material).decrypt(token).decode("utf-8")
            return plaintext, index
        except (InvalidToken, UnicodeDecodeError):
            continue
    raise SecretStorageError("AI API Key 无法解密，请恢复原 DATA_ENCRYPTION_KEY 或 SECRET_KEY")


def decrypt_secret(value: str) -> str:
    stored = str(value or "")
    if not stored:
        return ""
    if not is_encrypted_secret(stored):
        return stored
    try:
        return _decrypt_with_index(stored)[0]
    except (UnicodeEncodeError, ValueError) as exc:
        raise SecretStorageError("AI API Key 密文格式无效") from exc


def protect_secret(value: str) -> str:
    stored = str(value or "")
    if not stored:
        return ""
    if not is_encrypted_secret(stored):
        return encrypt_secret(stored)
    try:
        plaintext, material_index = _decrypt_with_index(stored)
    except (UnicodeEncodeError, ValueError) as exc:
        raise SecretStorageError("AI API Key 密文格式无效") from exc
    return stored if material_index == 0 else encrypt_secret(plaintext)


def protect_settings_data(data: dict | None) -> dict:
    protected = copy.deepcopy(data or {})
    ai_settings = protected.get("ai")
    if isinstance(ai_settings, dict):
        ai_settings["apiKey"] = protect_secret(ai_settings.get("apiKey", ""))
    return protected


def reveal_settings_data(data: dict | None) -> dict:
    revealed = copy.deepcopy(data or {})
    ai_settings = revealed.get("ai")
    if isinstance(ai_settings, dict):
        ai_settings["apiKey"] = decrypt_secret(ai_settings.get("apiKey", ""))
    return revealed
