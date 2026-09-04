import io
import os

from app.models import EncryptedFile, db
from app.utils import storage


def _subir_archivo(client, nombre="documento.txt", contenido=b"contenido de prueba de la boveda"):
    return client.post(
        "/vault/upload",
        data={"file": (io.BytesIO(contenido), nombre)},
        content_type="multipart/form-data",
        follow_redirects=True,
    )


def _ruta_fisica(stored_filename):
    # Los tests corren con las variables S3_* anuladas (ver conftest.py), así
    # que storage.py siempre usa el backend local acá — ver
    # tests/test_storage.py para la cobertura específica de la selección de
    # backend y el backend S3.
    return os.path.join(storage.LOCAL_UPLOAD_FOLDER, stored_filename)


def _borrar_archivo_fisico(stored_filename):
    storage.delete_file(stored_filename)


def test_upload_stores_file_encrypted_on_disk(logged_in_client, app):
    contenido_original = b"este texto no debe verse en claro en disco"
    _subir_archivo(logged_in_client, contenido=contenido_original)

    with app.app_context():
        archivo = EncryptedFile.query.first()
        assert archivo is not None
        ruta = _ruta_fisica(archivo.stored_filename)
        with open(ruta, "rb") as f:
            bytes_en_disco = f.read()

    assert bytes_en_disco != contenido_original
    _borrar_archivo_fisico(archivo.stored_filename)


def test_download_returns_original_content(logged_in_client, app):
    contenido_original = b"contenido que debe llegar identico al descargarlo"
    _subir_archivo(logged_in_client, nombre="informe.txt", contenido=contenido_original)

    with app.app_context():
        archivo = EncryptedFile.query.first()
        file_id = archivo.id
        stored_filename = archivo.stored_filename

    response = logged_in_client.get(f"/vault/download/{file_id}")
    assert response.status_code == 200
    assert response.data == contenido_original

    _borrar_archivo_fisico(stored_filename)


def test_upload_rejects_disallowed_extension(logged_in_client, app):
    _subir_archivo(logged_in_client, nombre="programa.exe", contenido=b"MZ\x90\x00falso ejecutable")

    with app.app_context():
        assert EncryptedFile.query.count() == 0


def test_upload_rejects_file_matching_yara_rule(logged_in_client, app):
    # Marcador propio e inventado (no es EICAR real ni malware real) que
    # coincide con la regla SuiteEncript_Selftest_Marker -- ver el porqué
    # de no usar EICAR real acá en el comentario de
    # tests/test_malware_scan.py. Este test solo confirma que la ruta de
    # subida realmente llama al escaneo y rechaza en base al resultado;
    # la cobertura de cada regla individual vive en ese otro archivo.
    marcador = b"SUITEENCRIPT-MALWARE-SCAN-SELFTEST-7f3a9c"
    response = _subir_archivo(logged_in_client, nombre="factura.txt", contenido=marcador)

    assert "patrón conocido de contenido malicioso".encode() in response.data
    with app.app_context():
        assert EncryptedFile.query.count() == 0


def test_upload_rejects_when_user_storage_quota_exceeded(logged_in_client, app, monkeypatch):
    """Antes solo existía el límite de 50MB por archivo
    (Config.MAX_CONTENT_LENGTH), sin ningún tope acumulado por usuario."""
    import app.routes.vault as vault_module
    monkeypatch.setattr(vault_module, "MAX_USER_STORAGE_BYTES", 100)

    _subir_archivo(logged_in_client, nombre="primero.txt", contenido=b"x" * 60)
    response = _subir_archivo(logged_in_client, nombre="segundo.txt", contenido=b"y" * 60)

    assert b"espacio suficiente" in response.data

    with app.app_context():
        archivos = EncryptedFile.query.all()
        assert len(archivos) == 1
        assert archivos[0].original_filename == "primero.txt"
        stored_filename = archivos[0].stored_filename

    _borrar_archivo_fisico(stored_filename)


def test_vault_file_is_scoped_to_owner(client, register, login, app):
    register(username="dueno_del_archivo")
    login(username="dueno_del_archivo")
    _subir_archivo(client, nombre="privado.txt", contenido=b"solo para el dueno")

    with app.app_context():
        archivo = EncryptedFile.query.first()
        file_id = archivo.id
        stored_filename = archivo.stored_filename

    client.get("/logout")
    register(username="intruso")
    login(username="intruso")

    # El intruso no debe poder descargar el archivo de otro usuario por id.
    response = client.get(f"/vault/download/{file_id}", follow_redirects=True)
    assert b"solo para el dueno" not in response.data

    with app.app_context():
        # Y el archivo debe seguir existiendo (no se borró por el intento).
        assert db.session.get(EncryptedFile, file_id) is not None

    _borrar_archivo_fisico(stored_filename)
