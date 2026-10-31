"""Nova — Türkçe, araç kullanabilen (agentic) sesli yapay zekâ asistanı.

Paket yapısı:
    config   : ortam değişkenlerinden okunan ayarlar
    prompts  : sistem/rol promptları (Türkçe)
    safety   : SSRF koruması, hız sınırı, metin temizleme
    memory   : SQLite tabanlı kalıcı hafıza
    tools    : modelin çağırabildiği araçlar (hava, arama, hesap, ...)
    llm      : sağlayıcı soyutlaması (Anthropic / OpenAI uyumlu / çevrimdışı)
    agent    : çok adımlı araç döngüsü + olay (event) akışı
"""

__version__ = "2.0.0"

__all__ = ["__version__"]
