"""2FA por TOTP (RFC 6238) — opcional, activable por cada usuario.

El secreto TOTP se cifra en reposo con AES-256-GCM (la misma clave maestra
que ya protege la bóveda de archivos, las contraseñas guardadas y el
text-vault — un solo esquema de cifrado en todo el proyecto, como pide la
regla A02 de CLAUDE.md), en vez de guardarse en texto plano como hacen
muchos ejemplos de tutorial: quien obtenga ese secreto puede generar
códigos válidos indefinidamente, es tan sensible como una contraseña.

Los códigos de respaldo son de un solo uso: se generan en claro una vez
(para mostrárselos al usuario al activar 2FA), pero solo se guarda su hash
(Werkzeug, igual que la contraseña de la cuenta) — nunca el valor en sí.
"""
import base64
import io
import json
import secrets

import pyotp
import qrcode
from werkzeug.security import check_password_hash, generate_password_hash

from app.utils.crypto import decrypt_bytes, encrypt_bytes

TOTP_ISSUER = "SuiteEncript"
BACKUP_CODE_COUNT = 8


def generate_totp_secret() -> str:
    """Genera un secreto base32 nuevo. No lo persiste — eso es responsabilidad
    del caller, una vez confirmado con un código válido."""
    return pyotp.random_base32()


def get_provisioning_uri(username: str, secret: str) -> str:
    """URI otpauth:// estándar que cualquier app autenticadora (Google
    Authenticator, Authy, etc.) entiende al escanearlo como QR."""
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=TOTP_ISSUER)


def generate_qr_code_base64(uri: str) -> str:
    """PNG del QR, en memoria, codificado en base64 para incrustarlo directo
    en el HTML como data URI — evita exponer el secreto en un endpoint de
    imagen aparte, y la CSP del proyecto ya permite 'data:' en img-src."""
    img = qrcode.make(uri)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def encrypt_totp_secret(secret: str) -> str:
    return encrypt_bytes(secret.encode("utf-8")).hex()


def decrypt_totp_secret(encrypted_secret_hex: str) -> str:
    return decrypt_bytes(bytes.fromhex(encrypted_secret_hex)).decode("utf-8")


def verify_totp_code(secret: str, code: str) -> bool:
    """valid_window=1 tolera hasta un paso de 30s de desfase de reloj entre
    el móvil y el servidor (paso anterior/actual/siguiente = 90s de ventana
    total), sin dejar la validez abierta el tiempo suficiente como para
    debilitar el control."""
    if not secret or not code or not code.strip().isdigit():
        return False
    return pyotp.TOTP(secret).verify(code.strip(), valid_window=1)


def generate_backup_codes(count: int = BACKUP_CODE_COUNT) -> list:
    """Códigos de un solo uso, formato legible XXXX-XXXX en hexadecimal
    mayúsculas — fáciles de transcribir a mano si hace falta."""
    codes = []
    for _ in range(count):
        raw = secrets.token_hex(4).upper()  # 8 caracteres hexadecimales
        codes.append(f"{raw[:4]}-{raw[4:]}")
    return codes


def hash_backup_codes(codes) -> str:
    """Devuelve el JSON que se guarda en User.backup_codes: solo hashes,
    nunca los códigos en claro (igual criterio que password_hash)."""
    return json.dumps([generate_password_hash(c) for c in codes])


def verify_and_consume_backup_code(user, code: str) -> bool:
    """Si `code` coincide con un hash guardado, lo elimina de la lista (uso
    único) y devuelve True — deja el objeto `user` modificado en memoria,
    el caller es responsable de hacer db.session.commit()."""
    if not user.backup_codes or not code:
        return False
    hashes = json.loads(user.backup_codes)
    normalized = code.strip().upper()
    for i, stored_hash in enumerate(hashes):
        if check_password_hash(stored_hash, normalized):
            del hashes[i]
            user.backup_codes = json.dumps(hashes)
            return True
    return False
