import os

from dotenv import load_dotenv

load_dotenv()

from flask import (
    Flask,
    redirect,
    render_template,
    send_from_directory,
    session,
    url_for,
)
from flask_migrate import Migrate
from sqlalchemy import func
from werkzeug.middleware.proxy_fix import ProxyFix

from app.config import Config
from app.extensions import CONTENT_SECURITY_POLICY, csrf, limiter, talisman
from app.models import EncryptedFile, Password, User, db
from app.routes.auth import auth_bp
from app.routes.passwords import passwords_bp
from app.routes.tools import tools_bp
from app.routes.vault import MAX_USER_STORAGE_BYTES, vault_bp
from app.utils.logging_config import configure_logging
from app.utils.news_feed import get_security_news


def create_app(config_overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    # Debe aplicarse ANTES de db.init_app(): Flask-SQLAlchemy arma la
    # conexión en el momento en que se llama init_app(), usando el valor de
    # SQLALCHEMY_DATABASE_URI que haya en ese instante — cambiarlo en
    # app.config después ya no tiene efecto, la conexión queda fija. Este
    # parámetro existe para que los tests (tests/conftest.py) puedan apuntar
    # a SQLite en memoria de forma confiable, en vez de terminar conectados
    # a la base de datos real sin que nadie lo note.
    if config_overrides:
        app.config.update(config_overrides)

    # Logging estructurado (JSON a stdout) + Sentry opcional si SENTRY_DSN
    # está configurada — ver app/utils/logging_config.py (Fase 9). Temprano
    # a propósito, para que cualquier cosa que falle en la inicialización de
    # abajo (DB, extensiones) ya tenga a dónde loguearse.
    configure_logging(app)

    # Confía en las cabeceras X-Forwarded-* que agrega el proxy de la
    # plataforma (Render). Sin esto, la app cree que toda petición llega
    # por HTTP plano (así es como se la reenvía el proxy puertas adentro)
    # y, con FORCE_HTTPS=true, Talisman la redirige a HTTPS en un bucle
    # infinito: el proxy vuelve a mandarla en HTTP y Talisman vuelve a
    # redirigir. x_proto=1 confía en un único proxy por delante (el de
    # Render); si algún día hay más de un proxy en cadena, hay que subir
    # este número al que corresponda.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_for=1)

    db.init_app(app)
    # A partir de ahora, los cambios de esquema (tablas/columnas nuevas) se
    # aplican con `flask db upgrade`, no con db.create_all(). Tener los dos
    # mecanismos activos a la vez es justo lo que causó el bug de created_at:
    # create_all() nunca avisa cuando el modelo y la base de datos real se
    # desincronizan, solo crea tablas nuevas y calla sobre las existentes.
    Migrate(app, db)

    csrf.init_app(app)
    limiter.init_app(app)
    talisman.init_app(
        app,
        force_https=app.config["FORCE_HTTPS"],
        # Talisman trae su propio default para esto (True), independiente
        # de force_https — sin pasarlo explícito, marcaba la cookie de
        # sesión como Secure incluso con FORCE_HTTPS=false, y un cliente
        # HTTP real (no el test_client(), que es más permisivo) se niega a
        # reenviar una cookie Secure por HTTP plano. Rompía el login en
        # Docker local; nunca se notó antes porque solo se había probado
        # con app.test_client().
        session_cookie_secure=app.config["FORCE_HTTPS"],
        content_security_policy=CONTENT_SECURITY_POLICY,
    )

    # Registrar Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(passwords_bp)
    app.register_blueprint(vault_bp)
    app.register_blueprint(tools_bp)

    # Landing pública: si ya hay sesión, directo al dashboard.
    @app.route("/")
    def index():
        if "user_id" in session:
            return redirect(url_for("dashboard"))
        return render_template("index.html", news=get_security_news())

    @app.route("/dashboard")
    def dashboard():
        if "user_id" not in session:
            return redirect(url_for("auth.login"))
        user = db.session.get(User, session["user_id"])
        if not user:
            return redirect(url_for("auth.login"))

        password_count = Password.query.filter_by(user_id=user.id).count()
        file_count = EncryptedFile.query.filter_by(user_id=user.id).count()
        used_bytes = db.session.query(func.sum(EncryptedFile.file_size_bytes)).filter_by(
            user_id=user.id
        ).scalar() or 0

        return render_template(
            "dashboard.html",
            totp_enabled=user.totp_enabled,
            password_count=password_count,
            file_count=file_count,
            used_mb=round(used_bytes / (1024 * 1024), 1),
            quota_mb=MAX_USER_STORAGE_BYTES // (1024 * 1024),
        )

    @app.route("/service-worker.js")
    def service_worker():
        # Servido desde la raíz (no bajo /static/) a propósito: el alcance
        # por defecto de un service worker es el directorio de la URL desde
        # donde se lo registra — si viviera solo en /static/service-worker.js,
        # no podría cubrir "/" (el start_url del manifest), y algunos
        # navegadores no ofrecerían "instalar la app" sin eso. El archivo
        # físico sigue viviendo en static/ (ver app/../static/service-worker.js)
        # para mantener los assets organizados en un solo lugar; esta ruta
        # solo lo expone en la URL que necesita.
        return send_from_directory(
            app.static_folder, "service-worker.js", mimetype="application/javascript"
        )

    @app.route("/robots.txt")
    def robots_txt():
        # Igual criterio que /service-worker.js: los crawlers solo buscan
        # este archivo en la raíz real del sitio, nunca bajo /static/.
        # Bloquea el rastreo de rutas autenticadas y de recuperación de
        # contraseña -- sin valor de SEO, y /reset-password/<token> lleva
        # un secreto en la propia URL que no debería terminar indexado.
        return send_from_directory(
            app.static_folder, "robots.txt", mimetype="text/plain"
        )

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(_error):
        # exc_info=True toma la excepción real del contexto actual (Flask
        # invoca este handler todavía dentro del except) — sin esto, el log
        # solo diría "Error no manejado" sin traceback, inútil para
        # investigar un fallo en producción sin acceso directo al servidor.
        # ruff (LOG014) no puede ver que esto sigue estando dentro de un
        # except de Flask (el except vive en su despachador, no acá).
        app.logger.error("Error no manejado", exc_info=True)  # noqa: LOG014
        return render_template("errors/500.html"), 500

    return app

app = create_app()

if __name__ == "__main__":
    debug_mode = os.environ.get("FORCE_HTTPS", "false").lower() != "true"
    app.run(debug=debug_mode, host="0.0.0.0", port=5000)  # nosec B104 — necesario dentro de Docker (mismo bind que gunicorn en el Dockerfile), no expone nada que el firewall/plataforma no controle ya
