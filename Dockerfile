FROM python:3.13-slim

# libmagic1: python-magic (usado en app/routes/vault.py para revisar el
# contenido real de los archivos subidos, no solo su extensión) es un
# wrapper de esta librería del sistema en Linux — sin ella instalada,
# la subida a la bóveda falla al importar el módulo.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copiar solo requirements.txt primero, instalar, y recién después copiar
# el resto del código: mientras las dependencias no cambien, Docker
# reutiliza esta capa cacheada en vez de reinstalar todo en cada build.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Necesario para que `flask db upgrade` (ver entrypoint.sh) sepa qué app
# cargar sin tener que pasarlo a mano en cada comando.
ENV FLASK_APP=main.py

# No correr como root dentro del contenedor: si algo comprometiera la app,
# limita el daño posible (no podría, por ejemplo, instalar paquetes de
# sistema ni tocar archivos fuera de lo que este usuario tiene permiso).
RUN useradd --create-home appuser \
    && mkdir -p /app/app/uploads \
    && chown -R appuser:appuser /app \
    && chmod +x entrypoint.sh
USER appuser

EXPOSE 5000

# Aplica las migraciones pendientes y recién después arranca gunicorn —
# así un despliegue a una base de datos nueva (o desactualizada) no se
# rompe esperando que alguien corra `flask db upgrade` a mano.
ENTRYPOINT ["./entrypoint.sh"]
