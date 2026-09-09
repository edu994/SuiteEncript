import re

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from zxcvbn import zxcvbn

from app.extensions import limiter
from app.models import User, db
from app.utils.audit import log_action
from app.utils.email import send_email_verification_email, send_password_reset_email
from app.utils.totp import (
    decrypt_totp_secret,
    encrypt_totp_secret,
    generate_backup_codes,
    generate_qr_code_base64,
    generate_totp_secret,
    get_provisioning_uri,
    hash_backup_codes,
    verify_and_consume_backup_code,
    verify_totp_code,
)

auth_bp = Blueprint('auth', __name__)

MIN_PASSWORD_LENGTH = 10
MIN_ZXCVBN_SCORE = 3  # 0 (muy débil) a 4 (muy fuerte)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Hash señuelo (no corresponde a ninguna cuenta real) usado solo para
# igualar el tiempo de respuesta de /login cuando el usuario no existe --
# ver el comentario en login() más abajo. Generado en el propio proceso
# con generate_password_hash(), no hardcodeado: así siempre usa los mismos
# parámetros de costo (N/r/p de scrypt) que un hash real creado en este
# mismo entorno, sin depender de qué versión de Werkzeug haya instalada --
# requirements.txt solo fija un piso ("Werkzeug>=3.0.0"), así que un hash
# hardcodeado generado en otra máquina/momento puede no tener el mismo
# costo y arruinar la igualación de tiempos que este señuelo busca lograr.
_DECOY_PASSWORD_HASH = generate_password_hash("decoy-nunca-una-cuenta-real")


def require_current_password(user, submitted_password, failed_action, error_message):
    """Verifica la contraseña actual antes de una acción sensible de cuenta
    (cambiar contraseña, cambiar email, desactivar 2FA) -- mismo patrón
    repetido en las tres rutas, centralizado acá. Si la contraseña no
    coincide, ya deja el log de auditoría y el flash listos; el llamador
    solo necesita `return redirect(...)` cuando esto da False."""
    if user.check_password(submitted_password):
        return True
    log_action(user.id, failed_action)
    flash(error_message, 'danger')
    return False


def password_strength_error(password, username):
    """Devuelve un mensaje de error si la contraseña es débil, o None si es aceptable."""
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        return f'La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres.'

    result = zxcvbn(password, user_inputs=[username] if username else [])
    if result['score'] < MIN_ZXCVBN_SCORE:
        crack_time = result['crack_times_display']['offline_slow_hashing_1e4_per_second']
        return (
            f'Contraseña demasiado predecible (se rompería en aprox. {crack_time}). '
            'Prueba a alargarla o hacerla menos habitual.'
        )
    return None


@auth_bp.route('/register', methods=['GET', 'POST'])
@limiter.limit("10 per hour", methods=["POST"])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        email = request.form.get('email', '').strip().lower()

        if not username or not username.strip():
            flash('El nombre de usuario es obligatorio.', 'danger')
            return redirect(url_for('auth.register'))

        # El email es obligatorio para cuentas nuevas: sin él no hay forma
        # de ofrecer "olvidé mi contraseña" más adelante (ver
        # app/models.py:User.email — las cuentas de antes de este campo no
        # lo tienen y simplemente no pueden usar esa función).
        if not email or not EMAIL_RE.match(email):
            flash('Ingresá un email válido — lo vas a necesitar si alguna vez olvidás tu contraseña.', 'danger')
            return redirect(url_for('auth.register'))

        strength_error = password_strength_error(password, username)
        if strength_error:
            flash(strength_error, 'danger')
            return redirect(url_for('auth.register'))

        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('El nombre de usuario ya está registrado.', 'danger')
            return redirect(url_for('auth.register'))

        if User.query.filter_by(email=email).first():
            flash('Ya existe una cuenta registrada con ese email.', 'danger')
            return redirect(url_for('auth.register'))

        new_user = User(username=username, email=email)
        new_user.set_password(password)

        db.session.add(new_user)
        db.session.commit()
        log_action(new_user.id, "register")

        verify_token = new_user.generate_email_verify_token()
        db.session.commit()
        verify_url = url_for('auth.verify_email', token=verify_token, _external=True)
        send_email_verification_email(new_user.email, verify_url)
        log_action(new_user.id, "email_verification_sent")

        flash('Registro exitoso. Te enviamos un correo para confirmar tu email — ¡ahora puedes iniciar sesión!', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/register.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=["POST"])
