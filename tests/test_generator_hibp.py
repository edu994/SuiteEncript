from app.routes import passwords as passwords_module


def test_generator_shows_pwned_warning(logged_in_client, monkeypatch):
    monkeypatch.setattr(passwords_module, "check_pwned_count", lambda pw: 5)
    response = logged_in_client.post("/generator", data={"longitud": "16"})
    assert response.status_code == 200
    assert b"filtracion" in response.data.lower()


def test_generator_shows_safe_message_when_not_pwned(logged_in_client, monkeypatch):
    monkeypatch.setattr(passwords_module, "check_pwned_count", lambda pw: 0)
    response = logged_in_client.post("/generator", data={"longitud": "16"})
    assert response.status_code == 200
    assert b"No encontrada" in response.data


def test_generator_handles_hibp_unavailable_gracefully(logged_in_client, monkeypatch):
    monkeypatch.setattr(passwords_module, "check_pwned_count", lambda pw: None)
    response = logged_in_client.post("/generator", data={"longitud": "16"})
    assert response.status_code == 200
    assert b"No se pudo verificar" in response.data


def test_generator_get_request_does_not_call_hibp(logged_in_client, monkeypatch):
    calls = []
    monkeypatch.setattr(passwords_module, "check_pwned_count", lambda pw: calls.append(pw) or 0)
    logged_in_client.get("/generator")
    assert calls == []
