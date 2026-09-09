from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from flask_wtf import CSRFProtect

csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address)
talisman = Talisman()

# Todo el CSS/JS vive en static/ (nada de <style>/<script> inline en las
# plantillas), así que no hace falta 'unsafe-inline' en ningún lado: un
# script inyectado vía XSS simplemente no se ejecutaría.
CONTENT_SECURITY_POLICY = {
    "default-src": "'self'",
    # El hash cubre el <style> inline de base.html que fija el fondo oscuro
    # antes de que carguen las hojas de estilo externas (evita el flash
    # blanco al cargar) -- es un bloque estático, sin variables de Jinja, así
    # que un hash es seguro acá: a diferencia de 'unsafe-inline' (que este
    # proyecto quitó a propósito), no habilita cualquier <style> inline,
    # solo este contenido exacto.
    "style-src": "'self' https://fonts.googleapis.com https://cdn.jsdelivr.net 'sha256-nuoPj4rZRE/SDXjPvRYICRX+S3wLBw/70+P92zqZVsA='",
    "font-src": "'self' https://fonts.gstatic.com https://cdn.jsdelivr.net",
    "script-src": "'self' https://cdn.jsdelivr.net",
    # blogger.googleusercontent.com / krebsonsecurity.com: imágenes reales
    # de los artículos del carrusel de noticias de la landing (The Hacker
    # News aloja las suyas en Blogger, Krebs en su propio dominio -- se
    # verificó el host exacto sobre varios artículos de cada feed antes de
    # agregarlo, no es un comodín). BleepingComputer no trae imagen en su
    # RSS, así que no necesita entrada acá -- ver app/utils/news_feed.py.
    "img-src": "'self' data: https://blogger.googleusercontent.com https://krebsonsecurity.com",
    # Defensa en profundidad, no tapan un hueco real conocido -- ninguna
    # plantilla usa <object>/<embed>/<base>/formularios que apunten fuera
    # del propio origen, así que estas directivas no deberían cambiar nada
    # visible; solo cierran la puerta a que una inyección futura pueda
    # abusar de esos vectores.
    "object-src": "'none'",
    "base-uri": "'self'",
    "form-action": "'self'",
    # Equivalente moderno de X-Frame-Options: SAMEORIGIN (que Talisman ya
    # envía por su cuenta) -- se agrega igual porque frame-ancestors es lo
    # que los navegadores actuales miran primero.
    "frame-ancestors": "'self'",
}
