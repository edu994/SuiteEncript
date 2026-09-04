import base64
import html

from flask import Blueprint, redirect, render_template, request, session, url_for

from app.extensions import limiter
from app.models import Password, db
from app.utils.audit import log_action
from app.utils.crypto import decrypt_bytes, encrypt_bytes
from app.utils.generator import generar_contrasena
from app.utils.hibp import check_pwned_count

passwords_bp = Blueprint("passwords", __name__)


def guardar_credencial(user_id, sitio, usuario_sitio, contrasena_plana):
    """Cifra la contraseña con AES-256-GCM antes de persistirla."""
    encrypted = encrypt_bytes(contrasena_plana.encode("utf-8"))
    nueva_credencial = Password(
        user_id=user_id,
        service=sitio,
        username_site=usuario_sitio,
        encrypted_password=base64.b64encode(encrypted).decode("ascii"),
    )
    db.session.add(nueva_credencial)
    db.session.commit()
    log_action(user_id, "password_created", details=f"servicio: {sitio}")
    return nueva_credencial


def obtener_credenciales_usuario(user_id):
    """Devuelve las credenciales del usuario ya descifradas."""
    registros = Password.query.filter_by(user_id=user_id).all()
    credenciales = []

    for reg in registros:
        contrasena_plana = decrypt_bytes(
            base64.b64decode(reg.encrypted_password)
        ).decode("utf-8")
        credenciales.append({
            "id": reg.id,
            "sitio": reg.service,
            "usuario_sitio": reg.username_site,
            "contrasena": contrasena_plana,
        })

    return credenciales


def eliminar_credencial(password_id, user_id):
    credencial = Password.query.filter_by(id=password_id, user_id=user_id).first()
    if credencial:
        servicio = credencial.service
        db.session.delete(credencial)
        db.session.commit()
        log_action(user_id, "password_deleted", details=f"servicio: {servicio}")

# Configuración de límites de seguridad (Validación de entrada)
MAX_SITIO_LEN = 100
MAX_USUARIO_LEN = 100
MAX_PASS_LEN = 256


def sanitizar_entrada(texto, max_longitud):
    """
    Función de seguridad:
    1. Comprueba que no sea None o solo espacios en blanco.
    2. Recorta espacios sobrantes al inicio y final (.strip()).
    3. Escapa caracteres HTML peligrosos (<, >, &, ", ') para prevenir XSS.
    4. Trunca la longitud máxima para prevenir ataques DoS por sobrecarga de memoria.
    """
    if not texto or not texto.strip():
        return None
    
    # Recortar espacios invisibles
    texto_limpio = texto.strip()
    
    # Prevenir XSS convirtiendo <script> a &lt;script&gt;
    texto_seguro = html.escape(texto_limpio)
    
    # Prevenir saturación de memoria truncando el exceso
    return texto_seguro[:max_longitud]


@passwords_bp.route("/passwords", methods=["GET", "POST"])
@limiter.limit("30 per hour", methods=["POST"])
def passwords():
    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        # 1. Capturar datos del formulario
        raw_sitio = request.form.get("sitio")
        raw_usuario = request.form.get("usuario_sitio")
        raw_contrasena = request.form.get("contrasena")

        # 2. SANITIZAR Y VALIDAR (Capa de Seguridad Estricta)
        sitio = sanitizar_entrada(raw_sitio, MAX_SITIO_LEN)
        usuario_sitio = sanitizar_entrada(raw_usuario, MAX_USUARIO_LEN)
        
        # Para la contraseña no usamos html.escape para no alterar símbolos válidos (#, $, %, &), 
        # pero sí validamos espacios vacíos y longitud máxima.
        contrasena = raw_contrasena.strip() if raw_contrasena else None
        if contrasena and len(contrasena) > MAX_PASS_LEN:
            contrasena = contrasena[:MAX_PASS_LEN]

        # 3. Bloqueo estricto: Si algún campo falla la validación, rechazamos la petición
        if not sitio or not usuario_sitio or not contrasena:
            # Entrada inválida o vacía: ignoramos la petición o podrías mandar un mensaje de error
            return redirect(url_for("passwords.passwords"))

        # 4. Guardar únicamente si pasó todas las pruebas de seguridad
        guardar_credencial(
            user_id=session["user_id"],
            sitio=sitio,
            usuario_sitio=usuario_sitio,
            contrasena_plana=contrasena
        )

        return redirect(url_for("passwords.passwords"))

    user_passwords = obtener_credenciales_usuario(session["user_id"])

    return render_template(
        "passwords/passwords.html",
        passwords=user_passwords,
        username=session["username"]
    )


@passwords_bp.route("/passwords/delete/<int:password_id>", methods=["POST"])
@limiter.limit("30 per hour")
def delete_password(password_id):
    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    eliminar_credencial(password_id, session["user_id"])
    return redirect(url_for("passwords.passwords"))


@passwords_bp.route("/generator", methods=["GET", "POST"])
def generator():
    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    contrasena_generada = ""
    pwned_count = None

    if request.method == "POST":
        longitud = int(request.form.get("longitud", 16))
        # Limitar rango permitido entre 8 y 64 caracteres
        longitud = max(8, min(64, longitud))

        mayus = "mayus" in request.form
        numeros = "numeros" in request.form
        simbolos = "simbolos" in request.form

        contrasena_generada = generar_contrasena(
            longitud=longitud,
            incluir_mayus=mayus,
            incluir_numeros=numeros,
            incluir_simbolos=simbolos
        )
        # Verificación contra Have I Been Pwned (k-anonimato — ver
        # app/utils/hibp.py). None significa que la consulta no se pudo
        # completar (sin red, API caída); no bloquea el generador, solo se
        # deja de mostrar el resultado.
        pwned_count = check_pwned_count(contrasena_generada)

    return render_template(
        "passwords/generator.html",
        contrasena=contrasena_generada,
        pwned_count=pwned_count,
        username=session["username"]
    )