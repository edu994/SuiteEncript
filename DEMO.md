# Guion de demo y preguntas frecuentes

Preparado para la presentación del proyecto. Dos partes: un guion de demo
en vivo (~6-8 minutos) y respuestas ya pensadas a las preguntas que es
más probable que aparezcan.

## Guion de demo (en vivo)

Orden pensado para que cada paso construya sobre el anterior — de "esto es
una app que funciona" a "esto está pensado con seguridad real, de punta a
punta, y desplegado de verdad".

**1. Landing + registro (30s)**
Mostrar la página pública, registrar una cuenta. Mencionar al pasar: la
contraseña exige mínimo 10 caracteres y un puntaje mínimo de `zxcvbn` (no
alcanza con "cumplir el patrón", tiene que no ser predecible).

**2. Gestor de contraseñas + generador (1 min)**
Generar una contraseña, mostrar la verificación automática contra Have I
Been Pwned (probar con una contraseña obviamente filtrada, tipo
`password123`, para que se vea la advertencia en rojo). Guardar una
credencial, mostrar que la tabla la muestra descifrada pero explicar que en
la base de datos está cifrada con AES-256-GCM — buen momento para abrir
`psql`/el dashboard de Neon en otra pestaña y mostrar la columna
`encrypted_password` como texto sin sentido.

**3. 2FA (1.5 min)**
Activar 2FA en la cuenta: mostrar el QR, escanearlo con una app
autenticadora real (Google Authenticator/Authy) si hay una a mano, o
ingresar el código manual. Confirmar, mostrar los códigos de respaldo.
Cerrar sesión, volver a entrar — mostrar que ahora pide el segundo factor.
Este es el momento para mencionar la decisión de que sea **opcional**, no
forzado (está documentada en `ARCHITECTURE.md`, con el razonamiento).

**4. Bóveda de archivos (1.5 min)**
Subir un archivo, marcar "generar enlace público" con una contraseña
opcional. Abrir el enlace en una ventana privada/incógnito (sin sesión) y
descargarlo con la contraseña — muestra que compartir no requiere que el
otro lado tenga cuenta. Mencionar la opción de "un solo uso" y expiración
por tiempo.

**5. Arquitectura de producción (1.5 min)**
Cambiar a explicar, sin necesariamente navegar más: la app corre en
Render, la base de datos es Postgres administrado en Neon, y los archivos
de la bóveda van a Supabase Storage — no al disco del contenedor, porque ese
disco es efímero y se perdería en cada redeploy. Si el tiempo alcanza,
mostrar el diagrama de `README.md`.

**6. Proceso y seguridad (1.5 min)**
Mostrar brevemente `ARCHITECTURE.md` (el razonamiento detrás de cada
decisión técnica) y `CHANGELOG.md` (el historial de cambios). Mencionar el
incidente real documentado ahí (pruebas corriendo contra la base de datos
real por accidente) — es más convincente mostrar que un problema real
pasó, se entendió la causa, y se corrigió con un test de regresión, que
decir "nunca tuve bugs". Cerrar con el pipeline de CI (GitHub Actions:
lint, tests, `bandit`, `pip-audit` en cada push).

## Preguntas frecuentes

**¿Por qué Flask y no Django/FastAPI?**
Flask da control explícito sobre cada pieza (autenticación, ORM, rate
limiting) en vez de decisiones tomadas por el framework — apropiado para
un proyecto donde la seguridad de cada capa es el punto central, no algo
que se delega a convenciones de un framework más opinado.

**¿Cómo funciona el cifrado, en concreto?**
AES-256-GCM: cifrado simétrico autenticado — no solo oculta el contenido,
también detecta si fue modificado (a diferencia de un modo como CBC sin
autenticación aparte). Cada operación de cifrado genera un nonce aleatorio
de 12 bytes que nunca se reutiliza (reutilizar un nonce con la misma clave
rompe la seguridad de GCM por completo). La clave maestra vive en una
variable de entorno en producción, nunca en el código ni en git.

**¿Qué pasa si se pierde la clave maestra (`VAULT_MASTER_KEY`)?**
Todo lo cifrado con ella queda indescifrable para siempre — es la razón
por la que en producción es una variable de entorno persistente (no un
archivo en el disco efímero del contenedor, que se perdería en cada
redeploy) y por la que se generó una sola vez y se guarda aparte
(`INFO_CLAVES_PROD.txt`, nunca en git).

**¿Qué pasa si alguien roba la base de datos completa?**
Ve usuarios, hashes de contraseña (no reversibles), y blobs cifrados con
AES-256-GCM — pero no la clave maestra, que vive en otro lado (variable de
entorno de la plataforma, no en la base de datos). Sin esa clave, el
contenido cifrado no se puede recuperar. Es justamente la separación que
un ataque de "robé un backup" está pensado para no romper.

**¿Qué pasa si se cae Supabase Storage?**
Los metadatos (nombre, tamaño, hash) siguen en Postgres, pero la subida y
descarga de archivos fallarían mientras dure la caída — es una dependencia
externa real, sin failover automático hoy. Sería un buen punto para
mencionar como mejora futura si preguntan "¿qué harías distinto?".

**¿Por qué Neon y no tu propio Postgres, o el de Render?**
El Postgres gratuito de Render expira a los 90 días — no sirve para un
proyecto que se supone sigue corriendo. Correr Postgres propio significa
mantenerlo actualizado y respaldado a mano. Neon da Postgres administrado,
gratis, sin expiración, con branching (usado de verdad para recuperar de
un incidente real, ver `CHANGELOG.md`) y point-in-time recovery.

**¿Cómo sabés que funciona, más allá de "lo probé a mano"?**
Suite de tests (`pytest`) que corre contra rutas reales vía
`app.test_client()`, no contra funciones aisladas — incluye tests de
aislamiento entre usuarios (que un usuario no pueda ver/borrar los datos
de otro adivinando un id), y corre en CI en cada push junto con `ruff`
(lint) y `bandit`/`pip-audit` (seguridad).

**¿Es esto seguro para uso real?**
Con matices honestos: la criptografía y el control de acceso están hechos
con cuidado real, no son un simulacro — pero es un proyecto de una
persona, sin auditoría externa ni bug bounty. Es un buen ejercicio de
"cómo pensar en seguridad de punta a punta", no una promesa de nivel
empresarial.

**¿Qué harías distinto con más tiempo?**
Tests de carga antes de asumir que el rate-limit en memoria alcanza si el
proyecto escalara a más de una instancia, y un proceso de disclosure de
seguridad más formal si esto alguna vez tuviera usuarios reales.

**¿Por qué 2FA opcional y no obligatorio para todos?**
Es el patrón estándar en la industria (Google, GitHub, etc.): dar la
opción sin forzarla no rompe el flujo de login para quien no lo activa, y
sigue dando control real a quien sí lo quiere. Forzarlo a todos habría
sido más invasivo de lo que un proyecto de este alcance necesita para
demostrar que el control está bien implementado.
