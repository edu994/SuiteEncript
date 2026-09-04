from conftest import TEST_PASSWORD

from app.models import User


def test_register_creates_user(client, app):
    response = client.post(
        "/register",
        data={"username": "nuevo_usuario", "password": TEST_PASSWORD, "email": "nuevo_usuario@test.local"},
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        user = User.query.filter_by(username="nuevo_usuario").first()
        assert user is not None
        # La contraseña nunca debe quedar legible en la base de datos.
        assert user.password_hash != TEST_PASSWORD
        assert user.check_password(TEST_PASSWORD)
        assert user.email == "nuevo_usuario@test.local"


def test_register_rejects_weak_password(client, app):
    client.post(
        "/register",
        data={"username": "usuario_debil", "password": "123456789a", "email": "usuario_debil@test.local"},
        follow_redirects=True,
    )
    with app.app_context():
        assert User.query.filter_by(username="usuario_debil").first() is None


def test_register_rejects_missing_email(client, app):
    client.post(
        "/register",
        data={"username": "sin_email", "password": TEST_PASSWORD},
        follow_redirects=True,
    )
    with app.app_context():
        assert User.query.filter_by(username="sin_email").first() is None


def test_register_rejects_duplicate_username(client, register, app):
    register(username="repetido")
    response = client.post(
        "/register",
        data={"username": "repetido", "password": TEST_PASSWORD, "email": "otro_email@test.local"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    with app.app_context():
        assert User.query.filter_by(username="repetido").count() == 1


def test_register_rejects_duplicate_email(client, register, app):
    register(username="dueno_del_email", email="compartido@test.local")
    response = client.post(
        "/register",
        data={"username": "otro_usuario", "password": TEST_PASSWORD, "email": "compartido@test.local"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    with app.app_context():
        assert User.query.filter_by(username="otro_usuario").first() is None


def test_login_success_sets_session(client, register, login):
    register(username="quien_inicia_sesion")
    response = login(username="quien_inicia_sesion")
    assert response.status_code == 200
    with client.session_transaction() as sess:
        assert sess.get("username") == "quien_inicia_sesion"


def test_login_with_email_instead_of_username_works(client, register):
    """El login tiene que aceptar el email además del username -- antes de
    este fix /login solo consultaba por username y tiraba "usuario o
    contraseña incorrectos" aunque las credenciales fueran correctas."""
    register(username="con_email_propio", email="con_email_propio@test.local")
    response = client.post(
        "/login",
        data={"username": "con_email_propio@test.local", "password": TEST_PASSWORD},
        follow_redirects=True,
    )
    assert response.status_code == 200
    with client.session_transaction() as sess:
        assert sess.get("username") == "con_email_propio"


def test_login_with_email_is_case_insensitive(client, register):
    """El email siempre se guarda en minúsculas (ver register()/
    update_email() en app/routes/auth.py) -- loguearse con mayúsculas
    tiene que igual encontrar la cuenta."""
    register(username="con_email_mayus", email="con_email_mayus@test.local")
    response = client.post(
        "/login",
        data={"username": "CON_EMAIL_MAYUS@TEST.LOCAL", "password": TEST_PASSWORD},
        follow_redirects=True,
    )
    assert response.status_code == 200
    with client.session_transaction() as sess:
        assert sess.get("username") == "con_email_mayus"


def test_login_with_email_ignores_unrelated_account_whose_username_matches_that_email(client, register):
    """Reproduce un bug real que llegó a pasar en producción: una cuenta A
    tiene email 'x@test.local'; una cuenta B, sin relación, tiene username
    literalmente 'x@test.local' (alguien había escrito su email en el
    campo usuario al registrarse). Buscar por
    (username==identifier OR email==identifier) es ambiguo entre A y B --
    .first() sin ORDER BY puede devolver la cuenta equivocada (B), y el
    login de A falla con la contraseña correcta de A. Login por email
    tiene que encontrar siempre la cuenta dueña de ese email, nunca una
    cuenta cuyo username coincide por casualidad."""
    register(username="cuenta_real", email="colision@test.local")
    register(username="colision@test.local", password="OtraClaveDeOtraCuenta9!")

    response = client.post(
        "/login",
        data={"username": "colision@test.local", "password": TEST_PASSWORD},
        follow_redirects=True,
    )
    assert response.status_code == 200
    with client.session_transaction() as sess:
        assert sess.get("username") == "cuenta_real"


def test_login_wrong_password_fails(client, register):
    register(username="con_clave_correcta")
    client.post(
        "/login",
        data={"username": "con_clave_correcta", "password": "clave-incorrecta"},
        follow_redirects=True,
    )
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_login_nonexistent_user_fails(client):
    client.post(
        "/login",
        data={"username": "no_existe", "password": TEST_PASSWORD},
        follow_redirects=True,
    )
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_login_missing_password_field_does_not_crash(client, register):
    """Un POST sin el campo "password" (no solo vacío, ausente del todo)
    llegaba antes como password=None a check_password_hash(), que lanza
    AttributeError (.encode() sobre None) — un 500 en vez de un simple
    "credenciales incorrectas"."""
    register(username="con_clave_correcta")
    response = client.post(
        "/login",
        data={"username": "con_clave_correcta"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_logout_clears_session(logged_in_client):
    with logged_in_client.session_transaction() as sess:
        assert "user_id" in sess

    logged_in_client.get("/logout")

    with logged_in_client.session_transaction() as sess:
        assert "user_id" not in sess
