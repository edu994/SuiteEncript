import os
from typing import ClassVar


def _get_secret_key() -> str:
    key = os.environ.get("SECRET_KEY")
    if key:
        return key
    if os.environ.get("FORCE_HTTPS", "false").lower() == "true":
        raise RuntimeError(
            "SECRET_KEY no está definida en el entorno. En producción "
            "(FORCE_HTTPS=true) esto es obligatorio: sin ella, cualquiera "
            "podría falsificar sesiones y tokens CSRF."
        )
    return "clave_secreta_desarrollo"


class Config:
    SECRET_KEY = _get_secret_key()
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "SQLALCHEMY_DATABASE_URI", "sqlite:///suiteencript.db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # pool_pre_ping: antes de prestar una conexión del pool, SQLAlchemy le
    # manda un "SELECT 1" barato y la descarta/reconecta sola si está
    # muerta -- sin esto, la primera consulta contra una conexión que el
    # servidor ya cerró del otro lado (por idle timeout) explota con un
    # OperationalError sin manejar → 500, y recién la siguiente petición
    # (que abre una conexión nueva) funciona. Es exactamente el patrón que
    # se veía en /login: fallaba una vez con 500, funcionaba al reintentar
    # con las mismas credenciales. Neon (producción) cierra conexiones
    # idle agresivamente por ser serverless, así que ahí es todavía más
    # probable que localmente contra el Postgres de docker-compose.
    # pool_recycle=280 además descarta proactivamente cualquier conexión
    # de más de ~4.5 minutos, antes de que el servidor la cierre él mismo.
    SQLALCHEMY_ENGINE_OPTIONS: ClassVar[dict] = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
    }
    # Límite de tamaño de subida (bóveda de archivos): 50 MB. Sin esto,
    # una petición con un archivo gigante se leería entera en memoria
    # antes de poder rechazarla (riesgo de DoS).
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024

    # Cookie de sesión: no accesible desde JS, no enviada en navegación
    # cross-site, y solo por HTTPS cuando FORCE_HTTPS esté activo (producción).
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    FORCE_HTTPS = os.environ.get("FORCE_HTTPS", "false").lower() == "true"
    SESSION_COOKIE_SECURE = FORCE_HTTPS

    # Backend de Flask-Limiter para los contadores de rate-limiting.
    # "memory://" (default) alcanza para un solo proceso/worker — deja de
    # ser válido en cuanto hay más de un worker de gunicorn, porque cada
    # uno llevaría su propio contador en memoria y el límite real terminaría
    # siendo (límite configurado × cantidad de workers). Redis comparte los
    # contadores entre procesos; docker-compose.yml ya trae un servicio
    # "redis" y fija esta variable a redis://redis:6379/0 para el contenedor
    # de la app. Fuera de Docker (python main.py directo) sigue en memoria
    # salvo que se defina la variable de entorno a mano.
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")

    # Almacenamiento S3-compatible para la bóveda de archivos (opcional: si
    # falta cualquiera de estas, app/utils/storage.py cae a disco local).
    # Se leen aquí, a través de app.config, y no directamente de os.environ
    # dentro de storage.py — así tests/conftest.py puede desactivarlas con
    # config_overrides sin que dependan del entorno real del proceso que
    # ejecuta pytest (ver la nota en app/utils/storage.py; leerlas de
    # os.environ directo fue justamente lo que hizo que un test mal aislado
    # tocara Neon real en otro módulo — ver CHANGELOG.md). Proveedor usado
    # en este proyecto: Supabase Storage (Cloudflare R2 exige tarjeta antes
    # de dar acceso a la API).
    S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL")
    S3_BUCKET = os.environ.get("S3_BUCKET")
    S3_ACCESS_KEY_ID = os.environ.get("S3_ACCESS_KEY_ID")
    S3_SECRET_ACCESS_KEY = os.environ.get("S3_SECRET_ACCESS_KEY")
    S3_REGION = os.environ.get("S3_REGION")

    # Envío de correo (recuperación de contraseña) vía la API HTTP de Brevo
    # -- ver app/utils/email.py. Reemplaza a Gmail SMTP: Render bloquea la
    # salida a los puertos SMTP (25/465/587) en el plan gratuito desde
    # 2025-09, así que solo un envío por HTTPS (puerto 443, nunca bloqueado)
    # funciona ahí. Opcional: si faltan, en dev el enlace de recuperación se
    # loguea en vez de enviarse; en producción (FORCE_HTTPS=true) el correo
    # simplemente no sale y queda registrado como error en los logs, no un
    # fallo fuerte al arrancar la app (a diferencia de SECRET_KEY/
    # VAULT_MASTER_KEY, esto no compromete datos ya cifrados si falta).
    BREVO_API_KEY = os.environ.get("BREVO_API_KEY")
    BREVO_SENDER_EMAIL = os.environ.get("BREVO_SENDER_EMAIL")
