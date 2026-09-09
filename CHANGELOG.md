# Changelog

Historial técnico del proyecto: qué se construyó, qué se rompió y cómo se
arregló. Agrupado por mes, no por commit — la idea es que se pueda leer de
corrido y entender el progreso real, incidentes incluidos.

## Septiembre 2026

### Auditoría de seguridad en producción: dos hallazgos reales corregidos

Revisión de caja negra contra el sitio desplegado (reconocimiento pasivo:
cabeceras, CSP, control de acceso, manejo de errores, más una cuenta de
prueba para las rutas autenticadas). La mayoría de lo revisado ya estaba
bien — CSRF, cookies HttpOnly, CSP sin `unsafe-inline`, IDOR, XSS
almacenado — pero aparecieron dos problemas reales:

**La landing prometía cifrado en el navegador que no existe.** El texto
decía "cada archivo se cifra en el navegador... antes de que un solo
byte salga hacia el servidor" — pero la subida es un POST normal sin
ningún JavaScript de cifrado de por medio; el servidor recibe el archivo
en claro y lo cifra ahí mismo antes de guardarlo. Es cifrado en reposo
real (AES-256-GCM, clave maestra fuera de la base de datos), pero no es
el modelo "zero-knowledge" que el copy insinuaba. Corregido el texto para
describir lo que realmente pasa, sin prometer algo que implementar de
verdad implicaría cifrar en el cliente con `crypto.subtle`, derivar la
clave ahí, y migrar todo lo ya guardado — un cambio de arquitectura, no
de copy.

**Fuga de tiempo en `/login` que permite confirmar qué cuentas
existen.** Con usuario inexistente, `check_password_hash()` nunca se
llega a ejecutar (no hay hash contra el cual comparar) — la respuesta
vuelve mucho más rápido que con una cuenta real y contraseña incorrecta.
El mensaje de error es idéntico en los dos casos, pero el tiempo de
respuesta no: la diferencia (verificada, cientos de milisegundos) alcanza
para confirmar por fuerza bruta qué usuarios/emails están registrados,
sin pasar por `/forgot-password`. Corregido corriendo
`check_password_hash()` contra un hash señuelo fijo cuando la cuenta no
existe, para que las dos ramas hagan el mismo trabajo y tarden lo mismo.

**Rate limiting roto en `/login`, causa real distinta de lo que parecía
al principio.** El decorador `@limiter.limit("5 per minute")` ya estaba
en el código, pero probando en vivo (varias tandas de intentos fallidos
seguidos) el límite se disparaba una vez y después dejaba pasar todo de
nuevo, sin ningún patrón. La primera hipótesis fue el backend en memoria
de Flask-Limiter sin compartir contador entre procesos — se sumó Redis
(Upstash) como storage compartido para descartarla, pero el problema
siguió exactamente igual: cero mejora, y la base de Redis no tenía ni
una sola clave escrita después de varios intentos, la prueba de que el
problema era anterior a Redis.

Revisando los logs de producción durante una tanda de prueba apareció la
causa real: `remote_addr` cambiaba en cada request (`10.196.46.1`,
`10.198.61.202`, `10.198.112.137`...) para lo que debería ser el mismo
cliente. Flask-Limiter usa la IP como identidad por defecto -- con una
IP distinta en cada request, nunca llegaba a acumular los 5 intentos
necesarios para bloquear. La causa de fondo: `ProxyFix` estaba
configurado con `x_for=1` (confiar en un solo salto de proxy delante del
contenedor), pero Render tiene más de uno delante -- con un solo salto
confiado, `remote_addr` terminaba siendo la IP interna del segundo
salto (infraestructura de Render, no el cliente real), y esa IP interna
varía según qué nodo atienda cada request.

Corregir esto a fuerza de probar un número de saltos, redeployar y
volver a medir era lento e impreciso (`x_for=2` mejoró el síntoma pero
seguía sin ser la IP real -- pasó a mostrar el borde de Cloudflare, que
también rota entre requests por el enrutamiento anycast). Se agregó
`x_forwarded_for` (el header crudo, sin procesar) al logging
estructurado para ver la cadena completa de una sola vez en vez de
seguir adivinando: resultó ser `cliente_real, borde_de_cloudflare,
proxy_interno_de_render` -- 3 valores, no 2. `ProxyFix(x_for=3)` es el
número correcto, confirmado contra el header real, no adivinado.

El Redis de Upstash se deja conectado de todas formas -- soluciona un
problema real y distinto (que el backend en memoria no comparte
contador si Render llega a correr más de un proceso en el futuro),
aunque no era la causa de este bug puntual.

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
