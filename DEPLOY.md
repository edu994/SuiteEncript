# Despliegue a producción

Guía paso a paso para llevar SuiteEncript de "corre en Docker local" a una
URL pública real. Las decisiones de *qué* usar (Render, Neon, Supabase
Storage) ya están tomadas y documentadas en `ARCHITECTURE.md` — este
documento es el *cómo*, en orden.

Crear cuentas y pegar credenciales en el panel de un proveedor externo son
pasos que hay que hacer manualmente, desde el navegador, con la sesión
propia de cada servicio — no hay forma de automatizarlos. Lo que sí queda
resuelto de antemano: el código (`app/utils/storage.py`), los secretos de
la aplicación ya generados (`INFO_CLAVES_PROD.txt`, gitignored — nunca se
sube a git) y esta guía con la lista exacta de qué configurar y dónde.

## Orden recomendado

1. Supabase Storage (bóveda de archivos)
2. Neon (base de datos de producción — ya tenés Neon para dev, acá se decide
   si reutilizarlo o separar)
3. Render (el servicio web en sí)
4. Variables de entorno en Render
5. Verificación de extremo a extremo

---

## 1. Supabase Storage

Se eligió Supabase Storage y no Cloudflare R2 a propósito: R2 pide cargar
una tarjeta a la cuenta antes de dar acceso a la API (aunque el uso real se
mantenga en el tier gratuito), y eso no era aceptable para este proyecto.
Supabase Storage es S3-compatible igual que R2, así que `app/utils/storage.py`
no necesita saber cuál de los dos hay detrás — solo lee 5 variables `S3_*`.

