import pytest

from app.utils.crypto import decrypt_bytes, encrypt_bytes
from app.utils.text_crypto import decrypt_text, encrypt_text


def test_encrypt_decrypt_bytes_roundtrip():
    original = b"contenido secreto de un archivo de la boveda"
    ciphertext = encrypt_bytes(original)

    assert ciphertext != original
    assert decrypt_bytes(ciphertext) == original


def test_encrypt_bytes_output_differs_from_input_even_for_same_plaintext():
    """El IV aleatorio hace que cifrar el mismo texto dos veces dé
    resultados distintos — si no, algo estaría mal con el modo de cifrado."""
    original = b"mismo contenido"
    assert encrypt_bytes(original) != encrypt_bytes(original)


def test_text_crypto_roundtrip_with_master_key():
    original = "texto guardado en el text-vault sin password propia"
    ciphertext = encrypt_text(original)
    assert decrypt_text(ciphertext) == original


def test_text_crypto_roundtrip_with_custom_password():
    original = "texto protegido con password propia del usuario"
    ciphertext = encrypt_text(original, custom_password="mi-password-personal")
    assert decrypt_text(ciphertext, custom_password="mi-password-personal") == original


def test_text_crypto_wrong_password_fails_to_decrypt():
    ciphertext = encrypt_text("secreto", custom_password="password-correcta")
    with pytest.raises(ValueError):
        decrypt_text(ciphertext, custom_password="password-incorrecta")
