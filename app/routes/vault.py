import hashlib
import io
import os
import secrets
from datetime import datetime, timedelta, timezone

import magic
from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from sqlalchemy import func
from werkzeug.utils import secure_filename

from app.extensions import limiter
from app.models import EncryptedFile, db
from app.utils import storage
from app.utils.audit import log_action
from app.utils.crypto import decrypt_bytes, encrypt_bytes
from app.utils.malware_scan import scan_bytes

vault_bp = Blueprint("vault", __name__, url_prefix="/vault")

# Lista blanca: solo se aceptan estas extensiones (documentos, imágenes,
# archivos comprimidos y texto). Todo lo que no esté aquí se rechaza,
# en vez de intentar enumerar cada extensión peligrosa posible.
ALLOWED_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".odt", ".xls", ".xlsx", ".ods", ".ppt", ".pptx",
    ".txt", ".csv", ".json", ".md",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp",
    ".zip", ".7z", ".tar", ".gz",
    ".mp3", ".mp4", ".wav",
}

# El nombre y la extensión no garantizan nada sobre el contenido real.
# Independientemente de la extensión, si los primeros bytes del archivo
# (los "magic bytes") identifican un tipo ejecutable o script, se rechaza.
DANGEROUS_MIME_TYPES = {
    "application/x-dosexec",
    "application/x-executable",
    "application/x-sharedlib",
    "application/x-mach-binary",
    "application/x-elf",
    "application/x-msdownload",
    "application/x-msdos-program",
    "text/x-shellscript",
    "text/x-python",
    "text/x-php",
    "application/javascript",
    "text/javascript",
}

# Cuota total por usuario, además del límite de 50MB por archivo
# (Config.MAX_CONTENT_LENGTH) — sin esto, se podían subir archivos de a
# 50MB sin ningún tope acumulado.
MAX_USER_STORAGE_BYTES = 200 * 1024 * 1024


def is_extension_allowed(filename):
    ext = os.path.splitext(filename)[1].lower()
    return ext in ALLOWED_EXTENSIONS


def is_content_safe(file_bytes):
    """Inspecciona los magic bytes reales del archivo, no la extensión declarada."""
    detected_mime = magic.from_buffer(file_bytes, mime=True)
    return detected_mime not in DANGEROUS_MIME_TYPES

@vault_bp.route("/", methods=["GET"])
def index():
    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    user_files = EncryptedFile.query.filter_by(user_id=session["user_id"]).order_by(EncryptedFile.created_at.desc()).all()

    active_files = []
    for file in user_files:
        if file.is_expired():
            storage.delete_file(file.stored_filename)
            db.session.delete(file)
        else:
            active_files.append(file)
    db.session.commit()

    return render_template("vault/vault.html", files=active_files)

@vault_bp.route("/upload", methods=["POST"])
@limiter.limit("20 per hour")
def upload_file():
    if "user_id" not in session:
        return jsonify({"error": "No autorizado"}), 401

    if "file" not in request.files:
        flash("No se seleccionó ningún archivo.", "danger")
        return redirect(url_for("vault.index"))

    file = request.files["file"]
    if file.filename == "":
        flash("Nombre de archivo no válido.", "danger")
        return redirect(url_for("vault.index"))

    if not is_extension_allowed(file.filename):
        flash("Tipo de archivo no permitido por razones de seguridad.", "danger")
        return redirect(url_for("vault.index"))

    orig_filename = secure_filename(file.filename)
    if not orig_filename:
        orig_filename = f"file_{secrets.token_hex(4)}.bin"

    file_bytes = file.read()

    if not is_content_safe(file_bytes):
        flash("El contenido del archivo no coincide con un tipo permitido.", "danger")
        return redirect(url_for("vault.index"))

    # Capa extra de defensa además de is_content_safe(): esa función solo
    # verifica el *tipo* real del archivo, no si su contenido es
    # malicioso -- un PDF real con JavaScript embebido, o un .docx real
    # con una macro, pasarían ese check sin problema. Ver
    # app/utils/malware_scan.py para el detalle, incluida la razón de por
    # qué un error de escaneo se trata como "no seguro" (fail closed).
    try:
        matched_rules = scan_bytes(file_bytes)
    except RuntimeError as exc:
        log_action(session["user_id"], "vault_upload_scan_error", details=str(exc))
        flash("No se pudo verificar la seguridad del archivo. Intentá de nuevo.", "danger")
        return redirect(url_for("vault.index"))

    if matched_rules:
        log_action(session["user_id"], "vault_upload_blocked_malware", details=f"Reglas: {', '.join(matched_rules)}")
        flash("El archivo fue rechazado: su contenido coincide con un patrón conocido de contenido malicioso.", "danger")
        return redirect(url_for("vault.index"))

    file_size = len(file_bytes)

    used_bytes = db.session.query(func.sum(EncryptedFile.file_size_bytes)).filter_by(
        user_id=session["user_id"]
    ).scalar() or 0
    if used_bytes + file_size > MAX_USER_STORAGE_BYTES:
        limit_mb = MAX_USER_STORAGE_BYTES // (1024 * 1024)
        flash(f"No hay espacio suficiente en tu bóveda (límite: {limit_mb}MB en total). Borrá algún archivo antes de subir uno nuevo.", "danger")
        return redirect(url_for("vault.index"))

    sha256_hash = hashlib.sha256(file_bytes).hexdigest()

    unique_prefix = secrets.token_hex(16)
    stored_filename = f"{unique_prefix}_{orig_filename}"

    storage.save_file(stored_filename, encrypt_bytes(file_bytes))

    is_one_time = "is_one_time" in request.form
    expiration_hours = request.form.get("expiration_hours", type=int)

    expires_at = None
    if expiration_hours and expiration_hours > 0:
        expires_at = datetime.now(timezone.utc) + timedelta(hours=expiration_hours)

    enable_share = "enable_share" in request.form
    share_password = request.form.get("share_password", "").strip()

    new_file = EncryptedFile(
        user_id=session["user_id"],
        original_filename=orig_filename,
        stored_filename=stored_filename,
        file_size_bytes=file_size,
        file_hash=sha256_hash,
        is_one_time_download=is_one_time,
        expires_at=expires_at
    )

    if enable_share:
        new_file.generate_share_token()
        if share_password:
            new_file.set_share_password(share_password)

    db.session.add(new_file)
    db.session.commit()
    log_action(session["user_id"], "file_uploaded", details=orig_filename)

    flash(f"Archivo subido con éxito. SHA-256: {sha256_hash[:16]}...", "success")
    return redirect(url_for("vault.index"))