1. Creá una cuenta en [supabase.com](https://supabase.com) si no tenés una
   (el free tier alcanza de sobra: 1GB de almacenamiento, sin tarjeta).
2. Creá un proyecto nuevo (o reutilizá uno existente) y, dentro de él, andá a
   **Storage** → **Buckets** → **New bucket**.
   - Nombre sugerido: `suiteencript-vault` (podés usar otro, es el valor de
     `S3_BUCKET`).
   - Dejalo **privado** (no "Public bucket"): la app nunca sirve archivos
     directo desde Supabase al navegador, siempre pasan por Flask (que
     descifra en memoria y los entrega vía `send_file`).
3. Andá a **Project Settings** → **Storage** → **S3 Connection** para obtener
   `S3_ENDPOINT_URL` (termina en `/storage/v1/s3`) y `S3_REGION`.
4. En la misma sección, **Access Keys** → **New access key**: te da el
   `S3_ACCESS_KEY_ID` y el `S3_SECRET_ACCESS_KEY` **una sola vez** — copialos
   de inmediato a `INFO_CLAVES_PROD.txt` (ver la plantilla que ya está ahí).

Con esto tenés los 5 valores de `S3_*` que pide `.env.example`.

## 2. Base de datos de producción (Neon)

El proyecto de Neon usa dos ramas separadas — `production` (exclusiva de
lo que corre en Render, la que usa
`SQLALCHEMY_DATABASE_URI` ahí) y `development` (branch-off de `production`,
auto-delete desactivado, para cualquier sesión que quiera trabajar contra
Neon real en vez del Postgres local de Docker). Si en algún momento hace
falta rehacer esta separación desde cero (por ejemplo, en un proyecto
nuevo): **Branches** → **Create branch**, elegir la rama actual como
origen, punto de partida "Head", y **poner "Auto-delete" en "Never"** — por
defecto Neon ofrece ramas temporales que se autodestruyen al día, fácil de
pasar por alto si no se mira ese campo.

Para la base de datos, andá a **Connection Details** en el dashboard de
Neon y copiá el connection string (formato
`postgresql://usuario:contraseña@host/basededatos`). Ese va a ser
`SQLALCHEMY_DATABASE_URI` en Render, pero con el driver explícito:
reemplazá `postgresql://` por `postgresql+psycopg2://` al principio (mismo
ajuste que ya se hace para desarrollo).

## 3. Render

1. Creá una cuenta en [render.com](https://render.com) (podés entrar con tu
   cuenta de GitHub directamente, simplifica el paso siguiente).
2. **New** → **Web Service**.
3. Conectá el repositorio `edu994/SuiteEncript` de GitHub (Render te va a
   pedir autorizar acceso a tus repos — dale acceso solo a este repo si te
   da la opción, no a toda tu cuenta).
4. **Runtime**: elegí **Docker** explícitamente, no dejes que Render
   autodetecte — así el comportamiento no depende de qué versión de
   Python soporte el buildpack nativo de la plataforma, se usa el
   `Dockerfile` del repo tal cual (más en `ARCHITECTURE.md`).
5. **Plan**: Free está bien para un proyecto de portfolio (se "duerme" tras
   ~15 min sin tráfico — la primera visita después de dormir tarda unos
   segundos más en responder, es esperable).
6. Todavía no le des a "Create" — primero configurá las variables de entorno
   del paso 4 de esta guía, Render te deja hacerlo en la misma pantalla de
   creación.

## 4. Variables de entorno en Render

En la sección **Environment** del servicio, agregá exactamente estas
(los valores de `SECRET_KEY` y `VAULT_MASTER_KEY` ya están generados —
están en `INFO_CLAVES_PROD.txt`, en la raíz del proyecto, que nunca se sube
a git):

| Variable | Valor | De dónde sale |
|---|---|---|
| `SECRET_KEY` | (ver `INFO_CLAVES_PROD.txt`) | Ya generado, 64 caracteres hex |
| `VAULT_MASTER_KEY` | (ver `INFO_CLAVES_PROD.txt`) | Ya generado, base64 de 32 bytes |
| `SQLALCHEMY_DATABASE_URI` | tu connection string de Neon | Paso 2 de esta guía |
| `FORCE_HTTPS` | `true` | Activa `talisman.force_https`, cookies `Secure`, y exige que `SECRET_KEY`/`VAULT_MASTER_KEY` estén presentes (fallan fuerte si faltan) |
| `S3_ENDPOINT_URL` | tu URL de conexión S3 de Supabase | Paso 1 |
| `S3_BUCKET` | el nombre que le pusiste en el paso 1 | Paso 1 |
| `S3_ACCESS_KEY_ID` | del access key que creaste | Paso 1 |
| `S3_SECRET_ACCESS_KEY` | del access key que creaste | Paso 1 |
| `S3_REGION` | tu región de Supabase | Paso 1 |
| `SENTRY_DSN` *(opcional)* | el DSN de tu proyecto en sentry.io | Paso 6 de esta guía — se puede agregar después, no bloquea el primer despliegue |

**No hace falta** `RATELIMIT_STORAGE_URI`: `entrypoint.sh` arranca
`gunicorn` sin `--workers` (default: 1 solo worker), y el plan free de
Render corre una sola instancia — con un único proceso, el backend en
memoria (`memory://`, el default de `Config.RATELIMIT_STORAGE_URI`) cuenta
correctamente sin necesitar Redis. **Si en algún momento escalás a más de un
worker o más de una instancia**, ahí sí hace falta un Redis compartido entre
procesos — Upstash tiene un free tier de Redis serverless que serviría sin
pagar nada; no es necesario para el despliegue inicial.

**No hace falta** `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB`: esas
solo las usa `docker-compose.yml` para el Postgres *local* — en Render la
base de datos ya existe en Neon, se conecta directo por
`SQLALCHEMY_DATABASE_URI`.

Después de cargar las variables de la tabla, ahí sí, **Create Web
Service**. Render va a buildear la imagen del `Dockerfile` y arrancarla —
`entrypoint.sh` corre `flask db upgrade` automáticamente antes de levantar
`gunicorn`, así que las migraciones se aplican solas contra la Neon nueva.

## 5. Verificación de extremo a extremo

Con la URL pública que te da Render (`https://tu-servicio.onrender.com`, o
tu dominio propio si configurás uno):

1. **Sin bucle de redirección**: la página carga por HTTPS sin quedar
   redirigiendo infinitamente. Si pasa esto, revisá que `ProxyFix` esté
   activo (ya lo está, en `main.py`) y que `FORCE_HTTPS=true` esté
   realmente configurado en Render — ver `ARCHITECTURE.md` para por qué
   hace falta `ProxyFix` detrás de un proxy que termina TLS.
2. **Registro + login** de un usuario de prueba real.
3. **Subida a la bóveda**: subí un archivo cualquiera, confirmá que aparece
   en el dashboard de Supabase (**Storage** → tu bucket) — si aparece ahí y
   no falla la subida, `storage.py` está usando Supabase Storage y no el
   disco efímero del contenedor.
4. **La prueba que realmente importa**: en Render, hacé un **Manual Deploy**
   (redeploy manual, sin cambiar código) del mismo servicio, y después
   volvé a descargar el archivo que subiste en el paso 3. Si se descarga
   bien después del redeploy, confirmaste que sobrevive al disco efímero —
   si hubiera estado usando disco local, ya no existiría.
5. Activá 2FA en la cuenta de prueba, cerrá sesión, volvé a entrar — el
   segundo factor debe pedirse.
6. Revisá `/tools/audit-log` — los eventos de arriba deben aparecer ahí.

Con los 6 puntos verificados, el despliegue queda confirmado de extremo a
extremo, no solo "levantó y responde".

## 6. Observabilidad (opcional pero recomendado)

El código ya está listo para ambas piezas — lo único que falta son las
cuentas:

- **Logging estructurado**: ya activo sin que haya que hacer nada — cada
  request y cualquier error 500 quedan como JSON en los logs de Render
  (pestaña **Logs** del servicio), sin necesidad de ninguna cuenta extra.
- **Sentry (monitoreo de errores)**: creá una cuenta gratis en
  [sentry.io](https://sentry.io), un proyecto nuevo tipo **Flask**, copiá
  el DSN que te muestra (`Settings` del proyecto → `Client Keys (DSN)`), y
  agregalo como la variable `SENTRY_DSN` en Render (podés hacerlo en
  cualquier momento después del primer despliegue, no es necesario para
  arrancar). Se activa solo, sin reiniciar código.
- **UptimeRobot (monitoreo de uptime)**: cuenta gratis en
  [uptimerobot.com](https://uptimerobot.com), **Add New Monitor** → HTTP(s)
  → la URL pública de Render, intervalo de 5 minutos. Te avisa (por email) si el servicio deja de
  responder. Como el plan free de Render "duerme" tras ~15 min sin tráfico,
  un ping cada 5 min además tiene el efecto colateral de
  mantenerlo siempre despierto (nunca pasan los 15 min de inactividad) —
  activado a propósito por eso, no solo por las alertas.

  **Ojo con el presupuesto de horas si hacés esto en cualquier proyecto de
  Render**: el plan free da 750 horas gratis **por workspace** al mes (no
  por servicio) — [render.com/docs/free](https://render.com/docs/free). Un
  mes de 31 días con el servicio despierto 24/7 consume 744h, dejando solo
  ~6h de margen; si se supera el límite, Render suspende **todos** los
  servicios free de ese workspace hasta el mes siguiente (no es solo lento,
  es una caída real). Confirmado antes de activarlo: esta cuenta de Render
  solo tiene el servicio de SuiteEncript, así que el margen es real todos
  los meses. Si algún día se agrega un segundo servicio free al mismo
  workspace, hay que volver a hacer esta cuenta.
