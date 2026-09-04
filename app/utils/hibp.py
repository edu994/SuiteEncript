"""Verificación de contraseñas filtradas contra Have I Been Pwned (HIBP),
usando el modelo de k-anonimato que la propia API recomienda: nunca se
envía la contraseña ni su hash completo — solo los primeros 5 caracteres
del hash SHA-1. HIBP responde con todos los sufijos que empiezan igual (en
promedio varios cientos), y la comparación final del sufijo completo se
hace en local. El servidor de HIBP nunca ve la contraseña real ni el hash
completo, así que no hay forma de que reconstruya cuál se está consultando.
"""
import hashlib

import requests

HIBP_RANGE_URL = "https://api.pwnedpasswords.com/range/{prefix}"
HIBP_TIMEOUT_SECONDS = 3


def check_pwned_count(password: str):
    """Devuelve cuántas veces apareció la contraseña en filtraciones
    conocidas (0 si no se encontró), o None si la consulta no se pudo
    completar (sin red, API caída, timeout). Un fallo de red nunca debe
    bloquear el uso del generador — solo se deja de mostrar la advertencia,
    igual criterio que el resto del proyecto ante servicios externos
    opcionales."""
    if not password:
        return None

    # usedforsecurity=False: SHA-1 aquí no protege nada propio, es el
    # algoritmo que exige el contrato de la API de HIBP (k-anonimato sobre
    # SHA-1), no una elección criptográfica de este proyecto.
    sha1 = hashlib.sha1(password.encode("utf-8"), usedforsecurity=False).hexdigest().upper()
    prefix, suffix = sha1[:5], sha1[5:]

    try:
        response = requests.get(
            HIBP_RANGE_URL.format(prefix=prefix),
            timeout=HIBP_TIMEOUT_SECONDS,
            headers={"Add-Padding": "true"},
        )
        response.raise_for_status()
    except requests.RequestException:
        return None

    for line in response.text.splitlines():
        parts = line.split(":")
        if len(parts) != 2:
            continue
        line_suffix, count = parts
        if line_suffix == suffix:
            try:
                return int(count)
            except ValueError:
                return None
    return 0
