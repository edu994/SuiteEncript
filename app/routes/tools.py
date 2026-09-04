import io

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from app.models import AuditLog
from app.utils.checksums import calculate_hashes
from app.utils.steganography import extract_text_from_image, hide_text_in_image
from app.utils.text_crypto import decrypt_text, encrypt_text

tools_bp = Blueprint("tools", __name__, url_prefix="/tools")


@tools_bp.route("/audit-log", methods=["GET"])
def audit_log():
    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    events = (
        AuditLog.query
        .filter_by(user_id=session["user_id"])
        .order_by(AuditLog.created_at.desc())
        .limit(100)
        .all()
    )
    return render_template("tools/audit_log.html", events=events)


@tools_bp.route("/checksum", methods=["GET", "POST"])
def checksum():
    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    hashes = None
    match_result = None
    expected_hash = ""

    if request.method == "POST":
        expected_hash = request.form.get("expected_hash", "").strip().lower()

        if "file" in request.files and request.files["file"].filename != "":
            file = request.files["file"]
            file_bytes = file.read()
            hashes = calculate_hashes(file_bytes)
        elif "text_input" in request.form and request.form["text_input"].strip() != "":
            text_data = request.form["text_input"].strip().encode("utf-8")
            hashes = calculate_hashes(text_data)
        else:
            flash("Ingresa un texto o selecciona un archivo para analizar.", "warning")

        if hashes and expected_hash:
            if expected_hash in hashes.values():
                match_result = {
                    "status": "success",
                    "msg": "¡COINCIDENCIA EXACTA! El hash proporcionado es válido."
                }
            else:
                match_result = {
                    "status": "danger",
                    "msg": "ALERTA: El hash no coincide. El archivo podría estar alterado."
                }

    return render_template(
        "tools/checksum.html",
        hashes=hashes,
        match_result=match_result,
        expected_hash=expected_hash
    )


@tools_bp.route("/text-vault", methods=["GET", "POST"])
def text_vault():
    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    result_text = None
    action_type = None

    if request.method == "POST":
        action = request.form.get("action")
        input_text = request.form.get("input_text", "").strip()
        custom_password = request.form.get("custom_password", "").strip()

        if not input_text:
            flash("Ingresa el texto para procesar.", "warning")
            return redirect(url_for("tools.text_vault"))

        try:
            if action == "encrypt":
                result_text = encrypt_text(
                    input_text,
                    custom_password if custom_password else None
                )
                action_type = "cifrado"
                flash("Texto cifrado exitosamente en Base64 con AES-256.", "success")
            elif action == "decrypt":
                result_text = decrypt_text(
                    input_text,
                    custom_password if custom_password else None
                )
                action_type = "descifrado"
                flash("Texto descifrado exitosamente.", "success")
        except ValueError as err:
            flash(str(err), "danger")

    return render_template(
        "tools/text_vault.html",
        result_text=result_text,
        action_type=action_type
    )


@tools_bp.route("/stego", methods=["GET", "POST"])
def steganography():
    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    extracted_message = None

    if request.method == "POST":
        action = request.form.get("action")
        file = request.files.get("image_file")

        if not file or file.filename == "":
            flash("Por favor selecciona una imagen en formato PNG o JPG.", "warning")
            return redirect(url_for("tools.steganography"))

        image_bytes = file.read()

        try:
            if action == "hide":
                secret_text = request.form.get("secret_text", "").strip()
                if not secret_text:
                    flash("Escribe el mensaje secreto que deseas ocultar.", "warning")
                    return redirect(url_for("tools.steganography"))

                stego_png_bytes = hide_text_in_image(image_bytes, secret_text)

                return send_file(
                    io.BytesIO(stego_png_bytes),
                    mimetype="image/png",
                    as_attachment=True,
                    download_name="stego_image.png"
                )

            elif action == "extract":
                extracted_message = extract_text_from_image(image_bytes)
                flash("¡Mensaje oculto extraído con éxito!", "success")

        except Exception as e:  # noqa: BLE001 — entrada de usuario no confiable, cualquier fallo de PIL/esteganografía debe dar un error amigable, no un 500
            flash(f"Error procesando la imagen: {e!s}", "danger")

    return render_template("tools/stego.html", extracted_message=extracted_message)