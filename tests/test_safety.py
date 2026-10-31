"""Güvenlik yardımcılarının testleri (SSRF, metin temizleme, hız sınırı)."""

from __future__ import annotations

import asyncio
import socket

import pytest

from nova.safety import (
    RateLimiter,
    SafetyError,
    assert_public_url,
    clean_text,
    clip,
    normalize_url,
)


def test_clean_text_strips_control_chars_and_collapses_spaces():
    assert clean_text("merhaba\x00\x07  dünya") == "merhaba dünya"


def test_clean_text_truncates_long_input():
    result = clean_text("a" * 5000, limit=100)
    assert len(result) <= 101
    assert result.endswith("…")


def test_clean_text_rejects_non_string():
    with pytest.raises(SafetyError):
        clean_text(None)  # type: ignore[arg-type]


def test_clip_keeps_short_text():
    assert clip("kısa", 10) == "kısa"
    assert len(clip("uzun metin", 5)) == 5


def test_normalize_url_adds_scheme():
    assert normalize_url("ornek.com/yol?a=1") == "https://ornek.com/yol?a=1"


def test_normalize_url_rejects_other_schemes():
    with pytest.raises(SafetyError):
        normalize_url("file:///etc/passwd")


@pytest.mark.parametrize("url", ["localhost:8000", "http://127.0.0.1", "http://10.0.0.5", "http://[::1]/"])
def test_assert_public_url_blocks_private_literals(url):
    with pytest.raises(SafetyError):
        asyncio.run(assert_public_url(url))


def test_assert_public_url_allows_public_literal():
    assert asyncio.run(assert_public_url("http://93.184.216.34")) == "http://93.184.216.34/"


def test_assert_public_url_blocks_hostname_resolving_to_private(monkeypatch):
    async def fake_getaddrinfo(host, port, family=None, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.20", 0))]

    fake_loop = type("Loop", (), {"getaddrinfo": staticmethod(fake_getaddrinfo)})
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: fake_loop())
    with pytest.raises(SafetyError):
        asyncio.run(assert_public_url("http://saldirgan.example"))


def test_assert_public_url_blocks_local_suffixes():
    with pytest.raises(SafetyError):
        asyncio.run(assert_public_url("http://yazici.local"))


def test_rate_limiter_blocks_after_limit():
    limiter = RateLimiter(2, window_seconds=60)
    assert limiter.allow("a") is True
    assert limiter.allow("a") is True
    assert limiter.allow("a") is False
    assert limiter.allow("b") is True


def test_rate_limiter_zero_disables_limit():
    limiter = RateLimiter(0)
    for _ in range(50):
        assert limiter.allow("x") is True
