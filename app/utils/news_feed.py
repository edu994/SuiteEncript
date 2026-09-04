"""Noticias de seguridad reales para la landing pública, vía feeds RSS.

Un feed caído o lento nunca debe romper ni frenar la carga de la landing —
se omite ese feed puntual y se sigue con los demás, mismo criterio que el
resto del proyecto ante servicios externos opcionales (ver
app/utils/hibp.py). La descarga se hace con `requests` (con timeout real),
no con el fetch interno de `feedparser`, que no tiene un timeout garantizado
y podría dejar la petición colgada si un feed no responde.
"""
import re
import time
from email.utils import parsedate_to_datetime

import feedparser
import requests

FEEDS = [
    ("The Hacker News", "https://feeds.feedburner.com/TheHackersNews"),
    ("BleepingComputer", "https://www.bleepingcomputer.com/feed/"),
    ("Krebs on Security", "https://krebsonsecurity.com/feed/"),
]

MAX_ITEMS = 6
CACHE_TTL_SECONDS = 30 * 60
FEED_TIMEOUT_SECONDS = 4
SUMMARY_MAX_CHARS = 160

_cache = {"items": None, "fetched_at": 0.0}


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _format_date(entry) -> str:
    try:
        return parsedate_to_datetime(entry.get("published", "")).strftime("%d %b")
    except (TypeError, ValueError):
        return ""


def _extract_image(entry) -> str | None:
    """Imagen propia del artículo, si el feed la trae -- para el carrusel
    de la landing. Primero el enclosure (así la trae The Hacker News);
    si no hay, el primer <img> del HTML del artículo (así la trae Krebs).
    BleepingComputer no incluye imagen en ninguna de las dos formas -- en
    ese caso queda en None y la plantilla usa un estado vacío, nunca rompe."""
    for enclosure in entry.get("enclosures", []):
        if "image" in enclosure.get("type", ""):
            return enclosure.get("href")

    html = ""
    content = entry.get("content")
    if content:
        html = content[0].get("value", "")
    if not html:
        html = entry.get("summary", "")
    match = re.search(r'<img[^>]+src=["\'](.*?)["\']', html)
    return match.group(1) if match else None


def _fetch_feed(source: str, url: str) -> list:
    try:
        response = requests.get(
            url,
            timeout=FEED_TIMEOUT_SECONDS,
            headers={"User-Agent": "SuiteEncript/1.0"},
        )
        response.raise_for_status()
    except requests.RequestException:
        return []

    parsed = feedparser.parse(response.content)
    items = []
    for entry in parsed.entries[:3]:
        summary = _strip_html(entry.get("summary", ""))[:SUMMARY_MAX_CHARS]
        items.append({
            "source": source,
            "title": entry.get("title", "").strip(),
            "link": entry.get("link", ""),
            "summary": summary,
            "published": _format_date(entry),
            "image": _extract_image(entry),
            "_sort_key": entry.get("published_parsed") or time.gmtime(0),
        })
    return items


def get_security_news() -> list:
    """Hasta MAX_ITEMS noticias reales, mezcladas de los feeds y cacheadas en
    memoria por CACHE_TTL_SECONDS para no golpear los feeds en cada visita a
    la landing. Lista vacía si todos los feeds fallan — la plantilla ya
    maneja ese caso mostrando un estado vacío.

    Orden: primero las que traen imagen propia, más recientes primero;
    después las que no. BleepingComputer nunca trae imagen en su RSS (ver
    _extract_image) — si se ordenara solo por fecha, un día con varios
    artículos suyos entre los más recientes llenaría el carrusel de tarjetas
    con el ícono de respaldo en vez de la foto real del artículo. Esto no
    excluye BleepingComputer, solo lo prioriza después de lo que sí tiene
    imagen, para que el carrusel se vea bien la mayoría de las veces sin
    dejar de mostrar sus noticias cuando hay lugar."""
    now = time.time()
    if _cache["items"] is not None and (now - _cache["fetched_at"]) < CACHE_TTL_SECONDS:
        return _cache["items"]

    items = []
    for source, url in FEEDS:
        items.extend(_fetch_feed(source, url))

    items.sort(key=lambda i: (bool(i["image"]), i["_sort_key"]), reverse=True)
    for item in items:
        del item["_sort_key"]
    items = items[:MAX_ITEMS]

    _cache["items"] = items
    _cache["fetched_at"] = now
    return items
