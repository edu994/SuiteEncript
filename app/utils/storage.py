"""Almacenamiento de los archivos cifrados de la bóveda. Dos backends,
seleccionados igual que la base de datos y la clave maestra del proyecto:
por la sola presencia de variables de entorno, sin que el código de las
rutas (`app/routes/vault.py`) tenga que saber cuál está activo.

- **Local** (default): disco, bajo `app/uploads/` — sirve para desarrollo
  y para Docker Compose local (con el volumen nombrado `suiteencript_uploads`).
- **S3-compatible** (producción, vía `boto3`): Render usa disco efímero —
  cualquier archivo escrito ahí se pierde en el próximo redeploy o reinicio
  del contenedor. Cualquier proveedor S3-compatible sirve (Supabase
  Storage, Cloudflare R2, Backblaze B2...) — el protocolo es el mismo,
  solo cambian las credenciales. Este proyecto usa Supabase Storage:
  Cloudflare R2 exige agregar una tarjeta a la cuenta antes de dar acceso
  a la API, y ese costo (aunque el uso real se mantenga en el tier
  gratuito) no valía la pena.

Se activa poniendo las 5 variables `S3_*` obligatorias (ver `.env.example`).
Si falta alguna, cae a disco local — igual criterio que `VAULT_MASTER_KEY`:
nunca un "a medias" silencioso, o está toda la configuración o usa el
fallback completo.

Las credenciales se leen de `current_app.config` (ver `app/config.py`),
nunca de `os.environ` directamente acá: así los tests pueden anularlas de
forma fiable con `config_overrides`, sin depender de qué haya en el `.env`
real del proceso que ejecuta pytest. Es el mismo bug que en algún momento
hizo que la suite completa golpeara la base de datos real de Neon en vez
de SQLite en memoria (ver CHANGELOG.md) — leer una credencial desde el
entorno del proceso en vez de desde app.config.
"""
import os

from flask import current_app

LOCAL_UPLOAD_FOLDER = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "uploads"
)

_S3_CONFIG_KEYS = ("S3_ENDPOINT_URL", "S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY")


def using_s3() -> bool:
    return all(current_app.config.get(key) for key in _S3_CONFIG_KEYS)


def _s3_client():
    # Import diferido: boto3 no hace falta instalarlo para desarrollo local
    # sin almacenamiento externo — pero está en requirements.txt para cuando
    # sí se usa.
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=current_app.config["S3_ENDPOINT_URL"],
        aws_access_key_id=current_app.config["S3_ACCESS_KEY_ID"],
        aws_secret_access_key=current_app.config["S3_SECRET_ACCESS_KEY"],
        # S3_REGION es opcional: R2 no la necesita, pero otros proveedores
        # S3-compatibles (Supabase Storage, el que usa este proyecto) sí la
        # piden para firmar las peticiones correctamente.
        region_name=current_app.config.get("S3_REGION") or None,
    )


def save_file(stored_filename: str, data: bytes) -> None:
    if using_s3():
        _s3_client().put_object(
            Bucket=current_app.config["S3_BUCKET"], Key=stored_filename, Body=data
        )
        return

    os.makedirs(LOCAL_UPLOAD_FOLDER, exist_ok=True)
    with open(os.path.join(LOCAL_UPLOAD_FOLDER, stored_filename), "wb") as f:
        f.write(data)


def read_file(stored_filename: str) -> bytes:
    if using_s3():
        obj = _s3_client().get_object(Bucket=current_app.config["S3_BUCKET"], Key=stored_filename)
        return obj["Body"].read()

    with open(os.path.join(LOCAL_UPLOAD_FOLDER, stored_filename), "rb") as f:
        return f.read()


def delete_file(stored_filename: str) -> None:
    if using_s3():
        # Borrar una key inexistente en S3 no da error — mismo comportamiento
        # que el os.path.exists()/os.remove() de abajo.
        _s3_client().delete_object(Bucket=current_app.config["S3_BUCKET"], Key=stored_filename)
        return

    path = os.path.join(LOCAL_UPLOAD_FOLDER, stored_filename)
    if os.path.exists(path):
        os.remove(path)


def file_exists(stored_filename: str) -> bool:
    if using_s3():
        import botocore.exceptions

        try:
            _s3_client().head_object(Bucket=current_app.config["S3_BUCKET"], Key=stored_filename)
            return True
        except botocore.exceptions.ClientError as err:
            error_code = err.response.get("Error", {}).get("Code", "")
            if error_code in ("404", "NoSuchKey"):
                return False
            raise

    return os.path.exists(os.path.join(LOCAL_UPLOAD_FOLDER, stored_filename))