def login():
    if request.method == 'POST':
        # El campo se sigue llamando "username" en el form (no hace falta
        # tocar el HTML/CSRF por esto), pero acepta usuario o email
        # indistintamente, como en casi cualquier sitio. .strip() nada más
        # (no .lower()): el username se guarda tal cual en el registro, así
        # que compararlo en minúsculas rompería un username con mayúsculas
        # real. El email sí se guarda siempre en minúsculas (ver register()
        # más arriba), así que ahí sí hace falta normalizar para que
        # coincida sin importar cómo se haya tipeado.
        identifier = request.form.get('username', '').strip()
        # Default a "" (no None): un POST sin el campo "password" llega con
        # password=None a check_password_hash(), que asume un str y lanza
        # AttributeError (.encode() sobre None) — un 500 en vez de un simple
        # "usuario o contraseña incorrectos".
        password = request.form.get('password', '')

        # Un OR entre username==identifier y email==identifier es ambiguo
        # si el username de una cuenta coincide con el email de otra —
        # pasó en producción (alguien había registrado una cuenta
        # escribiendo su email en el campo "usuario"). .first() sin
        # ORDER BY no garantiza cuál de las dos filas devuelve, así que a
        # veces autenticaba contra la cuenta equivocada. La búsqueda tiene
        # que ser determinística: si lo que se escribió tiene "@" es un
        # email y se busca solo por email; si no, es un username y se
        # busca solo por username — nunca los dos campos a la vez, cero
        # ambigüedad posible.
        if '@' in identifier:
            user = User.query.filter_by(email=identifier.lower()).first()
        else:
            user = User.query.filter_by(username=identifier).first()

        # Si la cuenta no existe, igual se corre un check_password_hash()
        # contra un hash señuelo fijo -- sin esto, la rama "cuenta
        # inexistente" responde mucho más rápido que la rama "cuenta real,
        # contraseña incorrecta" (no hay hash costoso que calcular), y esa
        # diferencia de tiempo (cientos de ms) permite confirmar qué
        # usuarios/emails existen sin necesidad de /forgot-password ni de
        # ver ningún mensaje distinto -- el resultado se descarta, es puro
        # trabajo para que las dos ramas tarden lo mismo.
        if user:
            password_ok = user.check_password(password)
        else:
            check_password_hash(_DECOY_PASSWORD_HASH, password)
            password_ok = False

        if user and password_ok:
            if user.totp_enabled:
                # No se abre la sesión todavía: falta el segundo factor. Se
                # guarda el id en una clave de sesión distinta a "user_id"
                # — todas las rutas protegidas comprueban "user_id", así
                # que un usuario en este estado intermedio no tiene acceso
                # a nada todavía, solo puede seguir hacia /2fa/verify.
                session['pending_2fa_user_id'] = user.id
                log_action(user.id, "login_password_ok_pending_2fa")
                return redirect(url_for('auth.verify_2fa'))

            session['user_id'] = user.id
            session['username'] = user.username
            log_action(user.id, "login_success")
            return redirect(url_for('dashboard'))
        else:
            log_action(user.id if user else None, "login_failed", details=f"usuario/email intentado: {identifier}")
            flash('Usuario o contraseña incorrectos.', 'danger')
            return redirect(url_for('auth.login'))

    return render_template('auth/login.html')


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
@limiter.limit("5 per hour", methods=["POST"])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        user = User.query.filter_by(email=email).first() if email else None

        if user:
            token = user.generate_reset_token()
            db.session.commit()
            reset_url = url_for('auth.reset_password', token=token, _external=True)
            send_password_reset_email(user.email, reset_url)
            log_action(user.id, "password_reset_requested")

        # Mismo mensaje exista o no la cuenta -- lo contrario permitiría
        # usar este formulario para averiguar qué emails están registrados
        # (a diferencia del username en /register, que sí se acepta
        # revelar por usabilidad — acá el costo de no revelarlo es bajo y
        # el riesgo de que importe es más alto).
        flash('Si ese email está registrado, te enviamos un enlace para recuperar tu contraseña.', 'info')
        return redirect(url_for('auth.login'))

    return render_template('auth/forgot_password.html')


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
@limiter.limit("10 per hour", methods=["POST"])
def reset_password(token):
    user = User.query.filter_by(reset_token=token).first()
    token_valid = bool(user and user.reset_token_is_valid())

    if not token_valid:
        flash('Ese enlace no es válido o ya venció. Pedí uno nuevo.', 'danger')
        return redirect(url_for('auth.forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        strength_error = password_strength_error(password, user.username)
        if strength_error:
            flash(strength_error, 'danger')
            return render_template('auth/reset_password.html', token=token)

        user.set_password(password)
        user.clear_reset_token()
        db.session.commit()
        log_action(user.id, "password_reset_completed")

        flash('Contraseña actualizada. Ya podés iniciar sesión con la nueva.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/reset_password.html', token=token)


@auth_bp.route('/verify-email/<token>')
@limiter.limit("20 per hour")
def verify_email(token):
    user = User.query.filter_by(email_verify_token=token).first()

    if not user or not user.email_verify_token_is_valid():
        flash('Ese enlace de verificación no es válido o ya venció. Podés pedir uno nuevo desde "Mi cuenta".', 'danger')
        return redirect(url_for('auth.account') if 'user_id' in session else url_for('auth.login'))

    user.email_verified = True
    user.clear_email_verify_token()
    db.session.commit()
    log_action(user.id, "email_verified")

    flash('Email confirmado.', 'success')
    return redirect(url_for('dashboard') if 'user_id' in session else url_for('auth.login'))


@auth_bp.route('/account')
def account():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    user = db.session.get(User, session['user_id'])
    return render_template('auth/account.html', user=user, totp_enabled=user.totp_enabled)


@auth_bp.route('/account/password', methods=['POST'])
@limiter.limit("10 per hour")
def change_password():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    user = db.session.get(User, session['user_id'])
    current_password = request.form.get('current_password', '')
    new_password = request.form.get('new_password', '')

    if not require_current_password(
        user, current_password, "password_change_failed_wrong_password",
        'Contraseña actual incorrecta. No se cambió nada.',
    ):
        return redirect(url_for('auth.account'))

    strength_error = password_strength_error(new_password, user.username)
    if strength_error:
        flash(strength_error, 'danger')
        return redirect(url_for('auth.account'))

    user.set_password(new_password)
    db.session.commit()
    log_action(user.id, "password_changed")
    flash('Contraseña actualizada.', 'success')
    return redirect(url_for('auth.account'))


@auth_bp.route('/account/email', methods=['POST'])
@limiter.limit("10 per hour")
def update_email():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    user = db.session.get(User, session['user_id'])
    current_password = request.form.get('current_password', '')
    new_email = request.form.get('new_email', '').strip().lower()

    if not require_current_password(
        user, current_password, "email_update_failed_wrong_password",
        'Contraseña actual incorrecta. No se cambió nada.',
    ):
        return redirect(url_for('auth.account'))

    if not new_email or not EMAIL_RE.match(new_email):
        flash('Ingresá un email válido.', 'danger')
        return redirect(url_for('auth.account'))

    existing = User.query.filter_by(email=new_email).first()
    if existing and existing.id != user.id:
        flash('Ya existe una cuenta registrada con ese email.', 'danger')
        return redirect(url_for('auth.account'))

    email_changed = new_email != user.email
    user.email = new_email
    if email_changed:
        # El estado verificado no se arrastra de un email al otro -- si se
        # arrastrara, cambiar el email a uno ajeno "heredaría" la confianza
        # que se había ganado con el email anterior.
        user.email_verified = False
        verify_token = user.generate_email_verify_token()
    db.session.commit()
    log_action(user.id, "email_updated", details=new_email)

    if email_changed:
        verify_url = url_for('auth.verify_email', token=verify_token, _external=True)
        send_email_verification_email(user.email, verify_url)
        log_action(user.id, "email_verification_sent")
        flash('Email actualizado. Te enviamos un correo para confirmarlo.', 'success')
    else:
        flash('Email actualizado.', 'success')
    return redirect(url_for('auth.account'))


@auth_bp.route('/account/resend-verification', methods=['POST'])
@limiter.limit("5 per hour")
def resend_verification():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    user = db.session.get(User, session['user_id'])
    if not user.email:
        flash('Agregá un email antes de pedir la verificación.', 'danger')
        return redirect(url_for('auth.account'))
    if user.email_verified:
        flash('Tu email ya está verificado.', 'info')
        return redirect(url_for('auth.account'))

    verify_token = user.generate_email_verify_token()
    db.session.commit()
    verify_url = url_for('auth.verify_email', token=verify_token, _external=True)
    send_email_verification_email(user.email, verify_url)
    log_action(user.id, "email_verification_resent")

    flash('Te reenviamos el correo de verificación.', 'success')
    return redirect(url_for('auth.account'))


@auth_bp.route('/2fa/verify', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=["POST"])
def verify_2fa():
    """Segundo paso del login para cuentas con 2FA activo. Solo accesible
    tras un usuario/contraseña correctos (requiere 'pending_2fa_user_id' en
    sesión, puesto por login()) — no es una ruta alternativa de acceso."""
    pending_user_id = session.get('pending_2fa_user_id')
    if not pending_user_id:
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        user = db.session.get(User, pending_user_id)
        code = request.form.get('code', '')
        valid = False

        if user and user.totp_enabled and user.totp_secret_encrypted:
            secret = decrypt_totp_secret(user.totp_secret_encrypted)
            valid = verify_totp_code(secret, code)

            if not valid:
                valid = verify_and_consume_backup_code(user, code)
                if valid:
                    db.session.commit()
                    log_action(user.id, "2fa_backup_code_used")

        if valid:
            session.pop('pending_2fa_user_id', None)
            session['user_id'] = user.id
            session['username'] = user.username
            log_action(user.id, "2fa_verify_success")
            return redirect(url_for('dashboard'))

        log_action(pending_user_id, "2fa_verify_failed")
        flash('Código incorrecto o expirado.', 'danger')
        return redirect(url_for('auth.verify_2fa'))

    return render_template('auth/verify_2fa.html')


@auth_bp.route('/2fa/setup', methods=['GET', 'POST'])
@limiter.limit("10 per hour", methods=["POST"])
def setup_2fa():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    user = db.session.get(User, session['user_id'])
    if user.totp_enabled:
        flash('La verificación en dos pasos ya está activa en tu cuenta.', 'info')
        return redirect(url_for('auth.account'))

    if request.method == 'POST':
        secret = session.get('pending_totp_secret')
        code = request.form.get('code', '')

        if not secret or not verify_totp_code(secret, code):
            flash('Código incorrecto. Volvé a intentarlo.', 'danger')
            return redirect(url_for('auth.setup_2fa'))

        user.totp_secret_encrypted = encrypt_totp_secret(secret)
        user.totp_enabled = True
        backup_codes = generate_backup_codes()
        user.backup_codes = hash_backup_codes(backup_codes)
        db.session.commit()
        session.pop('pending_totp_secret', None)
        log_action(user.id, "2fa_enabled")

        # Los códigos de respaldo se muestran una única vez, en esta misma
        # respuesta — no se guardan en claro en ningún lado (ni sesión ni
        # base de datos), así que un refresh de esta página ya no los trae.
        return render_template('auth/two_factor_setup.html', backup_codes=backup_codes)

    # Reutilizar el secreto pendiente si ya existe (por ejemplo, si el
    # usuario recargó la página): regenerar uno nuevo en cada GET
    # invalidaría el QR que ya pudo haber escaneado.
    secret = session.get('pending_totp_secret')
    if not secret:
        secret = generate_totp_secret()
        session['pending_totp_secret'] = secret

    uri = get_provisioning_uri(user.username, secret)
    qr_code_base64 = generate_qr_code_base64(uri)

    return render_template(
        'auth/two_factor_setup.html',
        secret=secret,
        qr_code_base64=qr_code_base64,
    )


@auth_bp.route('/2fa/disable', methods=['POST'])
@limiter.limit("10 per hour")
def disable_2fa():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    user = db.session.get(User, session['user_id'])
    password = request.form.get('password', '')

    # Desactivar 2FA es una acción sensible: exige la contraseña actual,
    # igual que cualquier cambio de seguridad de cuenta serio (no basta con
    # tener la sesión abierta).
    if not require_current_password(
        user, password, "2fa_disable_failed_wrong_password",
        'Contraseña incorrecta. No se desactivó la verificación en dos pasos.',
    ):
        return redirect(url_for('auth.account'))

    user.totp_enabled = False
    user.totp_secret_encrypted = None
    user.backup_codes = None
    db.session.commit()
    log_action(user.id, "2fa_disabled")
    flash('Verificación en dos pasos desactivada.', 'success')
    return redirect(url_for('auth.account'))


@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))