"""Envío de correo para la recuperación de contraseña, vía la API HTTP de
Brevo (antes Sendinblue).

Se usó Gmail SMTP originalmente, pero Render bloquea la salida a los
puertos SMTP (25, 465, 587) en el plan gratuito desde 2025-09 -- ver
https://render.com/changelog/free-web-services-will-no-longer-allow-outbound-traffic-to-smtp-ports.
Confirmado en producción con un `OSError: [Errno 101] Network is
unreachable` real en los logs al intentar conectar a smtp.gmail.com:587.
Una API HTTP como Brevo envía por el puerto 443 (HTTPS), que nunca está
bloqueado.

Se eligió Brevo sobre otras opciones (Resend, SendGrid) porque su
verificación de "remitente único" (probar que sos dueño de una casilla,
sin necesitar un dominio propio) permite mandar a *cualquier*
destinatario en el plan gratuito -- Resend, sin dominio verificado, solo
deja mandar a la propia cuenta, inútil para recuperación de contraseña de
usuarios reales. El costo real de no verificar un dominio completo es
peor entregabilidad a Gmail/Yahoo (puede caer en spam) -- aceptable para
un proyecto de portfolio sin dominio propio.

Import de `requests` no es diferido porque ya es una dependencia dura del
proyecto (usada también por hibp.py) -- a diferencia de Sentry/yara, que
sí son opcionales de verdad.

El cuerpo HTML usa estilos inline y una tabla como contenedor a propósito:
los clientes de correo (Gmail, Outlook...) no cargan hojas de estilo
externas ni respetan flexbox/grid de forma confiable, así que el layout
sigue la misma técnica que cualquier email transaccional real. La paleta
(fondo oscuro, azul de acento) es la misma que static/css/style.css
(--se-bg, --se-accent) para que se vea como parte de la app, no como un
correo automático genérico.
"""
import logging

import requests
from flask import current_app, url_for

logger = logging.getLogger(__name__)

_LOGO_FILENAME = "icon-192.png"
_BREVO_ENDPOINT = "https://api.brevo.com/v3/smtp/email"


def _api_configured():
    return bool(
        current_app.config.get("BREVO_API_KEY") and current_app.config.get("BREVO_SENDER_EMAIL")
    )


def _logo_url():
    """URL pública absoluta del ícono de la app, para referenciarlo como
    imagen remota en el correo (en vez de incrustarlo -- una API HTTP de
    JSON no tiene un mecanismo simple de adjuntos "inline" por Content-ID
    como sí tenía smtplib). Si no hay una request activa para construirla,
    se omite el logo -- nunca debe bloquear el envío del correo."""
    try:
        return url_for("static", filename=f"icons/{_LOGO_FILENAME}", _external=True)
    except RuntimeError:
        return None


def _build_html_body(
    title: str,
    intro_html: str,
    action_url: str,
    button_label: str,
    footer_note: str,
    logo_url: str | None,
) -> str:
    """Plantilla HTML compartida por todos los correos transaccionales
    (recuperación de contraseña, verificación de email) -- mismo layout de
    tabla/estilos inline, solo cambia el título, la intro, el botón y la
    nota de pie."""
    logo_html = (
        f'<img src="{logo_url}" width="48" height="48" alt="SuiteEncript" '
        'style="display:block;border-radius:10px;">'
        if logo_url
        else ""
    )
    return f"""\
<!DOCTYPE html>
<html lang="es">
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background-color:#060911;font-family:'Segoe UI',Helvetica,Arial,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#060911;padding:32px 16px;">
<tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:480px;background-color:#121829;border:1px solid #232b3d;border-radius:14px;overflow:hidden;">
<tr><td style="padding:28px 32px 0 32px;">
<table role="presentation" cellpadding="0" cellspacing="0"><tr>
<td style="padding-right:10px;">{logo_html}</td>
<td style="font-size:18px;font-weight:700;color:#f1f5f9;letter-spacing:-0.01em;">SuiteEncript</td>
</tr></table>
</td></tr>
<tr><td style="padding:24px 32px 8px 32px;">
<h1 style="margin:0 0 12px 0;font-size:20px;color:#f1f5f9;font-weight:700;">{title}</h1>
<p style="margin:0 0 20px 0;font-size:14px;line-height:1.6;color:#94a3b8;">
{intro_html}
</p>
</td></tr>
<tr><td style="padding:0 32px 28px 32px;">
<table role="presentation" cellpadding="0" cellspacing="0"><tr>
<td style="border-radius:8px;background-color:#5b8def;">
<a href="{action_url}" target="_blank" style="display:inline-block;padding:12px 28px;font-size:14px;font-weight:600;color:#060911;text-decoration:none;border-radius:8px;">
{button_label}
</a>
</td>
</tr></table>
<p style="margin:20px 0 0 0;font-size:12px;line-height:1.6;color:#5b6577;">
Si el botón no funciona, copiá y pegá este enlace en tu navegador:<br>
<a href="{action_url}" style="color:#8ab4f5;word-break:break-all;">{action_url}</a>
</p>
</td></tr>
<tr><td style="padding:20px 32px;border-top:1px solid #232b3d;">
<p style="margin:0;font-size:12px;line-height:1.6;color:#5b6577;">
{footer_note}
</p>
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>
"""


