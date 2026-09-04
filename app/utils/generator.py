import secrets
import string


def generar_contrasena(longitud=16, incluir_mayus=True, incluir_numeros=True, incluir_simbolos=True):
    """Genera una contraseña aleatoria criptográficamente segura."""
    caracteres = string.ascii_lowercase

    if incluir_mayus:
        caracteres += string.ascii_uppercase
    if incluir_numeros:
        caracteres += string.digits
    if incluir_simbolos:
        caracteres += "!@#$%^&*()_+-=[]{}|;:,.<>?"

    if not caracteres:
        return ""

    return ''.join(secrets.choice(caracteres) for _ in range(longitud))
