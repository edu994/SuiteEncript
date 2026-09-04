from app.utils import news_feed as news_feed_module
from app.utils.news_feed import get_security_news


class _FakeResponse:
    def __init__(self, content, status_code=200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise news_feed_module.requests.HTTPError("boom")


def _rss(items_xml: str) -> bytes:
    return f"""<?xml version="1.0"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel>
<title>Feed de prueba</title>
{items_xml}
</channel>
</rss>""".encode()


def _reset_cache():
    news_feed_module._cache["items"] = None
    news_feed_module._cache["fetched_at"] = 0.0


def test_extracts_image_from_enclosure(monkeypatch):
    _reset_cache()
    xml = _rss("""
        <item>
            <title>Artículo con enclosure</title>
            <link>https://example.com/a</link>
            <description>Resumen</description>
            <pubDate>Tue, 25 Aug 2026 10:00:00 GMT</pubDate>
            <enclosure url="https://img.example.com/foto.jpg" type="image/jpeg" length="1000"/>
        </item>
    """)
    monkeypatch.setattr(
        news_feed_module.requests, "get",
        lambda url, timeout, headers: _FakeResponse(xml),
    )

    items = get_security_news()

    # Los 3 feeds configurados devuelven el mismo XML de prueba acá (el
    # mock no distingue por URL) -- lo que importa es que la imagen del
    # enclosure se extrajo bien, no cuántos feeds "respondieron".
    assert len(items) > 0
    assert items[0]["image"] == "https://img.example.com/foto.jpg"


def test_extracts_image_from_content_html(monkeypatch):
    _reset_cache()
    xml = _rss("""
        <item>
            <title>Artículo con imagen en el contenido</title>
            <link>https://example.com/b</link>
            <description>Resumen sin imagen</description>
            <pubDate>Tue, 25 Aug 2026 10:00:00 GMT</pubDate>
            <content:encoded><![CDATA[<p>Texto</p><img src="https://img.example.com/inline.png"/>]]></content:encoded>
        </item>
    """)
    monkeypatch.setattr(
        news_feed_module.requests, "get",
        lambda url, timeout, headers: _FakeResponse(xml),
    )

    items = get_security_news()

    assert items[0]["image"] == "https://img.example.com/inline.png"


def test_item_without_image_gets_none_not_a_crash(monkeypatch):
    _reset_cache()
    xml = _rss("""
        <item>
            <title>Artículo sin imagen</title>
            <link>https://example.com/c</link>
            <description>Solo texto, sin img</description>
            <pubDate>Tue, 25 Aug 2026 10:00:00 GMT</pubDate>
        </item>
    """)
    monkeypatch.setattr(
        news_feed_module.requests, "get",
        lambda url, timeout, headers: _FakeResponse(xml),
    )

    items = get_security_news()

    assert items[0]["image"] is None


def test_items_with_image_are_prioritized_over_more_recent_ones_without(monkeypatch):
    """BleepingComputer nunca trae imagen en su RSS -- si el orden fuera solo
    por fecha, un día con varios de sus artículos entre los más recientes
    dejaría el carrusel lleno de íconos de respaldo en vez de fotos reales.
    Acá el artículo con imagen es más viejo que el que no tiene, y aun así
    debe aparecer primero."""
    _reset_cache()

    con_imagen = _rss("""
        <item>
            <title>Artículo viejo con imagen</title>
            <link>https://example.com/con-imagen</link>
            <description>Resumen</description>
            <pubDate>Mon, 24 Aug 2026 08:00:00 GMT</pubDate>
            <enclosure url="https://img.example.com/foto.jpg" type="image/jpeg" length="1000"/>
        </item>
    """)
    sin_imagen = _rss("""
        <item>
            <title>Artículo nuevo sin imagen</title>
            <link>https://example.com/sin-imagen</link>
            <description>Resumen</description>
            <pubDate>Wed, 26 Aug 2026 08:00:00 GMT</pubDate>
        </item>
    """)

    def fake_get(url, timeout, headers):
        if "TheHackersNews" in url:
            return _FakeResponse(con_imagen)
        return _FakeResponse(sin_imagen)

    monkeypatch.setattr(news_feed_module.requests, "get", fake_get)

    items = get_security_news()

    assert items[0]["image"] == "https://img.example.com/foto.jpg"
    assert items[0]["title"] == "Artículo viejo con imagen"


def test_a_down_feed_is_skipped_not_fatal(monkeypatch):
    _reset_cache()

    def fake_get(url, timeout, headers):
        if "TheHackersNews" in url:
            raise news_feed_module.requests.ConnectionError("sin red")
        return _FakeResponse(_rss("""
            <item>
                <title>Noticia disponible</title>
                <link>https://example.com/d</link>
                <description>Resumen</description>
                <pubDate>Tue, 25 Aug 2026 10:00:00 GMT</pubDate>
            </item>
        """))

    monkeypatch.setattr(news_feed_module.requests, "get", fake_get)

    items = get_security_news()

    assert len(items) > 0
    assert all(item["title"] for item in items)
