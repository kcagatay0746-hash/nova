"""Güvenlik yardımcıları.

- SSRF koruması: kullanıcı URL'leri çözümlenip özel/iç ağ adresleri engellenir.
- Hız sınırı: bellek içi kayan pencere sayacı.
- Metin temizleme: kontrol karakterleri ve aşırı uzunluk.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import time
from collections import defaultdict, deque
from urllib.parse import urlsplit, urlunsplit

ALLOWED_SCHEMES = ("http", "https")
MAX_INPUT_CHARS = 4000
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class SafetyError(ValueError):
    """Kullanıcı girdisi güvenlik kurallarını ihlal ettiğinde fırlatılır."""


# ---------------------------------------------------------------- metin

def clean_text(raw: str, limit: int = MAX_INPUT_CHARS) -> str:
    """Kontrol karakterlerini atar, boşlukları düzenler, uzunluğu sınırlar."""
    if not isinstance(raw, str):
        raise SafetyError("Metin bekleniyordu.")
    text = _CONTROL_RE.sub(" ", raw)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > limit:
        text = text[: max(1, limit - 2)].rstrip() + " …"
    return text


def clip(text: str, limit: int) -> str:
    """Uzun metni güvenli biçimde kısaltır."""
    text = text or ""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


# ---------------------------------------------------------------- URL / SSRF

def normalize_url(raw: str) -> str:
    """Kullanıcıdan gelen adresi http(s) URL'sine dönüştürür."""
    candidate = (raw or "").strip()
    if not candidate:
        raise SafetyError("Adres boş.")
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", candidate):
        candidate = "https://" + candidate
    parts = urlsplit(candidate)
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise SafetyError("Yalnızca http ve https adresleri kontrol edilebilir.")
    if not parts.hostname:
        raise SafetyError("Adres geçersiz.")
    netloc = parts.hostname
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", parts.query, ""))


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _host_literal_is_public(host: str) -> bool | None:
    """Host zaten IP ise doğrudan değerlendirir; değilse None döner."""
    try:
        return _is_public_ip(ipaddress.ip_address(host))
    except ValueError:
        return None


async def assert_public_url(url: str, *, allow_private: bool = False) -> str:
    """URL'yi doğrular ve hedef adresin genel (public) olduğunu garanti eder."""
    normalized = normalize_url(url)
    host = urlsplit(normalized).hostname or ""
    lowered = host.lower().rstrip(".")
    local_names = {"localhost", "localhost.localdomain"}
    is_local_name = lowered in local_names or lowered.endswith((".local", ".internal", ".lan", ".home"))
    if is_local_name and not allow_private:
        raise SafetyError("İç ağ adresleri kontrol edilemez.")
    literal = _host_literal_is_public(lowered)
    if literal is False and not allow_private:
        raise SafetyError("İç ağ adresleri kontrol edilemez.")
    if literal is True:
        return normalized
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(lowered, None, family=socket.AF_UNSPEC)
    except socket.gaierror as exc:
        raise SafetyError("Adres çözümlenemedi: " + lowered) from exc
    addresses = {info[4][0] for info in infos}
    if not addresses:
        raise SafetyError("Adres çözümlenemedi: " + lowered)
    if not allow_private:
        for address in addresses:
            try:
                ip = ipaddress.ip_address(address.split("%")[0])
            except ValueError:
                continue
            if not _is_public_ip(ip):
                raise SafetyError("Adres iç ağa çözümleniyor, kontrol edilemez.")
    return normalized


# ---------------------------------------------------------------- hız sınırı

class RateLimiter:
    """Basit kayan pencere hız sınırlayıcı (tek süreç, bellek içi)."""

    def __init__(self, max_calls: int, window_seconds: float = 60.0) -> None:
        self.max_calls = max(0, int(max_calls))
        self.window = float(window_seconds)
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        if self.max_calls <= 0:
            return True
        now = time.monotonic()
        bucket = self._hits[key]
        while bucket and now - bucket[0] > self.window:
            bucket.popleft()
        if len(bucket) >= self.max_calls:
            return False
        bucket.append(now)
        return True

    def retry_after(self, key: str) -> int:
        bucket = self._hits.get(key)
        if not bucket:
            return 0
        return max(1, int(self.window - (time.monotonic() - bucket[0])))
