import types

import pyotp
from conftest import TEST_PASSWORD

from app.models import User
from app.utils.totp import (
    decrypt_totp_secret,
    encrypt_totp_secret,
    generate_backup_codes,
    generate_totp_secret,
    hash_backup_codes,
    verify_and_consume_backup_code,
    verify_totp_code,
)

# ---------- Unidad: app/utils/totp.py ----------

def test_generate_totp_secret_produces_valid_base32():
    secret = generate_totp_secret()
    # Si no fuera base32 válido, esto lanzaría una excepción.
    pyotp.TOTP(secret).now()


def test_verify_totp_code_accepts_current_code():
    secret = generate_totp_secret()
    code = pyotp.TOTP(secret).now()
    assert verify_totp_code(secret, code) is True


def test_verify_totp_code_rejects_wrong_code():
    secret = generate_totp_secret()
    assert verify_totp_code(secret, "000000") is False


def test_verify_totp_code_rejects_malformed_input():
    secret = generate_totp_secret()
    assert verify_totp_code(secret, "abcdef") is False
    assert verify_totp_code(secret, "") is False
    assert verify_totp_code(secret, None) is False
    assert verify_totp_code(None, "123456") is False


def test_totp_secret_encryption_roundtrip():
    secret = generate_totp_secret()
    encrypted = encrypt_totp_secret(secret)
    assert secret not in encrypted  # nunca queda en claro
    assert decrypt_totp_secret(encrypted) == secret


def test_generate_backup_codes_are_unique_and_formatted():
    codes = generate_backup_codes(count=8)
    assert len(codes) == 8
    assert len(set(codes)) == 8  # todos distintos
    for code in codes:
        assert len(code) == 9  # formato XXXX-XXXX
        assert code[4] == "-"


def test_backup_code_is_single_use():
    fake_user = types.SimpleNamespace(backup_codes=None)
    codes = generate_backup_codes(count=3)
    fake_user.backup_codes = hash_backup_codes(codes)

    # El primer uso de un código válido funciona...
    assert verify_and_consume_backup_code(fake_user, codes[0]) is True
    # ...pero reutilizarlo ya no.
    assert verify_and_consume_backup_code(fake_user, codes[0]) is False
    # Los demás siguen intactos.
    assert verify_and_consume_backup_code(fake_user, codes[1]) is True


def test_backup_code_check_is_case_insensitive():
    fake_user = types.SimpleNamespace(backup_codes=None)
    codes = generate_backup_codes(count=1)
    fake_user.backup_codes = hash_backup_codes(codes)
    assert verify_and_consume_backup_code(fake_user, codes[0].lower()) is True


def test_backup_code_rejects_unknown_code():
    fake_user = types.SimpleNamespace(backup_codes=None)
    fake_user.backup_codes = hash_backup_codes(generate_backup_codes(count=2))
    assert verify_and_consume_backup_code(fake_user, "0000-0000") is False


# ---------- Integración: rutas de app/routes/auth.py ----------

def _get_pending_secret(client):
    client.get("/2fa/setup")
    with client.session_transaction() as sess:
        return sess["pending_totp_secret"]


def _enable_2fa(client):
    secret = _get_pending_secret(client)
    code = pyotp.TOTP(secret).now()
    response = client.post("/2fa/setup", data={"code": code}, follow_redirects=True)
    assert response.status_code == 200
    return secret


def test_setup_2fa_page_shows_qr(logged_in_client):
    response = logged_in_client.get("/2fa/setup")
    assert response.status_code == 200
    assert b"data:image/png;base64," in response.data


def test_setup_2fa_rejects_wrong_code(logged_in_client, app):
    _get_pending_secret(logged_in_client)
    logged_in_client.post("/2fa/setup", data={"code": "000000"}, follow_redirects=True)
    with app.app_context():
        user = User.query.filter_by(username="usuario_prueba").first()
        assert user.totp_enabled is False


def test_setup_2fa_enables_account_and_encrypts_secret(logged_in_client, app):
    secret = _enable_2fa(logged_in_client)
    with app.app_context():
        user = User.query.filter_by(username="usuario_prueba").first()
        assert user.totp_enabled is True
        assert user.totp_secret_encrypted is not None
        assert secret not in user.totp_secret_encrypted  # nunca en claro
        assert user.backup_codes is not None


def test_login_with_2fa_enabled_requires_verification_step(client, register, login):
    register(username="con_2fa")
    login(username="con_2fa")
    _enable_2fa(client)
    client.get("/logout")

    response = login(username="con_2fa")
    assert response.status_code == 200
    with client.session_transaction() as sess:
        assert "user_id" not in sess
        assert sess.get("pending_2fa_user_id") is not None


def test_login_with_2fa_completes_with_correct_code(client, register, login):
    register(username="con_2fa_ok")
    login(username="con_2fa_ok")
    secret = _enable_2fa(client)
    client.get("/logout")
    login(username="con_2fa_ok")

    valid_code = pyotp.TOTP(secret).now()
    response = client.post("/2fa/verify", data={"code": valid_code}, follow_redirects=True)
    assert response.status_code == 200
    with client.session_transaction() as sess:
        assert sess.get("username") == "con_2fa_ok"
        assert "pending_2fa_user_id" not in sess


def test_login_with_2fa_wrong_code_does_not_open_session(client, register, login):
    register(username="con_2fa_mal")
    login(username="con_2fa_mal")
    _enable_2fa(client)
    client.get("/logout")
    login(username="con_2fa_mal")

    client.post("/2fa/verify", data={"code": "000000"}, follow_redirects=True)
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_verify_2fa_unreachable_without_pending_login(client):
    response = client.get("/2fa/verify", follow_redirects=True)
    # Sin haber pasado usuario/contraseña antes, se redirige a login.
    assert response.status_code == 200
    assert b"Acceder a tu cuenta" in response.data


def test_disable_2fa_requires_correct_password(logged_in_client, app):
    _enable_2fa(logged_in_client)

    logged_in_client.post("/2fa/disable", data={"password": "incorrecta"}, follow_redirects=True)
    with app.app_context():
        user = User.query.filter_by(username="usuario_prueba").first()
        assert user.totp_enabled is True  # sigue activo

    logged_in_client.post("/2fa/disable", data={"password": TEST_PASSWORD}, follow_redirects=True)
    with app.app_context():
        user = User.query.filter_by(username="usuario_prueba").first()
        assert user.totp_enabled is False
        assert user.totp_secret_encrypted is None
        assert user.backup_codes is None
