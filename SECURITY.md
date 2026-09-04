# Seguridad — SuiteEncript

Este documento explica **qué** se protege, **cómo**, y **por qué** se tomó
cada decisión de seguridad en este proyecto. Es la versión "de referencia
rápida" — el historial de cambios e incidentes reales vive en
`CHANGELOG.md`; el razonamiento de arquitectura, en `ARCHITECTURE.md`.

## Principios que guían el proyecto

1. **Un solo esquema de cifrado.** AES-256-GCM (`app/utils/crypto.py`) para
   todo lo que necesita ser reversible: bóveda de archivos, contraseñas
   guardadas, texto cifrado, secreto TOTP. Nunca un cifrado casero, nunca
   un segundo esquema en paralelo.
2. **Lo que no necesita ser reversible, no se cifra — se hashea.**
   Contraseñas de cuenta, contraseña de enlaces compartidos, y códigos de
   respaldo de 2FA: hash de Werkzeug (irreversible), nunca AES.
3. **Control de acceso verificado en cada ruta, nunca solo por id.** Toda
   consulta a datos de un usuario está escopada por `user_id` de sesión
   (`Password.query.filter_by(id=..., user_id=session["user_id"])`), nunca
   solo por el id del registro — adivinar un id ajeno no alcanza.
4. **Los fallos de servicios externos opcionales nunca bloquean el uso de
   la app.** Si Have I Been Pwned no responde, el generador de contraseñas
   sigue funcionando, solo sin mostrar la advertencia. Mismo criterio para
   Sentry: si no está configurado, la app funciona exactamente igual.
5. **Nada sensible en los logs.** `app/utils/audit.py` documenta
   explícitamente que `details` nunca debe llevar secretos — verificado con
   pruebas (ninguna contraseña ni texto descifrado aparece nunca en
   `AuditLog`).

## Autenticación y sesión

- Contraseñas de cuenta: hash con `werkzeug.security` (nunca en texto
  plano, nunca cifradas — irreversible por diseño).
