from app.models import Password, db


def _crear_password(client, sitio="github.com", usuario="mi_usuario", contrasena="clave-del-sitio-123"):
    return client.post(
        "/passwords",
        data={"sitio": sitio, "usuario_sitio": usuario, "contrasena": contrasena},
        follow_redirects=True,
    )


def test_create_password_stores_encrypted_not_plaintext(logged_in_client, app):
    _crear_password(logged_in_client, contrasena="super-secreto-123")

    with app.app_context():
        registro = Password.query.first()
        assert registro is not None
        assert "super-secreto-123" not in registro.encrypted_password


def test_list_passwords_returns_decrypted_value(logged_in_client):
    _crear_password(logged_in_client, sitio="ejemplo.com", contrasena="clave-a-mostrar")
    response = logged_in_client.get("/passwords")
    assert b"clave-a-mostrar" in response.data


def test_delete_password_removes_it(logged_in_client, app):
    _crear_password(logged_in_client)
    with app.app_context():
        registro = Password.query.first()
        password_id = registro.id

    logged_in_client.post(f"/passwords/delete/{password_id}", follow_redirects=True)

    with app.app_context():
        assert db.session.get(Password, password_id) is None


def test_password_is_scoped_to_owner(client, register, login, app):
    register(username="usuario_a")
    login(username="usuario_a")
    _crear_password(client, sitio="privado-de-a.com", contrasena="clave-de-a")

    client.get("/logout")
    register(username="usuario_b")
    login(username="usuario_b")

    # usuario_b no debe ver la contraseña de usuario_a en su listado.
    response = client.get("/passwords")
    assert b"privado-de-a.com" not in response.data

    with app.app_context():
        registro_de_a = Password.query.filter_by(service="privado-de-a.com").first()

    # usuario_b intenta borrar la credencial de usuario_a por id: no debe poder.
    client.post(f"/passwords/delete/{registro_de_a.id}", follow_redirects=True)
    with app.app_context():
        assert db.session.get(Password, registro_de_a.id) is not None
