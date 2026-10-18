import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup


def public_address(url):
    """Resolve once so the actual connection uses the checked IP address."""
    parts = urlsplit(url)
    if (
        parts.scheme not in ("http", "https")
        or not parts.hostname
        or parts.username
        or parts.password
    ):
        raise ValueError("Bitte einen öffentlichen HTTP- oder HTTPS-Link eingeben.")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    addresses = socket.getaddrinfo(parts.hostname, port, type=socket.SOCK_STREAM)
    if not addresses or any(
        not ipaddress.ip_address(item[4][0]).is_global for item in addresses
    ):
        raise ValueError("Lokale und private Adressen sind nicht erlaubt.")
    return parts, addresses[0][4][0], port


def scrape_article(url):
    for _ in range(4):
        parts, address, port = public_address(url)
        connection = http.client.HTTPConnection(parts.hostname, port, timeout=15)
        try:
            connection.sock = socket.create_connection((address, port), timeout=15)
            if parts.scheme == "https":
                connection.sock = ssl.create_default_context().wrap_socket(
                    connection.sock, server_hostname=parts.hostname
                )
            path = parts.path or "/"
            if parts.query:
                path += "?" + parts.query
            connection.request(
                "GET",
                path,
                headers={"User-Agent": "Polycast/1.0", "Accept-Encoding": "identity"},
            )
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location:
                    raise ValueError(
                        "Die Webseite liefert eine ungültige Weiterleitung."
                    )
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise ValueError(
                    "Der Artikel konnte nicht geladen werden. Bitte Text direkt einfügen."
                )
            if "text/html" not in response.getheader("Content-Type", ""):
                raise ValueError("Der Link muss auf eine HTML-Webseite zeigen.")
            html = response.read(2_000_001)
            if len(html) > 2_000_000:
                raise ValueError(
                    "Die Webseite ist zu gross. Bitte den Artikeltext direkt einfügen."
                )
        finally:
            connection.close()
        soup = BeautifulSoup(html, "html.parser")
        for element in soup.select(
            "script, style, nav, header, footer, aside, form, noscript, [hidden], [aria-hidden=true]"
        ):
            element.decompose()
        article = soup.find("article") or soup.find("main") or soup.body or soup
        paragraphs = article.find_all("p")
        text = (
            "\n\n".join(p.get_text(" ", strip=True) for p in paragraphs)
            if paragraphs
            else article.get_text(" ", strip=True)
        )
        if not text.strip():
            raise ValueError(
                "Kein Artikeltext gefunden. Bitte den Text direkt einfügen."
            )
        if len(text) > 20_000:
            raise ValueError(
                "Der Artikel hat mehr als 20'000 Zeichen. Bitte einen kürzeren Ausschnitt einfügen."
            )
        return text.strip()
    raise ValueError("Der Link leitet zu oft weiter.")
