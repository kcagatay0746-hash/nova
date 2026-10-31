# Nova v2 — Araç Kullanan Türkçe Yapay Zekâ Asistanı

Nova, tek dosyalık bir “soruları yanıtlayan sohbet” değil; **planlayan, araç çağıran,
hafıza tutan ve yanıtı kelime kelime akıtan** bir Türkçe asistandır. Tarayıcıda
çalışan bir arayüz (mikrofon + yazı) ve FastAPI tabanlı bir ajan sunucusundan oluşur.

> v1 (tek dosya, sabit yanıtlar) → v2 (agentic döngü + gerçek araçlar + kalıcı hafıza + streaming).

## Ne yapabilir?

| Yetenek | Nasıl çalışır |
| --- | --- |
| Hava durumu + 3 günlük tahmin | `get_weather` → Open-Meteo (anahtarsız) |
| Güncel/genel bilgi | `web_search` → Vikipedi (tr/en) + DuckDuckGo |
| Matematik | `calculate` → AST tabanlı güvenli değerlendirici (eval yok) |
| Tarih/saat | `current_datetime` → zoneinfo, Türkçe okunuş |
| Site sağlığı + SEO temel kontrolü | `check_site` → durum kodu, süre, başlık, meta, dil, H1 |
| Kalıcı hafıza | `memory_save` / `memory_search` → SQLite |
| Kod incelemesi | `/api/review` |
| Sesli asistan | Web Speech API (tanıma + cümle bazlı seslendirme kuyruğu) |

Model, soruya göre hangi aracı çağıracağına **kendisi** karar verir; sonuçları
görüp gerekirse ikinci bir araç çağırır (en fazla `NOVA_MAX_TOOL_ROUNDS` tur).
Arayüz bu turları canlı gösterir: “Hava durumuna bakıyorum… ✓ Antalya 18°C”.

## Mimari

```
Tarayıcı (index.html + app.js + styles.css)
   │  POST /api/chat/stream  (SSE: status / tool_start / tool_result / delta / done)
   ▼
FastAPI (server.py)  ── hız sınırı, CORS, statik dosyalar
   ▼
NovaAgent (nova/agent.py)  ── çok adımlı araç döngüsü + olay akışı
   ├── nova/llm.py      Anthropic | OpenAI uyumlu | çevrimdışı demo
   ├── nova/tools.py    get_weather, web_search, calculate, current_datetime,
   │                    check_site, memory_save, memory_search
   ├── nova/memory.py   SQLite: facts + messages
   ├── nova/safety.py   SSRF/DNS koruması, hız sınırı, girdi temizleme
   └── nova/prompts.py  Türkçe sistem promptları (sesli/yazılı)
```

## Hızlı başlangıç

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Gerçek model için (opsiyonel — anahtar yoksa demo modunda çalışır)
export ANTHROPIC_API_KEY="sk-ant-..."

export NOVA_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt   # kurumsal proxy varsa
uvicorn server:app --host 0.0.0.0 --port 5000
```

Tarayıcıda `http://localhost:5000` adresini aç.

**Demo modu:** API anahtarı yoksa Nova otomatik olarak `offline` sağlayıcıya düşer.
Bu modda gerçek bir dil modeli yoktur; niyet tespiti + gerçek araçlar çalışır
(hava durumu, saat, hesap, web araması, hafıza). Arayüz ve ajan akışı anahtarsız
da test edilebilir. Rozet “Demo · nova-local-v2” gösterir.

## Ortam değişkenleri

| Değişken | Varsayılan | Açıklama |
| --- | --- | --- |
| `NOVA_PROVIDER` | anahtara göre | `anthropic`, `openai`, `offline` |
| `ANTHROPIC_API_KEY` | — | Claude anahtarı |
| `NOVA_MODEL` | `claude-sonnet-5-5` | Model kimliği |
| `NOVA_BASE_URL` | — | OpenAI uyumlu uç nokta (Ollama/vLLM/OpenRouter) |
| `NOVA_MAX_TOKENS` | `800` | Yanıt başına token sınırı |
| `NOVA_EFFORT` | `medium` | Anthropic çaba seviyesi (`low`…`max`) |
| `NOVA_TEMPERATURE` | `0.4` | Yalnızca OpenAI uyumlu sağlayıcılar |
| `NOVA_MAX_TOOL_ROUNDS` | `4` | Araç turu üst sınırı |
| `NOVA_HISTORY_LIMIT` | `10` | Bağlama katılan son mesaj sayısı |
| `NOVA_MEMORY_DB` | `./nova.db` | SQLite hafıza dosyası |
| `NOVA_RATE_LIMIT` | `90` | IP başına dakikalık istek (0 = kapalı) |
| `NOVA_ALLOW_PRIVATE_HOSTS` | `false` | `check_site` iç ağa erişebilsin mi |
| `NOVA_CA_BUNDLE` | — | Özel CA dosyası (proxy/TLS) |
| `NOVA_CORS_ORIGINS` | `*` | Virgülle ayrılmış izinli origin listesi |

## Uç noktalar

| Metot | Yol | Açıklama |
| --- | --- | --- |
| POST | `/api/chat/stream` | SSE ile akan ajan yanıtı (arayüz bunu kullanır) |
| GET | `/api/chat/stream?q=...` | Aynı akış, `EventSource` uyumlu |
| POST | `/api/ask` | Akışsız tek yanıt (v1 uyumlu) |
| POST | `/api/review` | Kod incelemesi |
| POST | `/api/site-check` | Site kontrolü + isteğe bağlı model analizi |
| GET/POST/DELETE | `/api/memory` | Hafıza notlarını listele / ekle / sil |
| GET | `/api/tools` | Araç şemaları (JSON Schema) |
| GET | `/api/health` | Sürüm, sağlayıcı, mod, hafıza istatistikleri |

Örnek:

```bash
curl -N -X POST localhost:5000/api/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"question":"Antalya hava nasıl","session_id":"demo"}'
```

## Testler

```bash
pip install -r requirements-dev.txt
pytest              # 78 test, tamamı ağsız (hermetik)
ruff check .        # stil/lint
```

Testler sahte sağlayıcı ve sahte araç handler'ları kullanır; internet veya API
anahtarı gerektirmez.

## Güvenlik notları

- **SSRF koruması:** `check_site` adresi çözümler, özel/loopback/link-local
  adresleri reddeder (`nova/safety.py`). `NOVA_ALLOW_PRIVATE_HOSTS=true` bilinçli tercih.
- **Hesap makinesi:** `eval`/`exec` yok; yalnızca izinli AST düğümleri, üs ve düğüm
  sayısı sınırlı.
- **Prompt enjeksiyonu:** sistem promptu, kullanıcı metnindeki “önceki kuralları unut”
  tipi talimatları yok saymasını söyler.
- **Hız sınırı** ve **girdi uzunluğu** sınırları sunucu tarafında uygulanır.
- Araç sonuçları modele gönderilmeden önce 6 KB ile kırpılır; anahtar asla istemciye gitmez.

## v1'den farkları

- `claude_haiku_4_5` gibi geçersiz model kimliği yerine yapılandırılabilir model + doğrulama.
- Anahtar yokken çöken sunucu yerine çalışan demo modu.
- `Function()` ile ifade çalıştırma yerine AST tabanlı güvenli hesap.
- Tek seferlik yanıt yerine araç turları, akış (streaming) ve kaynak gösterimi.
- Hafıza paneli, “yeni sohbet”, durdur düğmesi ve araç etkinlik rozetleri.
- 78 birim/entegrasyon testi ve lint temizliği.
