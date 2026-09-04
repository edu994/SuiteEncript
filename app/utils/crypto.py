import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MASTER_KEY_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "vault_master.key")

def get_master_key() -> bytes:
    # Producción: la clave viene de una variable de entorno (secreto de la
    # plataforma), en base64 porque bytes crudos no son un valor de entorno
    # seguro de transportar. Nunca un archivo en disco: el hosting gratuito
    # usa disco efímero, así que un archivo se borraría en cada redeploy y
    # todo lo cifrado con la clave anterior quedaría indescifrable para siempre.
    env_key = os.environ.get("VAULT_MASTER_KEY")
    if env_key:
        return base64.b64decode(env_key)

    if os.environ.get("FORCE_HTTPS", "false").lower() == "true":
        raise RuntimeError(
            "VAULT_MASTER_KEY no está definida en el entorno. En producción "
            "(FORCE_HTTPS=true) es obligatoria — sin ella, un archivo en disco "
            "efímero se perdería en el próximo redeploy y todo lo cifrado con "
            "él quedaría indescifrable. Genera una con:\n"
            "  python -c \"import base64,os; "
            "print(base64.b64encode(os.urandom(32)).decode())\""
        )

    # Desarrollo local: archivo en disco, autogenerado la primera vez, por
    # comodidad — no hace falta configurar nada para levantar el proyecto.
    if not os.path.exists(MASTER_KEY_PATH):
        key = AESGCM.generate_key(bit_length=256)
        with open(MASTER_KEY_PATH, "wb") as f:
            f.write(key)
    else:
        with open(MASTER_KEY_PATH, "rb") as f:
            key = f.read()
    return key

def encrypt_bytes(raw_data: bytes) -> bytes:
    key = get_master_key()
    aesgcm = AESGCM(key)
    iv = os.urandom(12)
    ciphertext = aesgcm.encrypt(iv, raw_data, None)
    return iv + ciphertext

def decrypt_bytes(encrypted_data: bytes) -> bytes:
    key = get_master_key()
    aesgcm = AESGCM(key)
    iv = encrypted_data[:12]
    ciphertext = encrypted_data[12:]
    return aesgcm.decrypt(iv, ciphertext, None)