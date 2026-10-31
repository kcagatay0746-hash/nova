"""Nova yapılandırması.

Tüm ayarlar ortam değişkenlerinden okunur; hiçbir ayar zorunlu değildir.
API anahtarı yoksa Nova otomatik olarak çevrimdışı (demo) sağlayıcıya düşer,
böylece arayüz ve araç döngüsü anahtarsız da çalışır.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__

BASE_DIR = Path(__file__).resolve().parent.parent

PROVIDER_DEFAULTS = {
    "anthropic": "claude-sonnet-5-5",
    "openai": "gpt-4o-mini",
    "offline": "nova-local-v2",
}


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(_env(name, str(default))))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(str(_env(name, str(default))))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "evet", "on", "açık"}


def _env_list(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    raw = _env(name)
    if not raw:
        return default
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _detect_provider() -> str:
    explicit = _env("NOVA_PROVIDER")
    if explicit:
        return explicit.lower()
    if _env("ANTHROPIC_API_KEY"):
        return "anthropic"
    if _env("OPENAI_API_KEY"):
        return "openai"
    return "offline"


@dataclass(frozen=True)
class Settings:
    """Değiştirilemez (immutable) çalışma zamanı ayarları."""

    provider: str = "offline"
    model: str = "nova-local-v2"
    api_key: str | None = None
    base_url: str | None = None
    max_tokens: int = 800
    temperature: float = 0.4  # OpenAI uyumlu sağlayıcılar için
    effort: str = "medium"  # Anthropic: low | medium | high | xhigh | max
    max_tool_rounds: int = 4
    history_limit: int = 10
    memory_db: Path = BASE_DIR / "nova.db"
    memory_limit: int = 200
    allow_private_hosts: bool = False
    rate_limit_per_minute: int = 90
    request_timeout: float = 20.0
    ca_bundle: str | None = None  # özel CA dosyası (kurumsal proxy arkasında)
    static_dir: Path = BASE_DIR
    cors_origins: tuple[str, ...] = field(default_factory=tuple)
    log_level: str = "INFO"
    version: str = __version__

    @classmethod
    def from_env(cls) -> "Settings":
        provider = _detect_provider()
        default_model = PROVIDER_DEFAULTS.get(provider, PROVIDER_DEFAULTS["offline"])
        return cls(
            provider=provider,
            model=_env("NOVA_MODEL", default_model) or default_model,
            api_key=_env("ANTHROPIC_API_KEY") or _env("OPENAI_API_KEY"),
            base_url=_env("NOVA_BASE_URL") or _env("ANTHROPIC_BASE_URL") or _env("OPENAI_BASE_URL"),
            max_tokens=_env_int("NOVA_MAX_TOKENS", 800),
            temperature=_env_float("NOVA_TEMPERATURE", 0.4),
            effort=_env("NOVA_EFFORT", "medium") or "medium",
            max_tool_rounds=_env_int("NOVA_MAX_TOOL_ROUNDS", 4),
            history_limit=_env_int("NOVA_HISTORY_LIMIT", 10),
            memory_db=Path(_env("NOVA_MEMORY_DB", str(BASE_DIR / "nova.db")) or "nova.db"),
            memory_limit=_env_int("NOVA_MEMORY_LIMIT", 200),
            allow_private_hosts=_env_bool("NOVA_ALLOW_PRIVATE_HOSTS", False),
            rate_limit_per_minute=_env_int("NOVA_RATE_LIMIT", 90),
            request_timeout=_env_float("NOVA_REQUEST_TIMEOUT", 20.0),
            ca_bundle=_env("NOVA_CA_BUNDLE") or _env("SSL_CERT_FILE"),
            static_dir=Path(_env("NOVA_STATIC_DIR", str(BASE_DIR)) or "."),
            cors_origins=_env_list("NOVA_CORS_ORIGINS"),
            log_level=(_env("NOVA_LOG_LEVEL", "INFO") or "INFO").upper(),
            version=__version__,
        )

    def public(self) -> dict:
        """Sağlık uç noktası için anahtar sızdırmayan özet."""
        return {
            "version": self.version,
            "provider": self.provider,
            "model": self.model,
            "max_tool_rounds": self.max_tool_rounds,
            "effort": self.effort,
            "tools_enabled": True,
            "rate_limit_per_minute": self.rate_limit_per_minute,
        }
