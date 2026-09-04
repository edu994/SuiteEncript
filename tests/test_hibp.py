import hashlib

from app.utils import hibp as hibp_module
from app.utils.hibp import check_pwned_count


class _FakeResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise hibp_module.requests.HTTPError("boom")


def test_check_pwned_count_uses_k_anonymity_and_detects_match(monkeypatch):
    password = "password123"
    sha1 = hashlib.sha1(password.encode("utf-8"), usedforsecurity=False).hexdigest().upper()
    prefix, suffix = sha1[:5], sha1[5:]

    def fake_get(url, timeout, headers):
        # k-anonimato: solo el prefijo de 5 caracteres viaja en la URL — ni
        # la contraseña ni el hash SHA-1 completo deben aparecer nunca.
        assert prefix in url
        assert password not in url
        assert sha1 not in url
        return _FakeResponse(f"{suffix}:12345\r\nAAAAA0000000000000000000000000000:1\r\n")

    monkeypatch.setattr(hibp_module.requests, "get", fake_get)

    assert check_pwned_count(password) == 12345


def test_check_pwned_count_returns_zero_when_not_found(monkeypatch):
    monkeypatch.setattr(
        hibp_module.requests,
        "get",
        lambda url, timeout, headers: _FakeResponse("AAAAA0000000000000000000000000000:1"),
    )
    assert check_pwned_count("una-contrasena-cualquiera-muy-larga-y-rara") == 0


def test_check_pwned_count_returns_none_on_network_failure(monkeypatch):
    def fake_get(url, timeout, headers):
        raise hibp_module.requests.ConnectionError("sin red")

    monkeypatch.setattr(hibp_module.requests, "get", fake_get)
    assert check_pwned_count("cualquier-cosa") is None


def test_check_pwned_count_returns_none_on_http_error(monkeypatch):
    monkeypatch.setattr(
        hibp_module.requests,
        "get",
        lambda url, timeout, headers: _FakeResponse("", status_code=503),
    )
    assert check_pwned_count("cualquier-cosa") is None


def test_check_pwned_count_returns_none_for_empty_password():
    assert check_pwned_count("") is None
    assert check_pwned_count(None) is None
