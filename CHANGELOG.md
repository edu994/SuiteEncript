# Changelog

Historial técnico del proyecto: qué se construyó, qué se rompió y cómo se
arregló. Agrupado por mes, no por commit — la idea es que se pueda leer de
corrido y entender el progreso real, incidentes incluidos.

## Agosto 2026

### Base: de prototipo a aplicación con Postgres

El proyecto arrancó como un script de escritorio con SQLite y varias
inconsistencias heredadas de esa etapa: contraseñas guardadas en texto
plano, un generador basado en `random` (no criptográficamente seguro), y
una bóveda de archivos que decía cifrar pero escribía los bytes tal cual.
Se migró a PostgreSQL (Neon), se reescribió el cifrado sobre AES-256-GCM
para contraseñas, bóveda y notas de texto, y se separó el proyecto en
blueprints de Flask (`auth`, `passwords`, `vault`, `tools`).

### Seguridad de aplicación web

CSRF global (`Flask-WTF`), rate limiting en login/registro
(`Flask-Limiter`), política de contraseñas con `zxcvbn` en vez de un
simple check de longitud, cabeceras de seguridad y CSP vía
`flask-talisman`, y un registro de auditoría (`AuditLog`) para eventos
sensibles — login, cambios de 2FA, CRUD de contraseñas y bóveda. La
subida de archivos pasó de una lista negra de extensiones a una lista
blanca combinada con verificación de *magic bytes* (`python-magic`), para
que un ejecutable renombrado a `.txt` no pase el filtro.

### Incidente: la suite de tests borró tablas de la base de datos real

Un error de configuración en los fixtures de pytest hizo que, durante dos
corridas completas de la suite, las pruebas terminaran ejecutándose
contra la base de datos de Neon real en lugar de SQLite en memoria. Causa
raíz: Flask-SQLAlchemy construye y cachea el motor de conexión dentro de
`db.init_app()`, usando el valor de configuración vigente en ese momento
exacto — el fixture sobreescribía la URI de conexión *después* de esa
llamada, así que el cambio nunca llegaba a tener efecto. El impacto real
fue mínimo (solo existían un usuario de prueba y una cuenta administrativa,
recuperados desde el point-in-time recovery de Neon), pero el mecanismo
era serio: cualquier test de escritura podía tocar datos de producción sin
que nada lo advirtiera.

Corregido pasando toda la configuración de test a través de un parámetro
`config_overrides` que se aplica *antes* de inicializar cualquier
extensión, en vez de mutar `app.config` después de crear la app. El mismo
patrón se repitió más adelante con el almacenamiento S3 y con
`FORCE_HTTPS`, cada vez con el mismo diagnóstico y el mismo arreglo — se
terminó convirtiendo en una regla fija del proyecto: cualquier variable
que pueda venir de un `.env` real se anula explícitamente en la
configuración de test, nunca se asume que un valor por defecto razonable
alcanza.

### Contenerización y CI/CD

`Dockerfile` (Python 3.13, usuario no root) y `docker-compose.yml` con
Postgres y Redis. `entrypoint.sh` corre las migraciones de Alembic antes
de levantar `gunicorn`, así que una base de datos nueva queda al día sin
intervención manual. GitHub Actions corre lint (`ruff`), la suite de
tests, análisis estático (`bandit`), auditoría de dependencias
(`pip-audit`) y una verificación de que la imagen de Docker compila, en
cada push y pull request.

### 2FA, verificación de contraseñas filtradas, recuperación por email

2FA por TOTP (`pyotp`), opcional por usuario, con el secreto cifrado con
el mismo esquema AES-256-GCM del resto del proyecto y códigos de respaldo
guardados solo como hash. El generador de contraseñas consulta la API de
Have I Been Pwned por k-anonimato (solo viaja un prefijo de 5 caracteres
del hash, nunca la contraseña) para avisar si una contraseña generada ya
apareció en una filtración conocida.

La recuperación de contraseña por email pasó por dos proveedores: la
primera versión usaba Gmail vía SMTP, pero el plan gratuito de Render
bloquea la salida por los puertos SMTP estándar — el correo simplemente
nunca llegaba, sin ningún error visible del lado de la aplicación. Se
migró a la API HTTP de Brevo, que no depende de esos puertos y no exige
verificar un dominio propio para enviar a destinatarios reales.

### Escaneo de malware en la bóveda (YARA)

La validación de subida de archivos (extensión + magic bytes) confirma el
*tipo* de un archivo, no si su contenido es malicioso — un PDF real con
JavaScript embebido, o un documento de Office con una macro, pasan esa
verificación sin problema. Se agregó un motor de reglas YARA propio
(`app/utils/malware_scan.py`) que se ejecuta antes de cifrar y guardar
cualquier archivo subido: detecta PDFs con auto-ejecución, macros de
Office autoejecutables, PowerShell ofuscado, webshells genéricas y
ejecutables embebidos sin comprimir. Si el motor falla al compilar o
correr las reglas, el archivo se trata como no seguro — nunca se
interpreta un error como "sin amenazas detectadas".

### Bug real en producción: login por email con colisión de cuentas

El login se extendió para aceptar tanto nombre de usuario como email, con
una consulta `OR` entre ambos campos. En producción apareció un caso real
donde el *username* de una cuenta coincidía con el *email* de otra cuenta
distinta (alguien había escrito su email en el campo de usuario al
registrarse) — la consulta `OR` sin orden garantizado podía devolver
cualquiera de las dos filas, así que un usuario a veces terminaba
autenticado contra la cuenta equivocada. Se diagnosticó revisando el
registro de auditoría de producción antes de tocar código, lo que reveló
la cuenta duplicada. La corrección elimina la ambigüedad de raíz: si el
texto ingresado contiene `@` se busca únicamente por email, si no,
únicamente por username — nunca los dos campos en la misma consulta.

### Diseño

El proyecto pasó por dos rediseños completos. El primero reemplazó una
estética tipo "HUD de hacker" (fuente Orbitron en mayúsculas, resplandor
neón cian, animaciones tipo Matrix) por un sistema visual más restringido
— Inter para texto, un azul contenido como acento único, sin efectos de
glow. El segundo llevó la página pública a un formato de scroll narrativo
de página completa, con capturas reales de la aplicación por cada
funcionalidad y un feed de noticias de seguridad en vivo (RSS de fuentes
reales, con caché en memoria para no golpear los feeds en cada visita).

## Estado actual

Desplegado en Render (Docker), con PostgreSQL administrado en Neon y
almacenamiento de archivos en Supabase Storage. CI en cada push. Detalle
de las decisiones de arquitectura en `ARCHITECTURE.md`, postura de
seguridad completa en `SECURITY.md`.
