import secrets
from datetime import datetime, timedelta, timezone

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Opcional a propósito: las cuentas creadas antes de este campo no
    # tienen email, y no se las fuerza a completarlo retroactivamente. Sin
    # email, esa cuenta simplemente no puede usar "olvidé mi contraseña"
    # (no hay otro canal para verificar que quien lo pide es el dueño real).
    email = db.Column(db.String(255), unique=True, nullable=True)

    # Recuperación de contraseña: token de un solo uso con vencimiento,
    # mismo criterio que share_token en EncryptedFile (aleatorio de 256
    # bits, se guarda tal cual porque ya es lo bastante largo para no
    # necesitar además un hash, y se consulta directo por igualdad).
    reset_token = db.Column(db.String(64), unique=True, nullable=True)
    reset_token_expires_at = db.Column(db.DateTime, nullable=True)

    # Verificación de email: informativa, no bloquea login ni "olvidé mi
    # contraseña" (ese flujo ya es seguro sin esto -- el enlace siempre
    # llega a quien controla la casilla real). El valor real es que un
    # email mal escrito al registrarse se nota pronto (nunca llega el
    # correo de verificación) en vez de descubrirse el día que hace falta
    # recuperar la cuenta. Mismo esquema de token que reset_token, pero
    # con más margen (48h) porque lo que hay en juego es menor.
    email_verified = db.Column(db.Boolean, nullable=False, default=False)
    email_verify_token = db.Column(db.String(64), unique=True, nullable=True)
    email_verify_token_expires_at = db.Column(db.DateTime, nullable=True)

    # 2FA/TOTP (opcional, activable por el usuario — ver app/utils/totp.py).
    # El secreto viaja siempre cifrado con AES-256-GCM (nunca en texto
    # plano); backup_codes es un JSON con solo los hashes de los códigos de
    # un solo uso, nunca los códigos en sí.
    totp_secret_encrypted = db.Column(db.Text, nullable=True)
    totp_enabled = db.Column(db.Boolean, nullable=False, default=False)
    backup_codes = db.Column(db.Text, nullable=True)

    passwords = db.relationship('Password', backref='owner', lazy=True, cascade="all, delete-orphan")
    files = db.relationship('EncryptedFile', backref='owner', lazy=True, cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def generate_reset_token(self):
        """Token de recuperación de contraseña, válido por 1 hora. Devuelve
        el token en claro (va en el enlace del email); no hace falta un
        hash aparte, ya es un secreto de 256 bits de un solo uso."""
        self.reset_token = secrets.token_urlsafe(32)
        self.reset_token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        return self.reset_token

    def reset_token_is_valid(self):
        if not self.reset_token or not self.reset_token_expires_at:
            return False
        expires = self.reset_token_expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) <= expires

    def clear_reset_token(self):
        self.reset_token = None
        self.reset_token_expires_at = None

    def generate_email_verify_token(self):
        """Token de verificación de email, válido por 48 horas."""
        self.email_verify_token = secrets.token_urlsafe(32)
        self.email_verify_token_expires_at = datetime.now(timezone.utc) + timedelta(hours=48)
        return self.email_verify_token

    def email_verify_token_is_valid(self):
        if not self.email_verify_token or not self.email_verify_token_expires_at:
            return False
        expires = self.email_verify_token_expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) <= expires

    def clear_email_verify_token(self):
        self.email_verify_token = None
        self.email_verify_token_expires_at = None


class Password(db.Model):
    __tablename__ = 'passwords'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    service = db.Column(db.String(120), nullable=False)
    username_site = db.Column(db.String(120), nullable=False)
    encrypted_password = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class EncryptedFile(db.Model):
    __tablename__ = 'encrypted_files'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False, unique=True)
    file_size_bytes = db.Column(db.Integer, nullable=False, default=0)
    file_hash = db.Column(db.String(64), nullable=False)  # SHA-256 para integridad
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Opciones Efímeras y Destrucción Automática
    is_one_time_download = db.Column(db.Boolean, default=False)
    download_count = db.Column(db.Integer, default=0)
    expires_at = db.Column(db.DateTime, nullable=True)

    # Compartición Externa
    share_token = db.Column(db.String(64), unique=True, nullable=True)
    share_password_hash = db.Column(db.String(256), nullable=True)

    def generate_share_token(self):
        """Genera un token único URL-safe para compartir el archivo sin exponer IDs internos."""
        self.share_token = secrets.token_urlsafe(32)

    def set_share_password(self, password):
        """Añade una contraseña secundaria opcional a la URL compartida."""
        if password:
            self.share_password_hash = generate_password_hash(password)
        else:
            self.share_password_hash = None

    def check_share_password(self, password):
        if not self.share_password_hash:
            return True
        return check_password_hash(self.share_password_hash, password)

    def is_expired(self):
        """Verifica si el archivo ha superado el tiempo límite de vida."""
        if self.expires_at:
            now = datetime.now(timezone.utc)
            # Asegurar compatibilidad de zonas horarias en la comparación
            exp = self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=timezone.utc)
            return now > exp
        return False


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    # nullable: un intento de login fallido con un usuario inexistente no tiene user_id.
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    action = db.Column(db.String(50), nullable=False)
    # Nunca guardar aquí secretos: ni contraseñas, ni texto descifrado, ni claves.
    details = db.Column(db.String(255), nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))