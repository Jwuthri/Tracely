"""`assert_public_url` is what stops a customer-supplied URL from reaching the inside of the
deployment (ClickHouse's HTTP port, cloud metadata, …). Off outside prod by default."""

from __future__ import annotations

import socket

import pytest

from tracely.config import settings
from tracely.infrastructure.net import UnsafeURL, assert_public_url


@pytest.fixture
def strict(monkeypatch):
    monkeypatch.setattr(settings, "allow_private_urls", False)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8123/?query=SELECT%201",
        "http://[::1]:8123/",
        "http://10.0.0.5/",
        "http://192.168.1.10:8000/",
        "http://169.254.169.254/latest/meta-data/",
        "http://0.0.0.0/",
        "ftp://example.com/",
        "not a url",
        "",
    ],
)
def test_rejects_private_and_malformed(strict, url):
    with pytest.raises(UnsafeURL):
        assert_public_url(url)


def test_accepts_public_ip(strict):
    assert_public_url("https://8.8.8.8/hook")


def test_resolves_hostnames_before_judging(strict, monkeypatch):
    # `clickhouse` is a perfectly ordinary-looking name; what matters is where it resolves.
    def fake(host, port, *a, **kw):
        ip = {"clickhouse": "172.18.0.4", "hooks.slack.com": "3.5.6.7"}[host]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    with pytest.raises(UnsafeURL):
        assert_public_url("http://clickhouse:8123/")
    assert_public_url("https://hooks.slack.com/services/x")


def test_unresolvable_host_is_rejected(strict, monkeypatch):
    def fake(*a, **kw):
        raise socket.gaierror("nope")

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    with pytest.raises(UnsafeURL):
        assert_public_url("http://does-not-exist.invalid/")


def test_self_host_default_allows_localhost(monkeypatch):
    monkeypatch.setattr(settings, "allow_private_urls", None)
    monkeypatch.setattr(settings, "tracely_env", "docker")
    assert_public_url("http://host.docker.internal:9000/chat")
    assert_public_url("http://localhost:9000/chat")
    monkeypatch.setattr(settings, "tracely_env", "prod")
    with pytest.raises(UnsafeURL):
        assert_public_url("http://localhost:9000/chat")