- Política de contraseña: mínimo 10 caracteres, y un puntaje mínimo de
  `zxcvbn` (no alcanza con cumplir un patrón de caracteres si la
  contraseña es predecible — `Aaaaaaaaa1` pasa un check de "mayúscula +
  número" pero se rompe en minutos).
- **2FA/TOTP opcional**, activable por cada usuario: secreto cifrado en
  reposo (nunca en texto plano, a diferencia de muchos tutoriales),
  códigos de respaldo de un solo uso guardados solo como hash. El login
  con 2FA activo pasa por un estado de sesión intermedio
  (`pending_2fa_user_id`, distinto de `user_id`) que no da acceso a
  ninguna ruta protegida hasta verificar el segundo factor.
- Cookies de sesión: `HttpOnly` (no accesible desde JS), `SameSite=Lax`,
  `Secure` en producción (`FORCE_HTTPS=true`).
- Rate limiting en los endpoints más sensibles a fuerza bruta: login
  (5/min), registro (10/hora), verificación 2FA (5/min), setup/disable 2FA
  (10/hora), y la contraseña de descarga en enlaces compartidos de la
  bóveda (10/min — agregado en el repaso OWASP del 2026-08-23, ver abajo).

## Cifrado

- AES-256-GCM en todo lo reversible, con un nonce aleatorio de 12 bytes
  por operación (nunca reutilizado).
- Clave maestra: variable de entorno en producción (`VAULT_MASTER_KEY`,
  obligatoria si `FORCE_HTTPS=true` — falla fuerte en vez de silencioso),
  archivo autogenerado solo en desarrollo local por comodidad.
- El cifrado de texto con contraseña personalizada deriva la clave con
  PBKDF2-HMAC-SHA256 (480.000 iteraciones) — no usa la contraseña
  directamente como clave.

## Validación de entrada y subida de archivos

- Subida a la bóveda: **lista blanca** de extensiones permitidas (no una
  lista negra de las "obviamente peligrosas") **más** una verificación de
  los *magic bytes* reales del contenido (`python-magic`) — un `.txt` que
  en realidad es un ejecutable se rechaza igual, sin importar la extensión
  declarada.
- Límite de tamaño de subida (50 MB) a nivel de configuración de Flask,
  para no leer un archivo gigante entero en memoria antes de poder
  rechazarlo.
- CSRF: token global (`Flask-WTF`) en los 13 formularios `POST` del
  proyecto — verificado, ninguno falta.
- XSS: Jinja2 autoescapa HTML por defecto en todas las plantillas; sin
  `|safe` en contenido de usuario en ningún lado.

## Almacenamiento de archivos

- Local en desarrollo, Supabase Storage en producción — mismo código
  (`app/utils/storage.py`), selección automática por variables de entorno.
  Existe porque el disco de hosting gratuito es efímero: sin esto, un
  archivo subido se perdería en el siguiente redeploy. (Se evaluó primero
  Cloudflare R2, pero pide tarjeta antes de dar acceso a la API — ver
  `ARCHITECTURE.md`.)
- El backend de almacenamiento nunca ve contenido en claro: `storage.py`
  solo mueve bytes, el cifrado/descifrado ocurre siempre en
  `app/routes/vault.py` antes/después de llamarlo.

## Repaso OWASP Top 10

Revisión completa, categoría por categoría, de todo el código contra las
10 de OWASP:

| Categoría | Resultado |
|---|---|
| A01 Broken Access Control | Sin hallazgos — verificado en todas las rutas |
| A02 Cryptographic Failures | Sin hallazgos — esquema único, nonces no reutilizados |
| A03 Injection | Sin hallazgos — ORM en todo el proyecto, autoescape de Jinja2 |
| A04 Insecure Design | **Corregido**: crash (500) en `/login` con el campo `password` ausente |
| A05 Security Misconfiguration | Sin hallazgos nuevos — debug off en prod, páginas de error propias |
| A06 Vulnerable/Outdated Components | Sin hallazgos — `pip-audit` en CI en cada push |
| A07 Auth Failures | **Corregido**: sin límite de intentos en la contraseña de enlaces compartidos. Riesgo aceptado y documentado: enumeración de usuarios en `/register` |
| A08 Data Integrity Failures | Sin hallazgos — migraciones siempre revisadas a mano |
| A09 Logging/Monitoring Failures | `AuditLog` cubre los eventos de negocio; logging estructurado operacional a nivel de infraestructura corre en paralelo |
| A10 SSRF | Sin hallazgos — única llamada saliente es a una URL fija (HIBP) |

Dos correcciones reales de código salieron de este repaso, cada una con su
test de regresión: el crash de `/login` sin contraseña
(`test_login_missing_password_field_does_not_crash`) y la falta de rate
limit en la contraseña de enlaces compartidos
(`test_shared_download_password_is_rate_limited`).

Cerrado como parte de este repaso: rate-limit propio en `/vault/upload` y
en agregar/borrar contraseñas (antes solo mitigado por requerir sesión
iniciada), y una cuota total de 200MB de almacenamiento por usuario
(antes solo existía el límite de 50MB por archivo individual).

## Alineación con NIS2, Artículo 21

**Importante**: NIS2 (Directiva (UE) 2022/2555) aplica a entidades
esenciales/importantes definidas por la regulación — un proyecto personal
como este no está sujeto a ella. Lo que sigue es "diseñado siguiendo" el
espíritu de las medidas de gestión de riesgo del Art. 21, como ejercicio
de buenas prácticas — **nunca** una declaración de cumplimiento formal,
que es un estatus legal que no aplica acá.

| Medida del Art. 21 | Cómo se refleja en este proyecto |
|---|---|
| (b) Gestión de incidentes | Ver el incidente real documentado en `CHANGELOG.md` (pruebas corriendo contra la base de datos real por accidente) — causa raíz, corrección, y la lección aplicada hacia adelante |
| (c) Continuidad/backup | Migraciones versionadas en git (recuperables), Neon con point-in-time recovery (usado de verdad en el incidente de arriba) |
| (e) Seguridad en el desarrollo | CI en cada push (lint, tests, `bandit`, `pip-audit`), migraciones revisadas a mano antes de aplicar, código nunca desplegado sin pasar por tests |
| (g) Higiene cibernética básica | Dependencias con versión mínima fijada, escaneo de vulnerabilidades automatizado, principio de menor privilegio (usuario no-root en el contenedor, token de Supabase con permiso limitado a un solo bucket) |
| (h) Políticas de criptografía | Ver la sección "Cifrado" de este documento — un esquema único, documentado, con la razón de cada elección |
| (i) Control de acceso | Ver "Autenticación y sesión" arriba — control de acceso verificado por `user_id` en cada ruta |
| (j) Autenticación multifactor | 2FA/TOTP implementado y disponible para cada cuenta (opcional, no forzado — ver la decisión documentada en `ARCHITECTURE.md`) |

## Reportar un problema de seguridad

Este es un proyecto personal, sin un proceso formal de disclosure. Si
encontrás algo, el canal es directo: abrí un issue en el repositorio o
contactá al autor.