@vault_bp.route("/download/<int:file_id>", methods=["GET"])
def download_file(file_id):
    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    file = EncryptedFile.query.filter_by(id=file_id, user_id=session["user_id"]).first()
    if not file:
        flash("Archivo no encontrado o acceso denegado.", "danger")
        return redirect(url_for("vault.index"))

    if file.is_expired():
        storage.delete_file(file.stored_filename)
        db.session.delete(file)
        db.session.commit()
        flash("El archivo ha caducado y ha sido destruido.", "danger")
        return redirect(url_for("vault.index"))

    if not storage.file_exists(file.stored_filename):
        flash("El archivo físico no se encuentra en el servidor.", "danger")
        return redirect(url_for("vault.index"))

    file.download_count += 1

    decrypted_bytes = decrypt_bytes(storage.read_file(file.stored_filename))

    log_action(session["user_id"], "file_downloaded", details=file.original_filename)

    if file.is_one_time_download:
        response = send_file(
            io.BytesIO(decrypted_bytes),
            as_attachment=True,
            download_name=file.original_filename,
        )
        db.session.delete(file)
        db.session.commit()
        storage.delete_file(file.stored_filename)
        return response

    db.session.commit()
    return send_file(
        io.BytesIO(decrypted_bytes),
        as_attachment=True,
        download_name=file.original_filename,
    )

@vault_bp.route("/delete/<int:file_id>", methods=["POST"])
def delete_file(file_id):
    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    file = EncryptedFile.query.filter_by(id=file_id, user_id=session["user_id"]).first()
    if not file:
        flash("Archivo no encontrado.", "danger")
        return redirect(url_for("vault.index"))

    storage.delete_file(file.stored_filename)

    original_filename = file.original_filename
    db.session.delete(file)
    db.session.commit()
    log_action(session["user_id"], "file_deleted", details=original_filename)
    flash("Archivo eliminado de la bóveda.", "info")
    return redirect(url_for("vault.index"))

@vault_bp.route("/share/<token>", methods=["GET", "POST"])
# El token en sí ya es un secreto de 256 bits (secrets.token_urlsafe(32)),
# pero si además tiene share_password, ese segundo secreto es mucho más
# corto y sin este límite se podría probar por fuerza bruta sin fricción.
@limiter.limit("10 per minute", methods=["POST"])
def shared_download(token):
    file = EncryptedFile.query.filter_by(share_token=token).first()
    if not file:
        return render_template("vault/share_error.html", error="El enlace no existe o ha sido revocado."), 404

    if file.is_expired():
        storage.delete_file(file.stored_filename)
        db.session.delete(file)
        db.session.commit()
        return render_template("vault/share_error.html", error="El archivo ha expirado y fue destruido."), 410

    if request.method == "POST":
        password = request.form.get("password", "")
        if file.share_password_hash and not file.check_share_password(password):
            flash("Contraseña de descarga incorrecta.", "danger")
            return render_template("vault/share.html", file=file)

        if not storage.file_exists(file.stored_filename):
            return render_template("vault/share_error.html", error="Archivo físico no encontrado."), 404

        file.download_count += 1

        decrypted_bytes = decrypt_bytes(storage.read_file(file.stored_filename))

        log_action(file.user_id, "file_downloaded_via_share", details=file.original_filename)

        if file.is_one_time_download:
            response = send_file(
                io.BytesIO(decrypted_bytes),
                as_attachment=True,
                download_name=file.original_filename,
            )
            db.session.delete(file)
            db.session.commit()
            storage.delete_file(file.stored_filename)
            return response

        db.session.commit()
        return send_file(
            io.BytesIO(decrypted_bytes),
            as_attachment=True,
            download_name=file.original_filename,
        )

    return render_template("vault/share.html", file=file)
