from datetime import datetime, timedelta, timezone

from conftest import TEST_PASSWORD

import app.routes.auth as auth_module
from app.models import User, db


def _capture_sent_emails(monkeypatch):
    """Reemplaza send_email_verification_email por un doble que nunca toca
    la red real -- mismo criterio que _capture_sent_emails en
    test_password_reset.py."""
    sent = []

    def _fake_send(to_email, verify_url):
        sent.append({"to": to_email, "url": verify_url})
        return True

    monkeypatch.setattr(auth_module, "send_email_verification_email", _fake_send)
    return sent


def test_register_sends_verification_email(client, register, app, monkeypatch):
    sent = _capture_sent_emails(monkeypatch)
    register(username="nuevo_verifica", email="nuevo_verifica@test.local")

    assert len(sent) == 1
    assert sent[0]["to"] == "nuevo_verifica@test.local"
    assert "/verify-email/" in sent[0]["url"]

    with app.app_context():
        user = User.query.filter_by(username="nuevo_verifica").first()
        assert user.email_verified is False
        assert user.email_verify_token is not None
        assert user.email_verify_token in sent[0]["url"]


def test_verify_email_with_valid_token_marks_verified(client, register, app, monkeypatch):
    sent = _capture_sent_emails(monkeypatch)
    register(username="confirma_email", email="confirma_email@test.local")
    token = sent[0]["url"].rsplit("/", 1)[-1]

    response = client.get(f"/verify-email/{token}", follow_redirects=True)
    assert response.status_code == 200
    assert "Email confirmado" in response.get_data(as_text=True)

    with app.app_context():
        user = User.query.filter_by(username="confirma_email").first()
        assert user.email_verified is True
        assert user.email_verify_token is None


def test_verify_email_rejects_unknown_token(client):
    response = client.get("/verify-email/token-que-no-existe", follow_redirects=True)
    assert "no es válido o ya venció" in response.get_data(as_text=True)


def test_verify_email_rejects_expired_token(client, register, app, monkeypatch):
    sent = _capture_sent_emails(monkeypatch)
    register(username="verifica_vencido", email="verifica_vencido@test.local")
    token = sent[0]["url"].rsplit("/", 1)[-1]

    with app.app_context():
        user = User.query.filter_by(username="verifica_vencido").first()
        user.email_verify_token_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.session.commit()

    response = client.get(f"/verify-email/{token}", follow_redirects=True)
    assert "no es válido o ya venció" in response.get_data(as_text=True)

    with app.app_context():
        user = User.query.filter_by(username="verifica_vencido").first()
        assert user.email_verified is False


def test_verify_email_token_is_single_use(client, register, app, monkeypatch):
    sent = _capture_sent_emails(monkeypatch)
    register(username="token_email_unico", email="token_email_unico@test.local")
    token = sent[0]["url"].rsplit("/", 1)[-1]

    client.get(f"/verify-email/{token}", follow_redirects=True)
    response = client.get(f"/verify-email/{token}", follow_redirects=True)
    assert "no es válido o ya venció" in response.get_data(as_text=True)


def test_resend_verification_requires_login(client):
    response = client.post("/account/resend-verification", follow_redirects=True)
    assert b"Acceder a tu cuenta" in response.data


def test_resend_verification_sends_new_token(logged_in_client, app, monkeypatch):
    sent = _capture_sent_emails(monkeypatch)

    with app.app_context():
        old_token = User.query.filter_by(username="usuario_prueba").first().email_verify_token

    response = logged_in_client.post("/account/resend-verification", follow_redirects=True)
    assert response.status_code == 200
    assert "Te reenviamos el correo" in response.get_data(as_text=True)
    assert len(sent) == 1

    with app.app_context():
        user = User.query.filter_by(username="usuario_prueba").first()
        assert user.email_verify_token is not None
        assert user.email_verify_token != old_token


def test_resend_verification_noop_if_already_verified(logged_in_client, app):
    with app.app_context():
        user = User.query.filter_by(username="usuario_prueba").first()
        user.email_verified = True
        db.session.commit()

    response = logged_in_client.post("/account/resend-verification", follow_redirects=True)
    assert "ya está verificado" in response.get_data(as_text=True)


def test_changing_email_resets_verified_status_and_sends_new_verification(logged_in_client, app, monkeypatch):
    sent = _capture_sent_emails(monkeypatch)

    with app.app_context():
        user = User.query.filter_by(username="usuario_prueba").first()
        user.email_verified = True
        db.session.commit()

    response = logged_in_client.post(
        "/account/email",
        data={"current_password": TEST_PASSWORD, "new_email": "email_nuevo@test.local"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert len(sent) == 1
    assert sent[0]["to"] == "email_nuevo@test.local"

    with app.app_context():
        user = User.query.filter_by(username="usuario_prueba").first()
        assert user.email == "email_nuevo@test.local"
        assert user.email_verified is False
        assert user.email_verify_token is not None


def test_keeping_same_email_does_not_reset_verified_status(logged_in_client, app, monkeypatch):
    sent = _capture_sent_emails(monkeypatch)

    with app.app_context():
        user = User.query.filter_by(username="usuario_prueba").first()
        user.email_verified = True
        db.session.commit()

    logged_in_client.post(
        "/account/email",
        data={"current_password": TEST_PASSWORD, "new_email": "usuario_prueba@test.local"},
        follow_redirects=True,
    )

    assert len(sent) == 0
    with app.app_context():
        user = User.query.filter_by(username="usuario_prueba").first()
        assert user.email_verified is True
