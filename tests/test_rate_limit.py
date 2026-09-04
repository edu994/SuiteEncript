import io

from app.extensions import limiter
from app.models import EncryptedFile, db
from main import create_app


def test_login_is_rate_limited_after_too_many_attempts():
    """No reutiliza el fixture `app` compartido: ese se crea con
    RATELIMIT_ENABLED=False para no ensuciar el resto de la suite, y
    cambiar app.config *después* de crear la app no tiene efecto (Flask-
    Limiter, igual que SQLAlchemy, fija su configuración en el momento de
    init_app()). Este test arma su propia app con el valor correcto desde
    el inicio."""
    app = create_app(config_overrides={
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "WTF_CSRF_ENABLED": False,
        "RATELIMIT_ENABLED": True,
        # Explícito para no depender de si el entorno donde corre la suite
        # tiene RATELIMIT_STORAGE_URI apuntando a un Redis real (Fase 7) —
        # este test es sobre la lógica de límite, no sobre el backend.
        "RATELIMIT_STORAGE_URI": "memory://",
        # Ver la nota en tests/conftest.py: si el .env real tiene
        # FORCE_HTTPS=true, Talisman redirige con 302 cualquier request
        # HTTP plana del test client en vez de responder normalmente.
        "FORCE_HTTPS": False,
    })
    with app.app_context():
        db.create_all()
        client = app.test_client()
        limiter.reset()
        try:
            for _ in range(5):
                client.post(
                    "/login",
                    data={"username": "quien-sea", "password": "incorrecta"},
                )
            response = client.post(
                "/login",
                data={"username": "quien-sea", "password": "incorrecta"},
            )
            assert response.status_code == 429
        finally:
            limiter.reset()
            db.session.remove()
            db.drop_all()


def test_shared_download_password_is_rate_limited():
    """El token de un enlace compartido ya es un secreto de 256 bits
    inadivinable, pero si además tiene share_password, ese segundo secreto
    es mucho más corto — sin límite se podría probar por fuerza bruta."""
    app = create_app(config_overrides={
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "WTF_CSRF_ENABLED": False,
        "RATELIMIT_ENABLED": True,
        "RATELIMIT_STORAGE_URI": "memory://",
        # Ver la nota en tests/conftest.py: si el .env real tiene
        # FORCE_HTTPS=true, Talisman redirige con 302 cualquier request
        # HTTP plana del test client en vez de responder normalmente.
        "FORCE_HTTPS": False,
    })
    with app.app_context():
        db.create_all()
        client = app.test_client()
        limiter.reset()
        try:
            client.post(
                "/register",
                data={"username": "dueno_share", "password": "ClaveDePruebaSegura9!", "email": "dueno_share@test.local"},
                follow_redirects=True,
            )
            client.post(
                "/login",
                data={"username": "dueno_share", "password": "ClaveDePruebaSegura9!"},
                follow_redirects=True,
            )
            client.post(
                "/vault/upload",
                data={
                    "file": (io.BytesIO(b"contenido de prueba"), "documento.txt"),
                    "enable_share": "on",
                    "share_password": "secreto-de-descarga",
                },
                content_type="multipart/form-data",
                follow_redirects=True,
            )
            archivo = EncryptedFile.query.first()
            token = archivo.share_token

            for _ in range(10):
                client.post(f"/vault/share/{token}", data={"password": "incorrecta"})
            response = client.post(f"/vault/share/{token}", data={"password": "incorrecta"})
            assert response.status_code == 429
        finally:
            limiter.reset()
            db.session.remove()
            db.drop_all()


def test_vault_upload_is_rate_limited():
    """/vault/upload no tenía límite propio, solo mitigado por requerir
    sesión iniciada."""
    app = create_app(config_overrides={
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "WTF_CSRF_ENABLED": False,
        "RATELIMIT_ENABLED": True,
        "RATELIMIT_STORAGE_URI": "memory://",
        # Ver la nota en tests/conftest.py: si el .env real tiene
        # FORCE_HTTPS=true, Talisman redirige con 302 cualquier request
        # HTTP plana del test client en vez de responder normalmente.
        "FORCE_HTTPS": False,
    })
    with app.app_context():
        db.create_all()
        client = app.test_client()
        limiter.reset()
        try:
            client.post(
                "/register",
                data={"username": "subidor_masivo", "password": "ClaveDePruebaSegura9!", "email": "subidor_masivo@test.local"},
                follow_redirects=True,
            )
            client.post(
                "/login",
                data={"username": "subidor_masivo", "password": "ClaveDePruebaSegura9!"},
                follow_redirects=True,
            )
            for _ in range(20):
                client.post(
                    "/vault/upload",
                    data={"file": (io.BytesIO(b"contenido"), "archivo.txt")},
                    content_type="multipart/form-data",
                )
            response = client.post(
                "/vault/upload",
                data={"file": (io.BytesIO(b"contenido"), "archivo.txt")},
                content_type="multipart/form-data",
            )
            assert response.status_code == 429
        finally:
            limiter.reset()
            db.session.remove()
            db.drop_all()


def test_passwords_add_is_rate_limited():
    """Mismo backlog: /passwords (agregar) no tenía límite propio."""
    app = create_app(config_overrides={
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "WTF_CSRF_ENABLED": False,
        "RATELIMIT_ENABLED": True,
        "RATELIMIT_STORAGE_URI": "memory://",
        # Ver la nota en tests/conftest.py: si el .env real tiene
        # FORCE_HTTPS=true, Talisman redirige con 302 cualquier request
        # HTTP plana del test client en vez de responder normalmente.
        "FORCE_HTTPS": False,
    })
    with app.app_context():
        db.create_all()
        client = app.test_client()
        limiter.reset()
        try:
            client.post(
                "/register",
                data={"username": "guardador_masivo", "password": "ClaveDePruebaSegura9!", "email": "guardador_masivo@test.local"},
                follow_redirects=True,
            )
            client.post(
                "/login",
                data={"username": "guardador_masivo", "password": "ClaveDePruebaSegura9!"},
                follow_redirects=True,
            )
            for _ in range(30):
                client.post(
                    "/passwords",
                    data={"sitio": "ejemplo.com", "usuario_sitio": "yo", "contrasena": "Clave123!"},
                )
            response = client.post(
                "/passwords",
                data={"sitio": "ejemplo.com", "usuario_sitio": "yo", "contrasena": "Clave123!"},
            )
            assert response.status_code == 429
        finally:
            limiter.reset()
            db.session.remove()
            db.drop_all()
