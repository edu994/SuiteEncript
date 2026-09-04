# Arquitectura y decisiones

Por qué el proyecto está armado como está. No es un tutorial de las
tecnologías elegidas — es el razonamiento detrás de cada elección, para
que quede claro que no son defaults al azar.

## Vista general

```
Navegador
   │  HTTPS
   ▼
Render (Docker: gunicorn + Flask)
   │
   ├── app/routes/   rutas por área (auth, contraseñas, bóveda, herramientas)
   │                 cada una revisa la sesión y filtra todo por el usuario dueño
   │
   └── app/utils/    cifrado, TOTP, HIBP, storage, email, escaneo de malware
   │
   ├──► Neon (Postgres) — usuarios, contraseñas cifradas, metadata, auditoría
   └──► Supabase Storage — archivos cifrados de la bóveda
```

## Hosting: Render

Se eligió despliegue explícito por Docker en vez de dejar que la
plataforma autodetecte el runtime — así el comportamiento no depende de
qué versión de Python soporte el buildpack nativo de turno, se usa el
`Dockerfile` del repo tal cual, igual en cualquier plataforma. El plan
gratuito "duerme" el servicio tras ~15 minutos sin tráfico; aceptable
para un proyecto personal, con la opción de un monitor de uptime externo
si hace falta mantenerlo despierto.

## Base de datos: Neon en vez del Postgres de Render

El Postgres gratuito de Render expira a los 90 días — no sirve para algo
que se supone sigue funcionando. Neon da Postgres administrado gratis sin
fecha de expiración, con *branching* real de la base de datos (una copia
completa e independiente, no solo un snapshot) y recuperación a un punto
en el tiempo. Ambas capacidades se usaron en la práctica, no solo en
teoría: el branching separa hoy una rama de producción de una de
desarrollo, y el point-in-time recovery se usó para recuperar datos
después de un incidente real de aislamiento de tests (ver `CHANGELOG.md`).

## Almacenamiento de archivos: Supabase Storage, no Cloudflare R2

El disco de un contenedor en el plan gratuito de Render es efímero —
cualquier archivo escrito ahí se pierde en el siguiente redeploy o
reinicio. La bóveda necesita almacenamiento externo persistente. Se
evaluó primero Cloudflare R2, pero Cloudflare exige cargar una tarjeta de
crédito antes de dar acceso a la API, incluso si el uso real se mantiene
dentro del tier gratuito — no era una condición aceptable para este
proyecto. Supabase Storage ofrece el mismo protocolo S3-compatible sin
pedir tarjeta, así que el código de acceso (`app/utils/storage.py`) es
idéntico independientemente del proveedor: selecciona el backend por la
presencia de cinco variables de entorno `S3_*`, con fallback automático a
disco local cuando no están configuradas (útil en desarrollo).

## Cifrado: un solo esquema, en todo el proyecto

AES-256-GCM (`app/utils/crypto.py`) para todo lo que necesita ser
reversible — bóveda de archivos, contraseñas guardadas, texto cifrado y
el secreto de 2FA/TOTP — con nonce aleatorio de 12 bytes en cada
operación, nunca reutilizado. Es una decisión deliberada de no tener un
segundo esquema de cifrado en paralelo para ningún caso nuevo, ni
"simplificar" con algo casero. Lo que no necesita ser reversible
(contraseñas de cuenta, códigos de respaldo de 2FA) se hashea con
Werkzeug en vez de cifrarse — un hash es la herramienta correcta ahí, no
una versión más simple del mismo cifrado.

La clave maestra vive en una variable de entorno en producción
(`VAULT_MASTER_KEY`), nunca en un archivo — en un host con disco efímero,
una clave en archivo se perdería en cada redeploy, dejando indescifrable
todo lo que ya estaba cifrado. En desarrollo local, por comodidad, cae a
un archivo autogenerado; en producción, si falta, la aplicación falla al
arrancar en vez de arrancar sin cifrado real.

## 2FA opcional, no obligatorio

Cada usuario decide si lo activa, desde su propia cuenta. Es el patrón
estándar de la mayoría de servicios reales (Google, GitHub) y no cambia
el flujo de login para quien no lo usa. Forzarlo a todas las cuentas
habría sido más invasivo de lo que el proyecto necesita para demostrar
que el control de acceso funciona de verdad.

## Verificación de contraseñas filtradas: solo en el generador

La consulta a Have I Been Pwned (k-anonimato, solo viaja un prefijo de
hash) se aplica al generador de contraseñas, no al registro ni al login
de la propia aplicación — es una advertencia informativa, no un gate. Un
fallo de red hacia HIBP nunca bloquea el generador, solo deja de mostrar
el aviso; el mismo criterio se aplica a cualquier servicio externo
opcional del proyecto (Sentry, por ejemplo).

## Redis para rate limiting

`Flask-Limiter` puede correr en memoria de proceso, válido solo con un
único worker. Se decidió sumar Redis como backend compartido desde el
principio en vez de esperar a que hiciera falta — evita tener que
revisitar esto bajo presión si el proyecto alguna vez corre con más de un
worker. Fuera de Docker, sigue funcionando en memoria salvo que se
configure explícitamente.

## Escaneo de archivos: reglas YARA propias, no un set público

La validación de subida (lista blanca de extensiones + verificación de
*magic bytes*) confirma el tipo real de un archivo, pero no si su
contenido es malicioso. Se evaluó importar un set de reglas YARA público
(hay varios con miles de reglas ya escritas) y se optó por un set propio
y curado en su lugar: los sets públicos escanean más lento, generan más
falsos positivos sin revisar caso por caso, y cada uno trae su propia
licencia. Un set pequeño y propio, enfocado en los patrones más
relevantes para un archivo que alguien sube y potencialmente comparte por
enlace (PDFs con auto-ejecución, macros de Office, webshells,
PowerShell ofuscado), es más rápido y más fácil de razonar. Queda como
ampliación futura sumar un set público como capa adicional una vez que
el propio esté probado en uso real.

## Observabilidad

Logging estructurado en JSON a stdout — la plataforma de hosting ya
captura eso como logs consultables, sin necesidad de infraestructura
propia. El monitoreo de errores (Sentry) es opcional: si no está
configurado, la aplicación funciona exactamente igual, solo sin reportar
errores a un servicio externo.

## Lo que queda fuera de alcance, a propósito

- **Sin auditoría externa ni bug bounty.** Es un proyecto de una persona;
  la criptografía y el control de acceso están hechos con cuidado real,
  pero eso no reemplaza una revisión independiente.
- **Sin failover si Supabase Storage se cae.** Los metadatos siguen en
  Postgres, pero la subida/descarga de archivos depende de esa
  disponibilidad externa.
- **Descompresión de archivos comprimidos no incluida en el escaneo de
  malware.** Extraer contenido de un `.zip`/`.7z` subido por un usuario
  trae sus propios riesgos (zip bombs, path traversal) que quedaron
  deliberadamente fuera de este alcance.

Postura de seguridad completa, con el repaso categoría por categoría
contra el OWASP Top 10, en `SECURITY.md`. Historial de cambios e
incidentes reales en `CHANGELOG.md`.
