import io

from app.utils import storage

S3_CONFIG = {
    "S3_ENDPOINT_URL": "https://example.supabase.co/storage/v1/s3",
    "S3_BUCKET": "test-bucket",
    "S3_ACCESS_KEY_ID": "fake-key",
    "S3_SECRET_ACCESS_KEY": "fake-secret",
}


class _FakeS3Client:
    """Doble de boto3 en memoria — nunca pega a la red real, ni siquiera al
    proveedor S3 configurado."""

    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body):
        self.objects[(Bucket, Key)] = Body

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def delete_object(self, Bucket, Key):
        self.objects.pop((Bucket, Key), None)

    def head_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            import botocore.exceptions
            raise botocore.exceptions.ClientError({"Error": {"Code": "404"}}, "HeadObject")


def _clear_s3_config(app):
    app.config.update({key: None for key in S3_CONFIG})


def _set_s3_config(app):
    app.config.update(S3_CONFIG)


# ---------- Selección de backend ----------

def test_using_s3_false_without_config(app):
    with app.app_context():
        _clear_s3_config(app)
        assert storage.using_s3() is False


def test_using_s3_false_when_only_some_keys_set(app):
    with app.app_context():
        _clear_s3_config(app)
        app.config["S3_BUCKET"] = "solo-esta-una"
        # Faltan el resto a propósito: no debe activar S3 "a medias".
        assert storage.using_s3() is False


def test_using_s3_true_with_all_keys_set(app):
    with app.app_context():
        _set_s3_config(app)
        assert storage.using_s3() is True


# ---------- Backend local (default) ----------

def test_local_backend_roundtrip(app, tmp_path, monkeypatch):
    with app.app_context():
        _clear_s3_config(app)
        monkeypatch.setattr(storage, "LOCAL_UPLOAD_FOLDER", str(tmp_path))

        storage.save_file("archivo.bin", b"contenido-cifrado")
        assert storage.file_exists("archivo.bin") is True
        assert storage.read_file("archivo.bin") == b"contenido-cifrado"

        storage.delete_file("archivo.bin")
        assert storage.file_exists("archivo.bin") is False


def test_local_backend_delete_of_missing_file_does_not_raise(app, tmp_path, monkeypatch):
    with app.app_context():
        _clear_s3_config(app)
        monkeypatch.setattr(storage, "LOCAL_UPLOAD_FOLDER", str(tmp_path))
        storage.delete_file("nunca-existio.bin")  # no debe lanzar


# ---------- Backend S3 (mockeado — nunca red real) ----------

def test_s3_backend_roundtrip(app, monkeypatch):
    with app.app_context():
        _set_s3_config(app)
        fake_client = _FakeS3Client()
        monkeypatch.setattr(storage, "_s3_client", lambda: fake_client)

        storage.save_file("archivo.bin", b"contenido-cifrado")
        assert storage.file_exists("archivo.bin") is True
        assert storage.read_file("archivo.bin") == b"contenido-cifrado"

        storage.delete_file("archivo.bin")
        assert storage.file_exists("archivo.bin") is False


def test_s3_backend_used_instead_of_local_when_configured(app, tmp_path, monkeypatch):
    """Si S3 está configurado, no debe tocar el disco local en absoluto."""
    with app.app_context():
        _set_s3_config(app)
        monkeypatch.setattr(storage, "LOCAL_UPLOAD_FOLDER", str(tmp_path))
        fake_client = _FakeS3Client()
        monkeypatch.setattr(storage, "_s3_client", lambda: fake_client)

        storage.save_file("archivo.bin", b"contenido-cifrado")

        assert list(tmp_path.iterdir()) == []  # nada escrito en disco local
        assert ("test-bucket", "archivo.bin") in fake_client.objects
