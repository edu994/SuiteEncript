from conftest import TEST_PASSWORD

from app.models import User


def test_account_page_requires_login(client):
    response = client.get("/account", follow_redirects=True)
    assert b"Acceder a tu cuenta" in response.data


def test_account_page_shows_username_and_email(logged_in_client):
    response = logged_in_client.get("/account")
    assert response.status_code == 200
    assert b"usuario_prueba" in response.data
    assert b"usuario_prueba@test.local" in response.data


def test_change_password_requires_correct_current_password(logged_in_client, app):
    response = logged_in_client.post(
        "/account/password",
        data={"current_password": "incorrecta", "new_password": "OtraClaveNueva9!"},
        follow_redirects=True,
    )
    assert b"incorrecta" in response.data

    with app.app_context():
        user = User.query.filter_by(username="usuario_prueba").first()
        assert user.check_password(TEST_PASSWORD)  # no cambió


def test_change_password_rejects_weak_new_password(logged_in_client, app):
    logged_in_client.post(
        "/account/password",
        data={"current_password": TEST_PASSWORD, "new_password": "123"},
        follow_redirects=True,
    )
    with app.app_context():
        user = User.query.filter_by(username="usuario_prueba").first()
        assert user.check_password(TEST_PASSWORD)  # no cambió


def test_change_password_succeeds_and_new_password_works_on_next_login(client, register, login):
    register(username="cambia_clave")
    login(username="cambia_clave")

    nueva_clave = "ClaveNuevaSegura9!"
    response = client.post(
        "/account/password",
        data={"current_password": TEST_PASSWORD, "new_password": nueva_clave},
        follow_redirects=True,
    )
    assert response.status_code == 200

    client.get("/logout")

    fail_login = login(username="cambia_clave", password=TEST_PASSWORD)
    assert b"incorrectos" in fail_login.data

    ok_login = login(username="cambia_clave", password=nueva_clave)
    with client.session_transaction() as sess:
        assert sess.get("username") == "cambia_clave"
    assert ok_login.status_code == 200


def test_update_email_requires_correct_current_password(logged_in_client, app):
    logged_in_client.post(
        "/account/email",
        data={"current_password": "incorrecta", "new_email": "nuevo@test.local"},
        follow_redirects=True,
    )
    with app.app_context():
        user = User.query.filter_by(username="usuario_prueba").first()
        assert user.email == "usuario_prueba@test.local"  # no cambió


def test_update_email_rejects_invalid_format(logged_in_client, app):
    logged_in_client.post(
        "/account/email",
        data={"current_password": TEST_PASSWORD, "new_email": "no-es-un-email"},
        follow_redirects=True,
    )
    with app.app_context():
        user = User.query.filter_by(username="usuario_prueba").first()
        assert user.email == "usuario_prueba@test.local"


def test_update_email_rejects_email_already_used_by_another_account(client, register, app):
    register(username="dueno_email", email="ocupado@test.local")
    register(username="quiere_ese_email")
    client.post(
        "/login",
        data={"username": "quiere_ese_email", "password": TEST_PASSWORD},
        follow_redirects=True,
    )

    response = client.post(
        "/account/email",
        data={"current_password": TEST_PASSWORD, "new_email": "ocupado@test.local"},
        follow_redirects=True,
    )
    assert b"Ya existe una cuenta registrada con ese email" in response.data

    with app.app_context():
        user = User.query.filter_by(username="quiere_ese_email").first()
        assert user.email == "quiere_ese_email@test.local"


def test_update_email_succeeds(logged_in_client, app):
    response = logged_in_client.post(
        "/account/email",
        data={"current_password": TEST_PASSWORD, "new_email": "actualizado@test.local"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    with app.app_context():
        user = User.query.filter_by(username="usuario_prueba").first()
        assert user.email == "actualizado@test.local"


def test_update_email_allows_adding_email_to_account_without_one(client, app):
    from app.models import db as _db

    with client.application.app_context():
        user = User(username="sin_email_todavia")
        user.set_password(TEST_PASSWORD)
        _db.session.add(user)
        _db.session.commit()

    client.post(
        "/login",
        data={"username": "sin_email_todavia", "password": TEST_PASSWORD},
        follow_redirects=True,
    )
    response = client.post(
        "/account/email",
        data={"current_password": TEST_PASSWORD, "new_email": "recien_agregado@test.local"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    with app.app_context():
        user = User.query.filter_by(username="sin_email_todavia").first()
        assert user.email == "recien_agregado@test.local"
