from conftest import TEST_PASSWORD

import app.routes.auth as auth_module
from app.models import User, db


def _capture_sent_emails(monkeypatch):
    """Reemplaza send_password_reset_email por un doble que nunca toca la
    red real (ni siquiera SMTP) -- solo registra con qué se lo llamó."""
    sent = []

    def _fake_send(to_email, reset_url):
        sent.append({"to": to_email, "url": reset_url})
        return True

    monkeypatch.setattr(auth_module, "send_password_reset_email", _fake_send)
    return sent


def test_forgot_password_sends_email_for_known_account(client, register, app, monkeypatch):
    sent = _capture_sent_emails(monkeypatch)
    register(username="con_email", email="con_email@test.local")

    response = client.post(
        "/forgot-password",
        data={"email": "con_email@test.local"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert len(sent) == 1
    assert sent[0]["to"] == "con_email@test.local"
    assert "/reset-password/" in sent[0]["url"]

    with app.app_context():
        user = User.query.filter_by(username="con_email").first()
        assert user.reset_token is not None
        assert user.reset_token in sent[0]["url"]


def test_forgot_password_same_response_for_unknown_email(client, monkeypatch):
    """No debe revelar si el email existe o no -- mismo mensaje en ambos
    casos, y no se envía nada para un email que no está registrado."""
    sent = _capture_sent_emails(monkeypatch)

    response = client.post(
        "/forgot-password",
        data={"email": "nadie@test.local"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Si ese email está registrado" in response.get_data(as_text=True)
    assert len(sent) == 0


def test_reset_password_with_valid_token_changes_password(client, register, login, app, monkeypatch):
    sent = _capture_sent_emails(monkeypatch)
    register(username="recupera_clave", email="recupera_clave@test.local")
    client.post("/forgot-password", data={"email": "recupera_clave@test.local"})
    token = sent[0]["url"].rsplit("/", 1)[-1]

    nueva_clave = "OtraClaveSegura9!"
    response = client.post(
        f"/reset-password/{token}",
        data={"password": nueva_clave},
        follow_redirects=True,
    )
    assert response.status_code == 200

    # La contraseña vieja ya no debe funcionar, la nueva sí.
    fail_login = login(username="recupera_clave", password=TEST_PASSWORD)
    assert b"incorrectos" in fail_login.data

    ok_login = login(username="recupera_clave", password=nueva_clave)
    with client.session_transaction() as sess:
        assert sess.get("username") == "recupera_clave"
    assert ok_login.status_code == 200


def test_reset_password_token_is_single_use(client, register, app, monkeypatch):
    sent = _capture_sent_emails(monkeypatch)
    register(username="token_unico", email="token_unico@test.local")
    client.post("/forgot-password", data={"email": "token_unico@test.local"})
    token = sent[0]["url"].rsplit("/", 1)[-1]

    client.post(f"/reset-password/{token}", data={"password": "PrimerCambio9!"}, follow_redirects=True)

    # Reusar el mismo token una segunda vez no debe funcionar.
    response = client.post(
        f"/reset-password/{token}",
        data={"password": "SegundoCambio9!"},
        follow_redirects=True,
    )
    assert "no es válido o ya venció" in response.get_data(as_text=True)


def test_reset_password_rejects_unknown_token(client):
    response = client.get("/reset-password/token-que-no-existe", follow_redirects=True)
    assert "no es válido o ya venció" in response.get_data(as_text=True)


def test_reset_password_rejects_expired_token(client, register, app, monkeypatch):
    from datetime import datetime, timedelta, timezone

    sent = _capture_sent_emails(monkeypatch)
    register(username="token_vencido", email="token_vencido@test.local")
    client.post("/forgot-password", data={"email": "token_vencido@test.local"})
    token = sent[0]["url"].rsplit("/", 1)[-1]

    with app.app_context():
        user = User.query.filter_by(username="token_vencido").first()
        user.reset_token_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.session.commit()

    response = client.get(f"/reset-password/{token}", follow_redirects=True)
    assert "no es válido o ya venció" in response.get_data(as_text=True)


def test_reset_password_still_enforces_password_strength(client, register, app, monkeypatch):
    sent = _capture_sent_emails(monkeypatch)
    register(username="quiere_clave_debil", email="quiere_clave_debil@test.local")
    client.post("/forgot-password", data={"email": "quiere_clave_debil@test.local"})
    token = sent[0]["url"].rsplit("/", 1)[-1]

    client.post(f"/reset-password/{token}", data={"password": "123"}, follow_redirects=True)

    with app.app_context():
        user = User.query.filter_by(username="quiere_clave_debil").first()
        # El token sigue intacto: el intento con contraseña débil no lo consumió.
        assert user.reset_token is not None
