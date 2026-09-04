import base64
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.utils.crypto import get_master_key

PBKDF2_ITERATIONS = 480_000
SALT_SIZE = 16
NONCE_SIZE = 12
MASTER_KEY_MARKER = b"\x00"
CUSTOM_PASSWORD_MARKER = b"\x01"


def _derive_key_from_password(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(password.encode("utf-8"))


def encrypt_text(plain_text: str, custom_password: str | None = None) -> str:
    """Cifra texto con AES-256-GCM y lo devuelve codificado en Base64."""
    nonce = os.urandom(NONCE_SIZE)

    if custom_password:
        salt = os.urandom(SALT_SIZE)
        key = _derive_key_from_password(custom_password, salt)
        marker = CUSTOM_PASSWORD_MARKER
    else:
        salt = b"\x00" * SALT_SIZE
        key = get_master_key()
        marker = MASTER_KEY_MARKER

    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plain_text.encode("utf-8"), None)

    payload = marker + salt + nonce + ciphertext
    return base64.b64encode(payload).decode("ascii")


def decrypt_text(encoded_text: str, custom_password: str | None = None) -> str:
    """Descifra un texto generado por encrypt_text. Lanza ValueError si falla."""
    try:
        payload = base64.b64decode(encoded_text)
    except Exception as error:
        raise ValueError("El texto cifrado no tiene un formato Base64 válido.") from error

    header_size = 1 + SALT_SIZE + NONCE_SIZE
    if len(payload) < header_size:
        raise ValueError("El texto cifrado está incompleto o corrupto.")

    marker = payload[0:1]
    salt = payload[1:1 + SALT_SIZE]
    nonce = payload[1 + SALT_SIZE:header_size]
    ciphertext = payload[header_size:]

    if marker == CUSTOM_PASSWORD_MARKER:
        if not custom_password:
            raise ValueError(
                "Este texto fue cifrado con una contraseña personalizada. Indícala para descifrarlo."
            )
        key = _derive_key_from_password(custom_password, salt)
    else:
        key = get_master_key()

    aesgcm = AESGCM(key)
    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    except Exception as error:
        raise ValueError(
            "No se pudo descifrar el texto: contraseña incorrecta o datos corruptos."
        ) from error

    return plaintext.decode("utf-8")
