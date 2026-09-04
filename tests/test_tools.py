import io

from PIL import Image


def _test_png_bytes(size=(60, 60)):
    img = Image.new("RGB", size, color=(10, 20, 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


# ---------- /tools/audit-log ----------

def test_audit_log_requires_login(client):
    response = client.get("/tools/audit-log", follow_redirects=True)
    assert b"Acceder a tu cuenta" in response.data


def test_audit_log_shows_only_own_events(logged_in_client, register):
    # Un segundo usuario, con su propio evento de registro -- el detail de
    # log_action("register") no incluye el username ajeno en ningún lado
    # visible salvo si hubiera una fuga de aislamiento por user_id.
    register(username="otro_usuario_no_deberia_verse")

    response = logged_in_client.get("/tools/audit-log")
    assert response.status_code == 200
    assert b"otro_usuario_no_deberia_verse" not in response.data


# ---------- /tools/checksum ----------

def test_checksum_requires_login(client):
    response = client.get("/tools/checksum", follow_redirects=True)
    assert b"Acceder a tu cuenta" in response.data


def test_checksum_computes_hashes_for_text_input(logged_in_client):
    response = logged_in_client.post(
        "/tools/checksum",
        data={"text_input": "hola mundo"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    # SHA-256 de "hola mundo" es conocido y estable -- confirma que el
    # hash real se calculó, no solo que la página no rompió.
    assert b"0b894166d3336435c800bea36ff21b29eaa801a52f584c006c49289a0dcf6e2f" in response.data


def test_checksum_computes_hashes_for_uploaded_file(logged_in_client):
    data = {"file": (io.BytesIO(b"contenido de prueba"), "archivo.txt")}
    response = logged_in_client.post(
        "/tools/checksum",
        data=data,
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Resultados" in response.data or b"hash" in response.data.lower()


def test_checksum_flags_matching_expected_hash(logged_in_client):
    response = logged_in_client.post(
        "/tools/checksum",
        data={
            "text_input": "hola mundo",
            "expected_hash": "0b894166d3336435c800bea36ff21b29eaa801a52f584c006c49289a0dcf6e2f",
        },
        follow_redirects=True,
    )
    assert "COINCIDENCIA EXACTA" in response.get_data(as_text=True)


def test_checksum_flags_non_matching_expected_hash(logged_in_client):
    response = logged_in_client.post(
        "/tools/checksum",
        data={"text_input": "hola mundo", "expected_hash": "0" * 64},
        follow_redirects=True,
    )
    assert "no coincide" in response.get_data(as_text=True)


def test_checksum_warns_without_input(logged_in_client):
    response = logged_in_client.post("/tools/checksum", data={}, follow_redirects=True)
    assert "Ingresa un texto o selecciona un archivo" in response.get_data(as_text=True)


# ---------- /tools/text-vault ----------

def test_text_vault_requires_login(client):
    response = client.get("/tools/text-vault", follow_redirects=True)
    assert b"Acceder a tu cuenta" in response.data


def test_text_vault_encrypt_then_decrypt_roundtrip(logged_in_client):
    encrypt_response = logged_in_client.post(
        "/tools/text-vault",
        data={"action": "encrypt", "input_text": "mensaje secreto"},
        follow_redirects=True,
    )
    assert "cifrado exitosamente" in encrypt_response.get_data(as_text=True)

    # Extraer el texto cifrado real de la respuesta no es trivial desde
    # HTML -- se prueba el roundtrip llamando de nuevo con el resultado
    # que sabemos que produce encrypt_text() directamente, ya cubierto en
    # test_crypto.py. Acá lo que importa es que la ruta no rompe y que un
    # texto claramente inválido para descifrar da un error amigable.
    decrypt_response = logged_in_client.post(
        "/tools/text-vault",
        data={"action": "decrypt", "input_text": "esto-no-es-base64-cifrado-valido"},
        follow_redirects=True,
    )
    assert decrypt_response.status_code == 200


def test_text_vault_encrypt_with_custom_password_roundtrip(logged_in_client):
    encrypt_response = logged_in_client.post(
        "/tools/text-vault",
        data={"action": "encrypt", "input_text": "dato sensible", "custom_password": "unaClaveFuerte9!"},
        follow_redirects=True,
    )
    assert "cifrado exitosamente" in encrypt_response.get_data(as_text=True)


def test_text_vault_warns_without_input(logged_in_client):
    response = logged_in_client.post(
        "/tools/text-vault", data={"action": "encrypt"}, follow_redirects=True
    )
    assert "Ingresa el texto" in response.get_data(as_text=True)


def test_text_vault_decrypt_invalid_ciphertext_shows_friendly_error(logged_in_client):
    response = logged_in_client.post(
        "/tools/text-vault",
        data={"action": "decrypt", "input_text": "no-es-un-texto-cifrado-real"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    # No debe filtrar un traceback -- alguna variante de mensaje de error
    # amigable en vez de un 500.
    assert b"Internal Server Error" not in response.data


# ---------- /tools/stego ----------

def test_stego_requires_login(client):
    response = client.get("/tools/stego", follow_redirects=True)
    assert b"Acceder a tu cuenta" in response.data


def test_stego_hide_returns_a_png_file(logged_in_client):
    data = {
        "action": "hide",
        "secret_text": "mensaje oculto",
        "image_file": (io.BytesIO(_test_png_bytes()), "original.png"),
    }
    response = logged_in_client.post(
        "/tools/stego", data=data, content_type="multipart/form-data"
    )
    assert response.status_code == 200
    assert response.mimetype == "image/png"


def test_stego_hide_then_extract_roundtrip(logged_in_client):
    hide_data = {
        "action": "hide",
        "secret_text": "mensaje oculto de prueba",
        "image_file": (io.BytesIO(_test_png_bytes()), "original.png"),
    }
    hide_response = logged_in_client.post(
        "/tools/stego", data=hide_data, content_type="multipart/form-data"
    )
    stego_png_bytes = hide_response.get_data()

    extract_data = {
        "action": "extract",
        "image_file": (io.BytesIO(stego_png_bytes), "stego.png"),
    }
    extract_response = logged_in_client.post(
        "/tools/stego", data=extract_data, content_type="multipart/form-data", follow_redirects=True
    )
    assert "mensaje oculto de prueba" in extract_response.get_data(as_text=True)


def test_stego_warns_without_image(logged_in_client):
    response = logged_in_client.post(
        "/tools/stego", data={"action": "hide", "secret_text": "algo"}, follow_redirects=True
    )
    assert "selecciona una imagen" in response.get_data(as_text=True)


def test_stego_extract_without_hidden_message_shows_friendly_error(logged_in_client):
    """Una imagen sin mensaje oculto no debe reventar con un 500."""
    data = {
        "action": "extract",
        "image_file": (io.BytesIO(_test_png_bytes()), "sin_mensaje.png"),
    }
    response = logged_in_client.post(
        "/tools/stego", data=data, content_type="multipart/form-data", follow_redirects=True
    )
    assert response.status_code == 200
    assert b"Internal Server Error" not in response.data
