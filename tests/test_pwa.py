import json
import os

STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")
REQUIRED_ICON_SIZES = {"192x192", "512x512"}


def _load_manifest():
    with open(os.path.join(STATIC_DIR, "manifest.json"), encoding="utf-8") as f:
        return json.load(f)


# ---------- manifest.json ----------

def test_manifest_is_valid_json_with_required_pwa_fields():
    manifest = _load_manifest()

    assert manifest["name"] == "SuiteEncript"
    assert manifest["start_url"] == "/"
    assert manifest["display"] == "standalone"
    assert "background_color" in manifest
    assert "theme_color" in manifest


def test_manifest_icons_cover_required_sizes_and_files_exist():
    manifest = _load_manifest()
    sizes_present = {icon["sizes"] for icon in manifest["icons"]}

    assert REQUIRED_ICON_SIZES.issubset(sizes_present)

    for icon in manifest["icons"]:
        # icon["src"] es una ruta absoluta tipo "/static/icons/icon-192.png"
        relative_path = icon["src"].removeprefix("/static/")
        icon_path = os.path.join(STATIC_DIR, relative_path)
        assert os.path.isfile(icon_path), f"falta el archivo de ícono: {icon_path}"


def test_manifest_has_a_maskable_icon():
    """Sin un ícono "maskable", Android/algunos launchers recortan el ícono
    "any" sin respetar la zona segura y el diseño puede quedar cortado."""
    manifest = _load_manifest()
    purposes = {icon.get("purpose") for icon in manifest["icons"]}
    assert "maskable" in purposes


# ---------- service worker: servido desde la raíz, no solo /static/ ----------

def test_service_worker_served_from_root_scope(client):
    """Debe vivir en "/service-worker.js" (no solo bajo /static/) para que su
    scope por defecto cubra "/" — el start_url del manifest — y el navegador
    pueda ofrecer instalar la app."""
    response = client.get("/service-worker.js")

    assert response.status_code == 200
    assert "javascript" in response.content_type


def test_robots_txt_served_from_root_and_blocks_authenticated_routes(client):
    """robots.txt solo lo buscan los crawlers en la raíz real, nunca bajo
    /static/ -- y debe bloquear rutas sin valor de SEO, en particular
    /reset-password/ (lleva un token secreto en la propia URL)."""
    response = client.get("/robots.txt")

    assert response.status_code == 200
    assert "text/plain" in response.content_type
    body = response.get_data(as_text=True)
    assert "Disallow: /reset-password/" in body
    assert "Disallow: /dashboard" in body


def test_service_worker_only_touches_static_assets():
    """Chequeo de diseño, no de comportamiento en runtime (no hay motor JS
    en la suite de Python): el archivo debe declarar explícitamente que
    cachea solo bajo /static/, nunca HTML ni rutas con datos de usuario —
    ver el comentario de cabecera del propio archivo para el razonamiento
    completo."""
    sw_path = os.path.join(STATIC_DIR, "service-worker.js")
    with open(sw_path, encoding="utf-8") as f:
        content = f.read()

    assert 'pathname.startsWith("/static/")' in content


# ---------- base.html referencia el manifest y los íconos ----------

def test_pages_link_the_manifest_and_icons(client):
    response = client.get("/")

    assert b'rel="manifest"' in response.data
    assert b"manifest.json" in response.data
    assert b"icon-192.png" in response.data
