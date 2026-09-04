import io


def test_dashboard_shows_zero_counts_for_new_user(logged_in_client):
    response = logged_in_client.get("/dashboard")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert ">0</span>" in html
    assert "credenciales guardadas" in html
    assert "archivos ·" in html
    assert "de 200MB usados" in html


def test_dashboard_reflects_real_password_and_file_counts(logged_in_client):
    logged_in_client.post(
        "/passwords",
        data={"sitio": "ejemplo.com", "usuario_sitio": "yo", "contrasena": "ClaveGuardada9!"},
        follow_redirects=True,
    )
    logged_in_client.post(
        "/vault/upload",
        data={"file": (io.BytesIO(b"contenido de prueba"), "archivo.txt")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    response = logged_in_client.get("/dashboard")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert ">1</span>" in html
    assert "credencial guardada" in html
    assert "archivo ·" in html  # singular, no "archivos ·"
    assert "de 200MB usados" in html
