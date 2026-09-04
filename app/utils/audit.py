from flask import request

from app.models import AuditLog, db


def log_action(user_id, action, details=None):
    """Registra un evento de auditoría. `details` nunca debe contener secretos
    (contraseñas, texto descifrado, claves) — solo metadatos descriptivos."""
    entry = AuditLog(
        user_id=user_id,
        action=action,
        details=details,
        ip_address=request.remote_addr,
    )
    db.session.add(entry)
    db.session.commit()
