"""Logging estructurado (JSON, una línea por evento) — Fase 9 del ROADMAP.

La pregunta que responde esta fase es "si algo falla en producción, ¿cómo
me entero, y cómo lo investigo sin acceso directo al servidor?". Render (y
cualquier plataforma similar) captura todo lo que el proceso escribe a
stdout/stderr como logs consultables desde su dashboard — logs en JSON en
vez de texto libre es lo que los hace *buscables/filtrables* ahí, no solo
legibles.

Esto es logging operacional (nivel infraestructura, todo request con o sin
sesión), distinto de `app/utils/audit.py` (traza de negocio por usuario,
para auditar acciones concretas de una cuenta — sigue existiendo igual,
ver Fase 4). No se reemplazan entre sí.

No agrega ninguna dependencia nueva para el logging en sí — solo el módulo
`logging` de la librería estándar, con un formatter propio. Sentry (más
abajo) es la única pieza opcional que si trae una dependencia nueva, y
solo se activa si `SENTRY_DSN` está configurada.
"""
import json
import logging
import os
import sys
import time

from flask import g, request


class JsonFormatter(logging.Formatter):
    """Una línea de JSON por registro de log. Los campos base siempre están
    presentes; los campos "extra" que este módulo agrega a propósito (ver
    `_register_request_logging`) se incluyen solo si están presentes, para
    no ensuciar logs que no los usan (p. ej. los de librerías de terceros)."""

    EXTRA_FIELDS = ("method", "path", "status_code", "duration_ms", "remote_addr")

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for field in self.EXTRA_FIELDS:
            if hasattr(record, field):
                payload[field] = getattr(record, field)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


def configure_logging(app):
    """Reemplaza los handlers default de Flask por uno propio que escribe
    JSON a stdout. `LOG_LEVEL` (variable de entorno, default INFO) controla
    el nivel — útil para bajarlo a DEBUG temporalmente sin tocar código.

    `app.logger` es un logger con nombre fijo (el `import_name` de la app,
    "main" en este proyecto) — la librería `logging` devuelve la MISMA
    instancia cada vez que se pide un logger con ese nombre, y `create_app()`
    se llama una vez por test en toda la suite. Sin `handlers.clear()`, cada
    test iría acumulando un handler nuevo sobre el mismo logger compartido."""
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    app.logger.handlers.clear()
    app.logger.addHandler(handler)
    app.logger.setLevel(level)
    app.logger.propagate = False

    _register_request_logging(app)
    _configure_sentry(app)


def _register_request_logging(app):
    """Una línea de log por request: método, ruta, status, duración,
    IP. Da visibilidad operacional pareja para cualquier endpoint, sin
    depender de que cada ruta llame a `log_action()` (que es y sigue siendo
    solo para eventos de negocio auditables, ver `app/utils/audit.py`)."""

    @app.before_request
    def _start_timer():
        g._log_start_time = time.monotonic()

    @app.after_request
    def _log_request(response):
        start = getattr(g, "_log_start_time", None)
        duration_ms = round((time.monotonic() - start) * 1000, 2) if start else None

        app.logger.info(
            "request",
            extra={
                "method": request.method,
                "path": request.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "remote_addr": request.remote_addr,
            },
        )
        return response


def _configure_sentry(app):
    """Sentry es completamente opcional: si `SENTRY_DSN` no está en el
    entorno, esta función no hace nada — mismo criterio "todo o nada" que
    `VAULT_MASTER_KEY`/`R2_*`, salvo que acá alcanza con una sola variable.
    El import de `sentry_sdk` es local a esta función a propósito: si nunca
    se configura Sentry, no hace falta que el paquete esté instalado (ni
    siquiera importado) para que el resto de la app funcione."""
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return

    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration

    sentry_sdk.init(
        dsn=dsn,
        integrations=[FlaskIntegration()],
        environment="production" if app.config.get("FORCE_HTTPS") else "development",
        # Sin tracing de performance, solo captura de errores — es lo único
        # que hace falta para un proyecto de este tamaño, y evita cualquier
        # costo del free tier de Sentry por volumen de traces.
        traces_sample_rate=0.0,
        # El SDK ya redacta contraseñas conocidas por heurística, pero se
        # apaga send_default_pii explícitamente en vez de depender de eso:
        # nunca mandar cookies/IPs/headers completos a un tercero por default.
        send_default_pii=False,
    )
    app.logger.info("Sentry inicializado")
