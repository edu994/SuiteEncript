#!/bin/sh
set -e

# Antes de aceptar tráfico, dejar el esquema de la base de datos al día —
# incluye tanto una base de datos nueva y vacía (primer despliegue) como
# una que ya tiene datos y solo le faltan las migraciones más recientes.
flask db upgrade

exec gunicorn --bind 0.0.0.0:5000 main:app
