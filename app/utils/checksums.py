import hashlib


def calculate_hashes(file_bytes: bytes) -> dict:
    """Calcula simultáneamente MD5, SHA-1, SHA-256 y SHA-512 de un archivo o texto."""
    return {
        # usedforsecurity=False: son checksums de integridad para el usuario
        # (comparar contra el hash que publica quien distribuye un archivo),
        # no se usan para nada criptográfico — MD5/SHA1 son perfectamente
        # válidos para eso, y el flag se lo deja claro tanto a bandit como a
        # cualquiera que lea el código.
        "md5": hashlib.md5(file_bytes, usedforsecurity=False).hexdigest(),
        "sha1": hashlib.sha1(file_bytes, usedforsecurity=False).hexdigest(),
        "sha256": hashlib.sha256(file_bytes).hexdigest(),
        "sha512": hashlib.sha512(file_bytes).hexdigest()
    }