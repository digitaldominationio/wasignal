"""Encryption for tenant-provided secrets (LLM keys, OAuth refresh tokens).

AES-GCM with a 32-byte key derived from WASIGNAL_SECRET_KEY. Ciphertext and
nonce are stored separately (base64). Keys are write-only: the API only ever
returns a hint like "sk-or-…4f2a".
"""
from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..config import settings


class SecretError(RuntimeError):
    pass


def _key() -> bytes:
    return hashlib.sha256(settings.secret_key.encode("utf-8")).digest()


def encrypt(value: str) -> tuple[str, str]:
    """Return (ciphertext_b64, nonce_b64)."""
    if not value:
        raise SecretError("cannot encrypt an empty secret")
    nonce = os.urandom(12)
    ciphertext = AESGCM(_key()).encrypt(nonce, value.encode("utf-8"), None)
    return base64.b64encode(ciphertext).decode(), base64.b64encode(nonce).decode()


def decrypt(ciphertext_b64: str, nonce_b64: str) -> str:
    try:
        ciphertext = base64.b64decode(ciphertext_b64)
        nonce = base64.b64decode(nonce_b64)
        return AESGCM(_key()).decrypt(nonce, ciphertext, None).decode("utf-8")
    except Exception as exc:  # wrong master key, corrupted row
        raise SecretError("could not decrypt secret") from exc


def hint(value: str) -> str:
    cleaned = (value or "").strip()
    if len(cleaned) <= 8:
        return "…"
    prefix = cleaned[:5]
    return f"{prefix}…{cleaned[-4:]}"
