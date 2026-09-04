import json
import logging

import sentry_sdk

from app.utils.logging_config import JsonFormatter, _configure_sentry
from main import create_app


def _make_record(**kwargs):
    defaults = {
        "name": "main",
        "level": logging.INFO,
        "pathname": __file__,
        "lineno": 1,
        "msg": "mensaje de prueba",
        "args": (),
        "exc_info": None,
    }
    defaults.update(kwargs)
    return logging.LogRecord(
        defaults["name"], defaults["level"], defaults["pathname"],
        defaults["lineno"], defaults["msg"], defaults["args"], defaults["exc_info"],
    )


# ---------- JsonFormatter ----------

def test_json_formatter_produces_valid_json_with_base_fields():
    formatter = JsonFormatter()
    record = _make_record()

    parsed = json.loads(formatter.format(record))

    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "main"
    assert parsed["message"] == "mensaje de prueba"
    assert "timestamp" in parsed


def test_json_formatter_includes_extra_fields_when_present():
    formatter = JsonFormatter()
    record = _make_record(msg="request")
    record.method = "GET"
    record.path = "/dashboard"
    record.status_code = 200
    record.duration_ms = 12.5
    record.remote_addr = "127.0.0.1"

    parsed = json.loads(formatter.format(record))

    assert parsed["method"] == "GET"
    assert parsed["path"] == "/dashboard"
    assert parsed["status_code"] == 200
    assert parsed["duration_ms"] == 12.5
    assert parsed["remote_addr"] == "127.0.0.1"


def test_json_formatter_omits_extra_fields_when_absent():
    formatter = JsonFormatter()
    record = _make_record()

    parsed = json.loads(formatter.format(record))

    for field in JsonFormatter.EXTRA_FIELDS:
        assert field not in parsed


def test_json_formatter_includes_exception_traceback():
    formatter = JsonFormatter()
    try:
        raise ValueError("algo salió mal")
    except ValueError:
        import sys
        record = _make_record(msg="Error no manejado", exc_info=sys.exc_info())

    parsed = json.loads(formatter.format(record))

    assert "exception" in parsed
    assert "ValueError" in parsed["exception"]
    assert "algo salió mal" in parsed["exception"]


# ---------- configure_logging: no acumula handlers entre llamadas ----------

def test_configure_logging_does_not_accumulate_handlers_across_app_instances():
    """app.logger es el mismo logger (por nombre) en cada create_app() —
    conftest.py crea una app nueva por test, así que sin handlers.clear()
    esto acumularía un StreamHandler más en cada uno de los 50+ tests de
    la suite."""
    app1 = create_app(config_overrides={"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    handlers_after_first = len(app1.logger.handlers)

    app2 = create_app(config_overrides={"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    handlers_after_second = len(app2.logger.handlers)

    assert handlers_after_first == 1
    assert handlers_after_second == 1


# ---------- Logging por request ----------

def test_each_request_logs_one_structured_json_line(client, caplog):
    with caplog.at_level(logging.INFO, logger="main"):
        response = client.get("/")

    assert response.status_code == 200
    request_logs = [r for r in caplog.records if r.getMessage() == "request"]
    assert len(request_logs) == 1

    parsed = json.loads(JsonFormatter().format(request_logs[0]))
    assert parsed["method"] == "GET"
    assert parsed["path"] == "/"
    assert parsed["status_code"] == 200
    assert parsed["duration_ms"] >= 0


# ---------- Sentry (opcional) ----------

def test_sentry_not_initialized_without_dsn(app, monkeypatch):
    calls = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))
    monkeypatch.delenv("SENTRY_DSN", raising=False)

    _configure_sentry(app)

    assert calls == []


def test_sentry_initialized_with_dsn(app, monkeypatch):
    calls = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setenv("SENTRY_DSN", "https://fake@sentry.example/1")

    _configure_sentry(app)

    assert len(calls) == 1
    assert calls[0]["dsn"] == "https://fake@sentry.example/1"
    assert calls[0]["send_default_pii"] is False
    # Nunca mandar traces por default (evita cualquier costo del free tier
    # de Sentry por volumen) — solo captura de errores.
    assert calls[0]["traces_sample_rate"] == 0.0
