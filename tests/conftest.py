import pytest

from app.models import db as _db
from main import create_app

TEST_PASSWORD = "ClaveDePruebaSegura9!"


@pytest.fixture
def app():
    """Una app Flask nueva por test, con SQLite en memoria — nunca toca la
    base de datos real. CSRF y rate-limiting desactivados por defecto: son
    mecanismos ya probados por sus propias librerías, no algo que este
    proyecto necesite volver a demostrar en cada test de negocio."""
    flask_app = create_app(config_overrides={
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "WTF_CSRF_ENABLED": False,
        "RATELIMIT_ENABLED": False,
        # Anulada a propósito: si el .env real tiene FORCE_HTTPS=true (por
        # ejemplo, mientras se prepara/depura un despliegue), Talisman
        # redirige con 302 cualquier request HTTP plana del test client en
        # vez de responder 200 — no es un bug de la app, es el mismo tipo de
        # fuga de config real hacia los tests que ya rompió el aislamiento
        # en otros dos casos (Neon y S3, ver CHANGELOG.md): una variable
        # que debería estar aislada pero no se anulaba explícitamente acá.
        "FORCE_HTTPS": False,
        # Anuladas a propósito: si el .env real tiene credenciales S3
        # configuradas, los tests de la bóveda deben seguir cayendo a disco
        # local igualmente — nunca tocar el almacenamiento externo real.
        "S3_ENDPOINT_URL": None,
        "S3_BUCKET": None,
        "S3_ACCESS_KEY_ID": None,
        "S3_SECRET_ACCESS_KEY": None,
        "S3_REGION": None,
        # Mismo criterio: los tests de recuperación de contraseña mockean
        # send_password_reset_email a nivel de ruta, así que en la práctica
        # nunca se llegaría a llamar a la API de Brevo -- pero se anula
        # igual, explícito, para no depender de esa capa de protección.
        "BREVO_API_KEY": None,
        "BREVO_SENDER_EMAIL": None,
    })

    with flask_app.app_context():
        _db.create_all()
        yield flask_app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def register(client):
    """Registra un usuario vía la ruta real (no directo a la DB), para que
    los tests de otras áreas partan de un usuario creado por el mismo
    camino que usaría alguien de verdad."""
    def _register(username="usuario_prueba", password=TEST_PASSWORD, email=None):
        # El email es obligatorio desde la Fase de recuperación de
        # contraseña -- derivado del username por default para que cada
        # usuario de prueba siga teniendo uno único (email es unique=True).
        if email is None:
            email = f"{username}@test.local"
        return client.post(
            "/register",
            data={"username": username, "password": password, "email": email},
            follow_redirects=True,
        )
    return _register


@pytest.fixture
def login(client):
    def _login(username="usuario_prueba", password=TEST_PASSWORD):
        return client.post(
            "/login",
            data={"username": username, "password": password},
            follow_redirects=True,
        )
    return _login


@pytest.fixture
def logged_in_client(client, register, login):
    """Cliente con una sesión ya iniciada — la mayoría de tests de
    passwords/vault parten de este estado en vez de repetir el
    registro+login en cada uno."""
    register()
    login()
    return client
