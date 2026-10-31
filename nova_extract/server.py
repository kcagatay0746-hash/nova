# Nova — Sesli Asistan backend
# Gelişmiş sorular için LLM API'si sunar ve statik dosyaları servis eder.

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from anthropic import Anthropic
import re
import time
import requests as httpx_requests

app = FastAPI()
client = Anthropic()

MODEL = "claude_haiku_4_5"

SYSTEM_PROMPT = (
    "Sen Nova adında Türkçe konuşan bir sesli asistansın. "
    "Sana sesli soru soruluyor; cevapların sesli okunacak, bu yüzden KISA olmalı: "
    "en fazla 3-4 cümle, doğal konuşma diliyle, madde işareti veya list kullanmadan. "
    "Matematik sorusu gelirse önce net sonucu söyle (örn. 'Cevap 25.'), gerekirse "
    "en fazla bir cümleyle açıkla; uzun adım adım çözüm anlatma. "
    "Kullanıcının vereceğin bağlam bilgisi (hava durumu, pil seviyesi) varsa soruyla ilgiliyse kullan. "
    "Kendinden bahsederken 'Ben Nova' diyeceksin. Yalnızca Türkçe cevap ver."
)


def build_messages(question, history):
    messages = []
    for item in history:
        role = "assistant" if item.get("who") == "bot" else "user"
        text = (item.get("text") or "").strip()
        if text:
            messages.append({"role": role, "content": text})
    messages.append({"role": "user", "content": question})
    return messages


@app.post("/api/ask")
def ask(body: dict):
    question = (body.get("question") or "").strip()
    if not question:
        return {"answer": "Sorunu duyamadım, tekrar eder misin?"}
    context = body.get("context") or {}
    history = body.get("history") or []

    system = SYSTEM_PROMPT
    if context:
        parts = []
        if context.get("place"):
            parts.append("Kullanıcının konumu: " + context["place"])
        if context.get("weather"):
            parts.append("Anlık hava: " + context["weather"])
        if context.get("battery"):
            parts.append("Cihaz pili: " + context["battery"])
        if parts:
            system = SYSTEM_PROMPT + "\n\nBağlam: " + "; ".join(parts)

    try:
        msg = client.messages.create(
            model=MODEL,
            max_tokens=400,
            system=system,
            messages=build_messages(question, history),
        )
        answer = ""
        for block in msg.content:
            if getattr(block, "text", None):
                answer += block.text
        answer = answer.strip()
        if answer:
            return {"answer": answer}
    except Exception as e:
        return {"error": str(e), "answer": None}

    return {"answer": None}


# ---------- Uygulama kontrolü ----------

REVIEW_PROMPT = (
    "Sen Nova adlı asistanın kod inceleme modundasın. Verilen kodu deneyimli bir "
    "yazılım geliştiricisi gözüyle Türkçe olarak incele. Şu başlıklar altında, maddeler "
    "halinde ve net ol: 1) Hatalar ve riskler (bug, güvenlik açığı, mantık hatası), "
    "2) Performans sorunları, 3) Okunabilirlik ve iyileştirme önerileri. Önce tek cümleyle "
    "kodun ne yaptığını söyle. Sorun yoksa bunu açıkça belirt ve uydurma sorun çıkarma. "
    "Kod çalışıyorsa abartılı öneriler yerine en önemli 3-5 noktaya odaklan."
)


def llm_text(system, user_content, max_tokens=1500):
    msg = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_content}],
    )
    out = ""
    for block in msg.content:
        if getattr(block, "text", None):
            out += block.text
    return out.strip()


@app.post("/api/review")
def review(body: dict):
    code = (body.get("code") or "").strip()
    filename = (body.get("filename") or "").strip()
    if not code:
        return {"review": None}
    if len(code) > 60000:
        code = code[:60000] + "\n... (kod kısaltıldı)"
    header = "İncelenecek dosya: " + (filename or "belirtilmedi") + "\n\n"
    try:
        result = llm_text(REVIEW_PROMPT, header + code)
        return {"review": result}
    except Exception as e:
        return {"error": str(e), "review": None}


PRIVATE_HOST_RE = re.compile(
    r"^(localhost|127\.|0\.0\.0\.0|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|\[::1\])",
    re.IGNORECASE,
)


@app.post("/api/site-check")
def site_check(body: dict):
    raw_url = (body.get("url") or "").strip()
    if not raw_url:
        return {"error": "URL boş"}
    if not re.match(r"https?://", raw_url):
        raw_url = "https://" + raw_url

    host = re.sub(r"^https?://", "", raw_url).split("/")[0].split(":")[0]
    if PRIVATE_HOST_RE.match(host) or host.endswith(".local") or host.endswith(".internal"):
        return {"error": "Bu adres kontrol edilemez (iç ağ adresleri kapalı)."}

    result = {
        "url": raw_url,
        "up": False,
        "status": None,
        "responseTime": None,
        "size": None,
        "title": None,
        "analysis": None,
    }
    html = ""
    try:
        t0 = time.time()
        res = httpx_requests.get(
            raw_url,
            timeout=15,
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Nova Asistan Site Kontrol)"},
        )
        result["responseTime"] = int((time.time() - t0) * 1000)
        result["status"] = res.status_code
        result["up"] = res.status_code < 400
        result["size"] = len(res.content or b"")
        if res.status_code < 400:
            html = (res.text or "")[:200000]
    except Exception as e:
        result["error"] = "Bağlantı kurulamadı: " + str(e)[:120]
        return result

    # Başlık ve açıklama çıkar
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if m:
        result["title"] = m.group(1).strip()[:150]

    # LLM analizi (çalışan siteler için)
    if result["up"]:
        try:
            facts = (
                "Adres: " + raw_url
                + "\nHTTP durum: " + str(result["status"])
                + "\nYanıt süresi: " + str(result["responseTime"]) + " ms"
                + "\nSayfa başlığı: " + (result["title"] or "(yok)")
                + "\nSayfa boyutu: " + str(result["size"] or "?") + " bayt"
            )
            snippet = html[:12000]
            analysis = llm_text(
                "Sen Nova adlı asistanın site analiz modundasın. Verilen web sayfasını "
                "Türkçe, kısa (en fazla 5-6 cümle) ve maddeler halinde değerlendir: "
                "sayfanın içeriği ne, teknik durum nasıl (başlık/meta/erişilebilirlik "
                "temel kontrolleri), en dikkat çeken 2-3 sorun veya iyileştirme önerisi ne. "
                "Uydurma yapma, HTML'de olmayanı söyleme.",
                facts + "\n\nSayfanın HTML kodu (ilk bölüm):\n" + snippet,
                max_tokens=600,
            )
            result["analysis"] = analysis
        except Exception:
            pass

    return result


# Statik dosyalar (API rotalarından sonra mount edilmeli)
app.mount("/", StaticFiles(directory=".", html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=5000)
