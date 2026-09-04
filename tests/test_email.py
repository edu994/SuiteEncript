import requests

from app.utils.email import send_password_reset_email


def test_dev_without_credentials_logs_link_instead_of_failing(app, caplog):
    """FORCE_HTTPS=false (como en los tests) y sin BREVO_*: no debe intentar
    mandar nada por HTTP, solo loguear el enlace para poder probar el flujo
    localmente sin configurar Brevo."""
    with app.app_context():
        app.config["BREVO_API_KEY"] = None
        app.config["BREVO_SENDER_EMAIL"] = None
        with caplog.at_level("WARNING"):
            result = send_password_reset_email("alguien@test.local", "http://localhost/reset-password/abc")
    assert result is True
    assert "http://localhost/reset-password/abc" in caplog.text


def test_prod_without_credentials_fails_without_crashing(app, caplog):
    with app.app_context():
        app.config["FORCE_HTTPS"] = True
        app.config["BREVO_API_KEY"] = None
        app.config["BREVO_SENDER_EMAIL"] = None
        with caplog.at_level("ERROR"):
            result = send_password_reset_email("alguien@test.local", "http://localhost/reset-password/abc")
    assert result is False


def test_configured_sends_via_brevo_api(app, monkeypatch):
    """Nunca pega a la red real ni a Brevo de verdad -- requests.post se
    reemplaza por un doble que solo registra con qué se lo llamó."""
    sent = {}

    class _FakeResponse:
        status_code = 201
        text = '{"messageId": "fake"}'

    def _fake_post(url, json=None, headers=None, timeout=None):
        sent["url"] = url
        sent["json"] = json
        sent["headers"] = headers
        sent["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr(requests, "post", _fake_post)

    with app.app_context():
        app.config["BREVO_API_KEY"] = "clave-de-api-falsa"
        app.config["BREVO_SENDER_EMAIL"] = "cuenta@gmail.com"
        result = send_password_reset_email("destinatario@test.local", "http://localhost/reset-password/xyz")

    assert result is True
    assert sent["url"] == "https://api.brevo.com/v3/smtp/email"
    assert sent["headers"]["api-key"] == "clave-de-api-falsa"
    assert sent["json"]["sender"]["email"] == "cuenta@gmail.com"
    assert sent["json"]["to"] == [{"email": "destinatario@test.local"}]
    assert "http://localhost/reset-password/xyz" in sent["json"]["textContent"]
    assert "http://localhost/reset-password/xyz" in sent["json"]["htmlContent"]
    assert "SuiteEncript" in sent["json"]["htmlContent"]

    # Sin una request activa (este test corre fuera de una), _logo_url()
    # no puede construir una URL absoluta -- el correo debe salir igual,
    # solo sin el logo.
    assert "<img" not in sent["json"]["htmlContent"]


def test_logo_embedded_as_url_when_inside_a_request(client, monkeypatch):
    """Dentro de una request real sí hay contexto para armar la URL absoluta
    del logo -- se prueba disparando /forgot-password de verdad, en vez de
    mockear send_password_reset_email, para que _logo_url() corra con un
    request activo."""

    class _FakeResponse:
        status_code = 201
        text = "{}"

    captured = {}

    def _fake_post(url, json=None, headers=None, timeout=None):
        captured["json"] = json
        return _FakeResponse()

    monkeypatch.setattr(requests, "post", _fake_post)
    client.application.config["BREVO_API_KEY"] = "clave-de-api-falsa"
    client.application.config["BREVO_SENDER_EMAIL"] = "cuenta@gmail.com"

    from app.models import User, db

    with client.application.app_context():
        user = User(username="con_logo", email="con_logo@test.local")
        user.set_password("ClaveDePrueba9!")
        db.session.add(user)
        db.session.commit()

    client.post("/forgot-password", data={"email": "con_logo@test.local"})

    assert "json" in captured
    assert "<img" in captured["json"]["htmlContent"]
    assert "/static/icons/icon-192.png" in captured["json"]["htmlContent"]

    client.application.config["BREVO_API_KEY"] = None
    client.application.config["BREVO_SENDER_EMAIL"] = None


def test_brevo_rejection_is_caught_not_raised(app, monkeypatch):
    class _FakeResponse:
        status_code = 401
        text = '{"message": "Key not found"}'

    monkeypatch.setattr(requests, "post", lambda *a, **k: _FakeResponse())

    with app.app_context():
        app.config["BREVO_API_KEY"] = "clave-de-api-falsa"
        app.config["BREVO_SENDER_EMAIL"] = "cuenta@gmail.com"
        result = send_password_reset_email("destinatario@test.local", "http://localhost/reset-password/xyz")

    assert result is False


def test_network_failure_is_caught_not_raised(app, monkeypatch):
    def _raise(*a, **k):
        raise requests.exceptions.ConnectionError("no se pudo conectar")

    monkeypatch.setattr(requests, "post", _raise)

    with app.app_context():
        app.config["BREVO_API_KEY"] = "clave-de-api-falsa"
        app.config["BREVO_SENDER_EMAIL"] = "cuenta@gmail.com"
        result = send_password_reset_email("destinatario@test.local", "http://localhost/reset-password/xyz")

    assert result is False