def send_password_reset_email(to_email: str, reset_url: str) -> bool:
    """Envía el correo con el enlace de recuperación. Devuelve True si se
    envió (o se logueó en dev sin credenciales), False si falló de verdad.

    El llamador NUNCA debe usar el valor de retorno para cambiar el mensaje
    que ve el usuario — mostrar "se envió" o "no se envió" según si el
    email existe en la base sería una fuga de información (permite probar
    qué emails están registrados). El valor de retorno es solo para logging
    interno.
    """
    if not _api_configured():
        # Sin credenciales configuradas: en producción (FORCE_HTTPS=true)
        # esto es un error real que hay que ver en los logs. En desarrollo
        # local, en vez de fallar, se loguea el enlace directamente — así
        # se puede probar el flujo completo sin tener que configurar Brevo
        # para cada sesión de trabajo local.
        if current_app.config.get("FORCE_HTTPS"):
            logger.error("BREVO_API_KEY/BREVO_SENDER_EMAIL no configurados; no se pudo enviar el correo de recuperación")
            return False
        logger.warning("Envío de correo no configurado (modo dev) -- enlace de recuperación: %s", reset_url)
        return True

    text_body = (
        "Pediste recuperar el acceso a tu cuenta de SuiteEncript.\n\n"
        f"Para elegir una contraseña nueva, entrá a este enlace (válido por 1 hora):\n{reset_url}\n\n"
        "Si no fuiste vos, podés ignorar este correo con tranquilidad — tu contraseña actual sigue siendo la misma."
    )

    payload = {
        "sender": {"name": "SuiteEncript", "email": current_app.config["BREVO_SENDER_EMAIL"]},
        "to": [{"email": to_email}],
        "subject": "Recuperación de contraseña — SuiteEncript",
        "htmlContent": _build_html_body(
            title="Recuperación de contraseña",
            intro_html="Pediste recuperar el acceso a tu cuenta. Elegí una contraseña nueva desde el siguiente botón — el enlace vence en 1 hora.",
            action_url=reset_url,
            button_label="Elegir nueva contraseña",
            footer_note="Si no fuiste vos, podés ignorar este correo con tranquilidad — tu contraseña actual sigue siendo la misma.",
            logo_url=_logo_url(),
        ),
        "textContent": text_body,
    }
    headers = {
        "api-key": current_app.config["BREVO_API_KEY"],
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        response = requests.post(_BREVO_ENDPOINT, json=payload, headers=headers, timeout=10)
        if response.status_code >= 400:
            logger.warning(
                "Brevo rechazó el envío del correo de recuperación (status %s): %s",
                response.status_code, response.text,
            )
            return False
        return True
    except requests.RequestException:
        # Un correo que no sale nunca debe romper la petición del usuario
        # ni delatar si el email existía -- se registra para diagnosticarlo
        # del lado del servidor, la respuesta al usuario sigue siendo la
        # misma genérica en cualquier caso.
        logger.warning("No se pudo enviar el correo de recuperación", exc_info=True)
        return False


def send_email_verification_email(to_email: str, verify_url: str) -> bool:
    """Envía el correo de verificación de email (registro o cambio de
    email desde "Mi cuenta"). Mismo contrato y mismos criterios de fallo
    que send_password_reset_email: True si se envió (o se logueó en dev
    sin credenciales), False si falló de verdad -- nunca debe romper la
    petición del usuario ni cambiar la respuesta que ve."""
    if not _api_configured():
        if current_app.config.get("FORCE_HTTPS"):
            logger.error("BREVO_API_KEY/BREVO_SENDER_EMAIL no configurados; no se pudo enviar el correo de verificación")
            return False
        logger.warning("Envío de correo no configurado (modo dev) -- enlace de verificación: %s", verify_url)
        return True

    text_body = (
        "Confirmá tu email en SuiteEncript para asegurarte de poder recuperar tu cuenta si alguna vez olvidás tu contraseña.\n\n"
        f"Para verificarlo, entrá a este enlace (válido por 48 horas):\n{verify_url}\n\n"
        "Si no fuiste vos, podés ignorar este correo con tranquilidad."
    )

    payload = {
        "sender": {"name": "SuiteEncript", "email": current_app.config["BREVO_SENDER_EMAIL"]},
        "to": [{"email": to_email}],
        "subject": "Confirmá tu email — SuiteEncript",
        "htmlContent": _build_html_body(
            title="Confirmá tu email",
            intro_html="Confirmá tu email para asegurarte de poder recuperar tu cuenta si alguna vez olvidás tu contraseña — el enlace vence en 48 horas.",
            action_url=verify_url,
            button_label="Confirmar mi email",
            footer_note="Si no fuiste vos, podés ignorar este correo con tranquilidad.",
            logo_url=_logo_url(),
        ),
        "textContent": text_body,
    }
    headers = {
        "api-key": current_app.config["BREVO_API_KEY"],
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        response = requests.post(_BREVO_ENDPOINT, json=payload, headers=headers, timeout=10)
        if response.status_code >= 400:
            logger.warning(
                "Brevo rechazó el envío del correo de verificación (status %s): %s",
                response.status_code, response.text,
            )
            return False
        return True
    except requests.RequestException:
        logger.warning("No se pudo enviar el correo de verificación", exc_info=True)
        return False
