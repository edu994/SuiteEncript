"""Genera los íconos PWA de SuiteEncript con la paleta actual del sitio
(--se-bg / --se-accent). Script de un solo uso, no forma parte de la app
en runtime; se deja en el repo por si hay que regenerar los íconos."""

from PIL import Image, ImageDraw

BG = (10, 14, 26, 255)  # --se-bg
ACCENT = (91, 141, 239, 255)  # --se-accent


def _lock_icon(size, fg, bg=None, padding_ratio=0.24):
    img = Image.new("RGBA", (size, size), bg if bg else (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pad = int(size * padding_ratio)
    body_top = int(size * 0.46)
    body_bottom = size - pad
    body_left = pad
    body_right = size - pad
    radius = int(size * 0.08)

    draw.rounded_rectangle(
        [body_left, body_top, body_right, body_bottom], radius=radius, fill=fg
    )

    shackle_w = int((body_right - body_left) * 0.62)
    # Proporcional a shackle_w, no a size directamente: antes era
    # int(size * 0.26), un valor fijo que no se achicaba junto con
    # shackle_w cuando el padding crecía (versión maskable) -- el arco
    # quedaba angosto pero igual de alto, estirado verticalmente hacia
    # arriba. 0.8065 reproduce la misma proporción de arco que ya se veía
    # bien en el ícono normal (0.26 / 0.3224, los valores que
    # shackle_h/shackle_w tenían ahí).
    shackle_h = int(shackle_w * 0.8065)
    shackle_x0 = size // 2 - shackle_w // 2
    shackle_y0 = body_top - shackle_h
    shackle_thickness = max(int(size * 0.07), 3)

    draw.arc(
        [shackle_x0, shackle_y0, shackle_x0 + shackle_w, shackle_y0 + shackle_h * 2],
        start=180,
        end=360,
        fill=fg,
        width=shackle_thickness,
    )

    keyhole_r = int(size * 0.045)
    keyhole_cx = size // 2
    keyhole_cy = body_top + int((body_bottom - body_top) * 0.42)
    draw.ellipse(
        [keyhole_cx - keyhole_r, keyhole_cy - keyhole_r, keyhole_cx + keyhole_r, keyhole_cy + keyhole_r],
        fill=bg if bg else (10, 14, 26, 255),
    )
    draw.polygon(
        [
            (keyhole_cx - keyhole_r * 0.6, keyhole_cy + keyhole_r * 0.3),
            (keyhole_cx + keyhole_r * 0.6, keyhole_cy + keyhole_r * 0.3),
            (keyhole_cx + keyhole_r * 0.9, keyhole_cy + keyhole_r * 2.2),
            (keyhole_cx - keyhole_r * 0.9, keyhole_cy + keyhole_r * 2.2),
        ],
        fill=bg if bg else (10, 14, 26, 255),
    )
    return img


def make_icon(path, size, maskable=False):
    img = Image.new("RGBA", (size, size), BG)

    # Candado centrado. En modo maskable dejamos más margen de seguridad
    # (Android puede recortar hasta un 20% del borde).
    lock_ratio = 0.34 if maskable else 0.24
    lock = _lock_icon(size, ACCENT, bg=BG, padding_ratio=lock_ratio)
    img.alpha_composite(lock)

    img.save(path, "PNG")


make_icon("static/icons/icon-192.png", 192)
make_icon("static/icons/icon-512.png", 512)
make_icon("static/icons/icon-512-maskable.png", 512, maskable=True)
make_icon("static/icons/apple-touch-icon.png", 180)

print("listo")
