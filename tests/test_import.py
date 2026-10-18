import socket
from types import SimpleNamespace

import pytest

from services import scrape_article as importer


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.1.1",
        "192.168.0.1",
        "169.254.169.254",
        "0.0.0.0",
        "::1",
        "fc00::1",
        "::ffff:127.0.0.1",
    ],
)
def test_private_and_reserved_addresses_are_rejected(monkeypatch, address):
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: [(None, None, None, None, (address, 80))]
    )
    with pytest.raises(ValueError, match="private"):
        importer.public_address("http://example.test")


def test_extracts_article_and_connects_to_checked_ip(monkeypatch):
    connections = []
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(None, None, None, None, ("93.184.216.34", 80))],
    )
    monkeypatch.setattr(
        socket, "create_connection", lambda address, **k: connections.append(address)
    )
    html = b"<html><nav><p>Navigation</p></nav><article><p>Actual news.</p><aside><p>Advertisement</p></aside></article></html>"
    response = SimpleNamespace(
        status=200,
        getheader=lambda name, default=None: "text/html",
        read=lambda size: html,
    )
    monkeypatch.setattr(
        importer.http.client,
        "HTTPConnection",
        lambda *a, **k: SimpleNamespace(
            request=lambda *a, **k: None,
            getresponse=lambda: response,
            close=lambda: None,
        ),
    )
    assert importer.scrape_article("http://example.test/news") == "Actual news."
    assert connections == [("93.184.216.34", 80)]


def test_redirect_to_private_address_is_blocked(monkeypatch):
    def resolve(host, *args, **kwargs):
        ip = "127.0.0.1" if host == "localhost" else "93.184.216.34"
        return [(None, None, None, None, (ip, 80))]

    connections = []
    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(
        socket, "create_connection", lambda address, **k: connections.append(address)
    )
    response = SimpleNamespace(
        status=302, getheader=lambda name: "http://localhost/secret"
    )
    monkeypatch.setattr(
        importer.http.client,
        "HTTPConnection",
        lambda *a, **k: SimpleNamespace(
            request=lambda *a, **k: None,
            getresponse=lambda: response,
            close=lambda: None,
        ),
    )
    with pytest.raises(ValueError, match="private"):
        importer.scrape_article("http://example.test")
    assert len(connections) == 1


def test_invalid_link_returns_readable_error(client, auth):
    response = client.post(
        "/articles/extract", headers=auth, json={"url": "file:///etc/passwd"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["message"]
