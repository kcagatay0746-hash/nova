/* ============================================================
   Nova — Türkçe sesli asistan
   - Hava durumu: Open-Meteo (konum: tarayıcı izni, yoksa Antalya)
   - Şarj: Battery Status API
   - Matematik: gelişmiş sözel işlem desteği
   - Web araması: Vikipedi (TR) + DuckDuckGo
   - Ses: Web Speech API (SpeechRecognition + speechSynthesis)
   ============================================================ */

(function () {
  'use strict';

  /* ---------- Yardımcılar ---------- */

  const $ = (id) => document.getElementById(id);

  const statusEl = $('assistant-status');
  const conversationEl = $('conversation');
  const micBtn = $('mic-btn');

  function setStatus(text, interim) {
    statusEl.innerHTML = '';
    statusEl.append(document.createTextNode(text));
    if (interim) {
      const span = document.createElement('span');
      span.className = 'interim';
      span.textContent = ' ' + interim;
      statusEl.append(span);
    }
  }

  function addMsg(who, text, link) {
    history.push({ who, text });
    if (history.length > 12) history.splice(0, history.length - 12);
    const div = document.createElement('div');
    div.className = 'msg msg-' + who;
    div.setAttribute('data-testid', 'msg-' + who);
    div.append(document.createTextNode(text));
    if (link && link.url) {
      div.append(document.createElement('br'));
      const a = document.createElement('a');
      a.href = link.url;
      a.target = '_blank';
      a.rel = 'noopener';
      a.textContent = 'Kaynak: ' + (link.label || link.url);
      div.append(a);
    }
    conversationEl.append(div);
    conversationEl.scrollTop = conversationEl.scrollHeight;
  }

  /* ---------- Tema ---------- */

  (function initTheme() {
    const root = document.documentElement;
    const btn = document.querySelector('[data-theme-toggle]');
    let dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    root.setAttribute('data-theme', dark ? 'dark' : 'light');
    btn.addEventListener('click', () => {
      dark = !dark;
      root.setAttribute('data-theme', dark ? 'dark' : 'light');
      btn.setAttribute('aria-label', dark ? 'Açık moda geç' : 'Koyu moda geç');
    });
  })();

  /* ---------- Konuşma (sentez) ---------- */

  const synth = window.speechSynthesis;
  let trVoice = null;

  function pickVoice() {
    if (!synth) return;
    const voices = synth.getVoices();
    trVoice =
      voices.find((v) => v.lang === 'tr-TR') ||
      voices.find((v) => v.lang && v.lang.toLowerCase().startsWith('tr')) ||
      null;
  }

  if (synth) {
    pickVoice();
    synth.addEventListener('voiceschanged', pickVoice);
  }

  function speak(text) {
    addMsg('bot', text);
    if (!synth) return;
    synth.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = 'tr-TR';
    if (trVoice) u.voice = trVoice;
    u.rate = 1;
    synth.speak(u);
  }

  /* ---------- Hava durumu ---------- */

  const WMO = {
    0: ['Açık ve güneşli', 'sun'],
    1: ['Az bulutlu', 'cloud-sun'],
    2: ['Parçalı bulutlu', 'cloud-sun'],
    3: ['Kapalı', 'cloud'],
    45: ['Sisli', 'fog'],
    48: ['Kırağılı sis', 'fog'],
    51: ['Hafif çisenti', 'rain'],
    53: ['Çisenti', 'rain'],
    55: ['Yoğun çisenti', 'rain'],
    56: ['Dondurucu çisenti', 'rain'],
    57: ['Yoğun dondurucu çisenti', 'rain'],
    61: ['Hafif yağmurlu', 'rain'],
    63: ['Yağmurlu', 'rain'],
    65: ['Şiddetli yağmurlu', 'rain'],
    66: ['Dondurucu yağmur', 'rain'],
    67: ['Şiddetli dondurucu yağmur', 'rain'],
    71: ['Hafif kar yağışlı', 'snow'],
    73: ['Kar yağışlı', 'snow'],
    75: ['Yoğun kar yağışlı', 'snow'],
    77: ['Kar taneli', 'snow'],
    80: ['Sağanak yağışlı', 'rain'],
    81: ['Sağanak yağışlı', 'rain'],
    82: ['Şiddetli sağanak', 'rain'],
    85: ['Kar sağanağı', 'snow'],
    86: ['Şiddetli kar sağanağı', 'snow'],
    95: ['Gök gürültülü fırtına', 'storm'],
    96: ['Dolulu fırtına', 'storm'],
    99: ['Şiddetli dolulu fırtına', 'storm'],
  };

  const ICONS = {
    sun: '<circle cx="12" cy="12" r="4.5"/><path d="M12 1.5v2.5M12 20v2.5M4.6 4.6l1.8 1.8M17.6 17.6l1.8 1.8M1.5 12h2.5M20 12h2.5M4.6 19.4l1.8-1.8M17.6 6.4l1.8-1.8"/>',
    moon: '<path d="M20.5 14.1A8.5 8.5 0 1 1 9.9 3.5a7 7 0 0 0 10.6 10.6z"/>',
    'cloud-sun': '<path d="M8 3v2M3.3 5.3l1.4 1.4M1.5 10h2"/><path d="M7 10a4 4 0 0 1 7.6-1.6A3.5 3.5 0 1 1 16 15.5H8a3 3 0 0 1 0-5.5z"/>',
    cloud: '<path d="M6.5 18a4.5 4.5 0 0 1 .9-8.9A5.5 5.5 0 0 1 18 10.5 4 4 0 0 1 17.5 18z"/>',
    rain: '<path d="M6.5 14a4.5 4.5 0 0 1 .9-8.9A5.5 5.5 0 0 1 18 6.5 4 4 0 0 1 17.5 14z"/><path d="M8 17.5v2M12 17.5v2M16 17.5v2"/>',
    snow: '<path d="M6.5 14a4.5 4.5 0 0 1 .9-8.9A5.5 5.5 0 0 1 18 6.5 4 4 0 0 1 17.5 14z"/><path d="M8 18h.01M12 20h.01M16 18h.01M10 20.5h.01M14 16.5h.01"/>',
    storm: '<path d="M6.5 13a4.5 4.5 0 0 1 .9-8.9A5.5 5.5 0 0 1 18 5.5 4 4 0 0 1 17.5 13z"/><path d="M12.5 12 9.5 17h3l-2 4.5 5-6.5h-3l2-3z"/>',
    fog: '<path d="M4 14h16M4 17.5h11M6 10.5h12"/><path d="M7.5 7a4 4 0 0 1 8-1 3 3 0 0 1 2 4.5"/>',
  };

  function iconSvg(kind) {
    return (
      '<svg class="weather-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      ICONS[kind] +
      '</svg>'
    );
  }

  const FALLBACK_LOC = { lat: 36.8969, lon: 30.7133, name: 'Antalya' };
  const state = {
    weather: null,
    placeName: null,
    battery: null,
  };

  // Konuşma geçmişi (yapay zekâ bağlamı için)
  const history = [];

  function weatherText(code) {
    return (WMO[code] || ['Bilinmiyor', 'cloud'])[0];
  }
  function weatherIcon(code, isDay) {
    const kind = (WMO[code] || [null, 'cloud'])[1];
    if (kind === 'sun') return isDay ? 'sun' : 'moon';
    return kind;
  }

  async function reverseGeocode(lat, lon) {
    try {
      const res = await fetch(
        'https://api.bigdatacloud.net/data/reverse-geocode-client?latitude=' +
          lat + '&longitude=' + lon + '&localityLanguage=tr'
      );
      const d = await res.json();
      return d.city || d.locality || d.principalSubdivision || null;
    } catch {
      return null;
    }
  }

  async function loadWeather(lat, lon, placeName) {
    const url =
      'https://api.open-meteo.com/v1/forecast?latitude=' + lat +
      '&longitude=' + lon +
      '&current=temperature_2m,relative_humidity_2m,apparent_temperature,is_day,weather_code,wind_speed_10m' +
      '&daily=weather_code,temperature_2m_max,temperature_2m_min' +
      '&forecast_days=4&timezone=auto';
    const res = await fetch(url);
    if (!res.ok) throw new Error('hava servisi');
    const d = await res.json();

    state.weather = d;
    state.placeName = placeName || (await reverseGeocode(lat, lon)) || 'Bulunduğun yer';
    renderWeather();
  }

  function renderWeather() {
    const w = state.weather;
    if (!w) return;
    $('weather-loc').textContent = state.placeName;

    const c = w.current;
    const body = $('weather-body');
    const days = ['Paz', 'Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt'];
    const dayLabels = w.daily.time.slice(1, 4).map((iso) => {
      const d = new Date(iso + 'T12:00:00');
      return days[d.getDay()];
    });

    body.innerHTML =
      '<div class="weather-main">' +
        '<div>' +
          '<p class="weather-temp" data-testid="text-temp">' + Math.round(c.temperature_2m) + '°C</p>' +
          '<p class="weather-desc"><span data-testid="text-condition">' + weatherText(c.weather_code) + '</span></p>' +
        '</div>' +
        iconSvg(weatherIcon(c.weather_code, c.is_day)).replace('class="weather-icon"', 'class="weather-icon weather-icon-lg"') +
      '</div>' +
      '<dl class="weather-grid">' +
        '<div class="w-stat"><dt>Hissedilen</dt><dd>' + Math.round(c.apparent_temperature) + '°C</dd></div>' +
        '<div class="w-stat"><dt>Nem</dt><dd>%' + c.relative_humidity_2m + '</dd></div>' +
        '<div class="w-stat"><dt>Rüzgar</dt><dd>' + Math.round(c.wind_speed_10m) + ' km/s</dd></div>' +
      '</dl>' +
      '<div class="weather-days">' +
        dayLabels
          .map(
            (label, i) =>
              '<div class="day"><span>' + label + '</span>' +
              iconSvg(weatherIcon(w.daily.weather_code[i + 1], 1)).replace('class="weather-icon"', 'class="weather-icon weather-icon-sm"') +
              '<span class="day-temp">' + Math.round(w.daily.temperature_2m_max[i + 1]) + '°</span></div>'
          )
          .join('') +
      '</div>';
  }

  function initWeather() {
    const start = (lat, lon, name) =>
      loadWeather(lat, lon, name).catch(() => {
        $('weather-body').innerHTML =
          '<p class="weather-error">Hava durumu şu anda alınamadı. Bağlantını kontrol edip sayfayı yenile.</p>';
      });

    if (!navigator.geolocation) {
      start(FALLBACK_LOC.lat, FALLBACK_LOC.lon, FALLBACK_LOC.name);
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => start(pos.coords.latitude, pos.coords.longitude, null),
      () => start(FALLBACK_LOC.lat, FALLBACK_LOC.lon, FALLBACK_LOC.name),
      { timeout: 8000, maximumAge: 10 * 60 * 1000 }
    );
  }

  /* ---------- Şarj ---------- */

  function renderBattery() {
    const b = state.battery;
    if (!b) return;
    const pct = Math.round(b.level * 100);
    const fill = $('battery-fill');
    fill.style.width = pct + '%';
    fill.classList.toggle('low', pct <= 20 && !b.charging);
    $('battery-pct').textContent = pct + '%';
    $('battery-state').textContent = b.charging ? 'Şarj oluyor' : 'Şarjda değil';
    $('battery-note').textContent = b.charging
      ? 'Cihazın şu anda şarj oluyor.'
      : pct <= 20
        ? 'Pil azaldı, yakında şarj etmen iyi olur.'
        : 'Günlük kullanım için yeterli görünüyor.';
  }

  function initBattery() {
    if (!navigator.getBattery) {
      $('battery-note').textContent = 'Tarayıcın pil bilgisini paylaşmayı desteklemiyor.';
      $('battery-state').textContent = 'Desteklenmiyor';
      return;
    }
    navigator.getBattery().then((b) => {
      state.battery = b;
      renderBattery();
      b.addEventListener('levelchange', renderBattery);
      b.addEventListener('chargingchange', renderBattery);
    });
  }

  /* ---------- Türkçe anlama (kural tabanlı) ---------- */

  const norm = (s) =>
    s
      .toLocaleLowerCase('tr')
      .replace(/[.!?,;:]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();

  // \b kelime sınırı Türkçe karakterleri tanımadığı için
  // özel sınır deseni kullanıyoruz
  const TR_BOUND = 'a-zçğıöşü0-9';

  function replaceWord(str, word, repl) {
    const re = new RegExp('(^|[^' + TR_BOUND + '])' + word + '(?=$|[^' + TR_BOUND + '])', 'g');
    return str.replace(re, (m, a) => a + repl);
  }

  const has = (text, ...words) => words.some((w) => text.includes(w));

  /* ---------- Matematik ---------- */

  const NUM_WORDS = {
    sıfır: 0, bir: 1, iki: 2, üç: 3, dört: 4, beş: 5, altı: 6, yedi: 7,
    sekiz: 8, dokuz: 9, on: 10, yirmi: 20, otuz: 30, kırk: 40, elli: 50,
    altmış: 60, yetmiş: 70, seksen: 80, doksan: 90, yüz: 100, bin: 1000,
    milyon: 1000000,
  };
  const TENS = { yirmi: 20, otuz: 30, kırk: 40, elli: 50, altmış: 60, yetmiş: 70, seksen: 80, doksan: 90 };
  const UNITS = { bir: 1, iki: 2, üç: 3, dört: 4, beş: 5, altı: 6, yedi: 7, sekiz: 8, dokuz: 9 };

  function tryMath(text) {
    let t = norm(text);
    if (!t) return null;

    // "yüzde" ayrı ele alınmalı (yüz=100 ile karışmasın)
    t = t.replace(/yüzde/g, ' PCT ');

    // Birleşik sayılar: "yirmi beş" → 25, "on iki" → 12
    for (const [tw, tv] of Object.entries(TENS)) {
      for (const [uw, uv] of Object.entries(UNITS)) {
        t = replaceWord(t, tw + ' ' + uw, String(tv + uv));
      }
    }
    t = replaceWord(t, 'on bir', '11').replace(/\bon iki\b/g, '12');

    // Sayı kelimesi + olası ek: "beşin" → 5 (ek atılır)
    for (const [w, n] of Object.entries(NUM_WORDS)) {
      const re = new RegExp('(^|[^' + TR_BOUND + '])(' + w + '[a-zçğıöşü]{0,3})(?=$|[^' + TR_BOUND + '])', 'g');
      t = t.replace(re, (m, a) => a + n);
    }

    // Yüzde: "250'nin yüzde 20'si" → (250*20/100) — boşluklu ekli
    // yazımları da destekler ("250 nin yüzde 20 si")
    t = t.replace(/(\d+)\s*['a-zçğıöşü]{0,4}\s*PCT\s*(\d+)\s*['a-zçğıöşü]{0,4}/g, '($1*$2/100)');

    // Kare / küp / karekök / üs — "4 ün karesi", "16 nın karekökü" gibi
    t = t.replace(/(\d+)\s*['a-zçğıöşü]{0,4}\s*karesi[a-zçğıöşü]{0,4}/g, '($1**2)');
    t = t.replace(/(\d+)\s*['a-zçğıöşü]{0,4}\s*küpü[a-zçğıöşü]{0,4}/g, '($1**3)');
    t = t.replace(/(\d+)\s*['a-zçğıöşü]{0,4}\s*karekök[a-zçğıöşü]{0,5}/g, 'Math.sqrt($1)');
    t = t.replace(/karekök[a-zçğıöşü]{0,5}\s*(\d+)/g, 'Math.sqrt($1)');
    t = t.replace(/(\d+)\s*['a-zçğıöşü]{0,4}\s*(?:üssü|üzeri)\s*(\d+)/g, '($1**$2)');
    t = t.replace(/\^/g, '**');

    // İşlem kelimeleri
    t = replaceWord(t, 'artı', ' + ').replace(/\btopla\b/g, '+');
    t = replaceWord(t, 'eksi', ' - ').replace(/\bçıkar\b/g, '-');
    t = replaceWord(t, 'kere', ' * ').replace(/\bçarpı\b/g, '*').replace(/\bçarp\b/g, '*');
    t = replaceWord(t, 'bölü', ' / ').replace(/\bböl\b/g, '/');

    // Soru kelimeleri temizle
    t = t.replace(/kaçtır|kaç eder|kaç|nedir|ne kadar|eder|kaçar|hesapla|yapar|olur|söyle/g, '').trim();

    // Örtük çarpma: "3 (100*20/100)" → "3*(100*20/100)"
    t = t.replace(/(\d)\s+\(/g, '$1*(')
         .replace(/(\d)\s+(Math\.sqrt)/g, '$1*$2')
         .replace(/\)\s+\(/g, ')*(');

    // Geçerlilik kontrolü: yalnızca sayı, operatör, Math.sqrt
    if (!/^[\d\s+\-*/().a-z]+$/i.test(t)) return null;
    if (!/[+\-*/]|Math\.sqrt|\*\*/.test(t)) return null;

    try {
      const val = Function('"use strict"; return (' + t + ')')();
      if (typeof val === 'number' && isFinite(val)) {
        const out = Math.round(val * 100) / 100;
        return 'Cevap ' + String(out).replace('.', ',') + '.';
      }
    } catch {
      /* geçersiz ifade */
    }
    return null;
  }

  /* ---------- Yapay zekâ (gelişmiş sorular) ---------- */

  // Yerelde boş, yayında proxy adresine dönüşür
  const AI_BASE = 'port/5000'.startsWith('__') ? '' : 'port/5000';

  function aiContext() {
    const ctx = {};
    if (state.placeName) ctx.place = state.placeName;
    if (state.weather) {
      const c = state.weather.current;
      ctx.weather =
        weatherText(c.weather_code).toLocaleLowerCase('tr') +
        ', ' + Math.round(c.temperature_2m) + ' derece';
    }
    if (state.battery) {
      ctx.battery =
        'yüzde ' + Math.round(state.battery.level * 100) +
        (state.battery.charging ? ', şarj oluyor' : '');
    }
    return ctx;
  }

  async function askLLM(question) {
    try {
      const res = await fetchWithTimeout(AI_BASE + '/api/ask', 30000, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question,
          context: aiContext(),
          history: history.slice(-6),
        }),
      });
      if (!res.ok) return null;
      const d = await res.json();
      if (d && typeof d.answer === 'string' && d.answer.trim()) {
        return d.answer.trim();
      }
    } catch {
      /* backend kapalı — web aramasına düş */
    }
    return null;
  }

  /* ---------- Web araması ---------- */

  function firstSentences(text, maxChars) {
    const parts = text.split(/(?<=[.!?])\s+/);
    let out = '';
    for (const p of parts) {
      if ((out + ' ' + p).trim().length > maxChars && out) break;
      out = (out + ' ' + p).trim();
      if (out.length >= maxChars) break;
    }
    return out || text.slice(0, maxChars);
  }

  async function fetchWithTimeout(url, ms, options) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), ms);
    try {
      return await fetch(url, Object.assign({}, options, { signal: ctrl.signal }));
    } finally {
      clearTimeout(timer);
    }
  }

  async function webSearch(query) {
    // 1) Vikipedi (Türkçe)
    try {
      const res = await fetchWithTimeout(
        'https://tr.wikipedia.org/w/api.php?action=query&format=json&origin=*&list=search&srsearch=' +
          encodeURIComponent(query) + '&srlimit=5',
        8000
      );
      const d = await res.json();
      const hits = (d.query && d.query.search) || [];
      if (hits.length) {
        // Sorguyla en çok örtüşen başlığı seç
        const q = query.toLocaleLowerCase('tr');
        const qWords = q.split(/\s+/);
        let best = null;
        let bestScore = -Infinity;
        hits.forEach((hit, i) => {
          const title = hit.title.toLocaleLowerCase('tr');
          let score = -i * 0.1;
          if (title === q) score += 10;
          if (q.startsWith(title) || title.startsWith(q)) score += 5;
          qWords.forEach((w) => {
            if (w.length > 2 && title.includes(w)) score += 1;
          });
          if (score > bestScore) {
            bestScore = score;
            best = hit;
          }
        });
        if (best && bestScore >= 2) {
          const res2 = await fetchWithTimeout(
            'https://tr.wikipedia.org/w/api.php?action=query&format=json&origin=*&prop=extracts&exintro&explaintext&pageids=' +
              best.pageid,
            8000
          );
          const d2 = await res2.json();
          const page = d2.query && d2.query.pages && d2.query.pages[best.pageid];
          const extract = ((page && page.extract) || '').split('\n').filter(Boolean)[0];
          if (extract && extract.length > 40) {
            return {
              text: extract,
              source: 'Vikipedi',
              url: 'https://tr.wikipedia.org/?curid=' + best.pageid,
            };
          }
        }
      }
    } catch {
      /* sıradaki kaynağa geç */
    }

    // 2) DuckDuckGo Anlık Yanıt
    try {
      const res = await fetchWithTimeout(
        'https://api.duckduckgo.com/?q=' + encodeURIComponent(query) +
          '&format=json&no_html=1&skip_disambig=1',
        8000
      );
      const d = await res.json();
      if (d.AbstractText && d.AbstractText.length > 40) {
        return { text: d.AbstractText, source: d.AbstractSource || 'DuckDuckGo', url: d.AbstractURL };
      }
      const rt = (d.RelatedTopics || []).find((x) => x.Text && x.FirstURL);
      if (rt) {
        return { text: rt.Text, source: 'DuckDuckGo', url: rt.FirstURL };
      }
    } catch {
      /* başarısız */
    }

    return null;
  }

  async function webAnswer(query) {
    let q = query.toLocaleLowerCase('tr');
    ['kaç tane', 'kaçtır', 'kimdir', 'nedir', 'ne kadar', 'midir', 'neresidir', 'nerededir', 'nerede', 'kaç', 'tane', 'kim', 'hangi'].forEach((w) => {
      q = replaceWord(q, w, ' ');
    });
    q = q.replace(/\s+/g, ' ').trim() || query;

    const result = await webSearch(q);
    if (!result) {
      return {
        text:
          'Web\'de arama yaptım ama güvenilir bir sonuç bulamadım. Soruyu biraz farklı sorabilir ya da internet bağlantını kontrol edebilirsin.',
      };
    }
    return {
      text: firstSentences(result.text, 420),
      source: result.source,
      url: result.url,
    };
  }

  /* ---------- Cevap üretimi ---------- */

  function weatherSentence() {
    if (!state.weather) return 'Hava durumu verisi henüz hazır değil, birkaç saniye sonra tekrar dener misin?';
    const c = state.weather.current;
    return (
      'Şu anda ' + state.placeName + "'da hava " +
      Math.round(c.temperature_2m) + ' derece, ' + weatherText(c.weather_code).toLocaleLowerCase('tr') +
      '. Hissedilen sıcaklık ' + Math.round(c.apparent_temperature) +
      ' derece, nem yüzde ' + c.relative_humidity_2m +
      ', rüzgar saatte ' + Math.round(c.wind_speed_10m) + ' kilometre.'
    );
  }

  function tomorrowSentence() {
    if (!state.weather) return 'Hava durumu verisi henüz hazır değil, birkaç saniye sonra tekrar dener misin?';
    const d = state.weather.daily;
    return (
      'Yarın ' + state.placeName + "'da en yüksek " + Math.round(d.temperature_2m_max[1]) +
      ' derece, en düşük ' + Math.round(d.temperature_2m_min[1]) + ' derece; hava ' +
      weatherText(d.weather_code[1]).toLocaleLowerCase('tr') + ' olması bekleniyor.'
    );
  }

  function batterySentence() {
    if (!state.battery) {
      return 'Üzgünüm, tarayıcın pil bilgisini paylaşmıyor. Pil durumunu cihazının durum çubuğundan kontrol edebilirsin.';
    }
    const pct = Math.round(state.battery.level * 100);
    if (state.battery.charging) {
      return 'Pilin şu anda yüzde ' + pct + ' ve şarj oluyor.';
    }
    return 'Pil seviyen yüzde ' + pct + '. ' +
      (pct <= 20 ? 'Az kalmış, şarj aletini takman iyi olur.' : 'Günlük kullanım için yeterli görünüyor.');
  }

  async function answer(raw) {
    const t = norm(raw);

    // Selamlama (yalnızca kısa selamlamalar için)
    if (has(t, 'merhaba', 'selam', 'günaydın', 'iyi günler', 'iyi akşamlar', 'naber', 'nasılsın') && t.length <= 50) {
      if (has(t, 'nasılsın', 'naber')) {
        return {
          text:
            'Çok iyiyim, sorduğun için sağ ol! Ben Nova, sesli asistanın. Hava durumu, şarjın, saat, tarih, matematik işlemleri ve web\'de arama konusunda yardım edebilirim.',
        };
      }
      return {
        text:
          'Merhaba! Ben Nova. Hava durumu, şarj seviyen, saat, tarih, matematik işlemleri, her türlü soru ve web\'de arama konusunda yardım edebilirim. Sormak istediğin bir şey var mı?',
      };
    }

    // Hava durumu
    if (has(t, 'hava', 'sıcaklık', 'yağmur', 'yağacak', 'kar var mı', 'nem', 'rüzgar', 'rüzgâr', 'derece')) {
      if (has(t, 'yarın')) return { text: tomorrowSentence() };
      if (has(t, 'yağmur', 'yağacak')) {
        if (!state.weather) return { text: weatherSentence() };
        const codes = [state.weather.current.weather_code, state.weather.daily.weather_code[1]];
        const rainy = codes.some((c) => [51,53,55,56,57,61,63,65,66,67,80,81,82,95,96,99].includes(c));
        return {
          text: rainy
            ? 'Evet, hava durumu verilerine göre yağış görünüyor. Şemsiyeni alman iyi olur. ' + weatherSentence()
            : 'Şu anki verilere göre yağış beklenmiyor. ' + weatherSentence(),
        };
      }
      return { text: weatherSentence() };
    }

    // Şarj / pil
    if (has(t, 'şarj', 'pil', 'batarya', 'battery')) return { text: batterySentence() };

    // Saat
    if (has(t, 'saat')) {
      const now = new Date();
      return {
        text: 'Şu anda saat ' + now.getHours() + '.' + String(now.getMinutes()).padStart(2, '0') + '.',
      };
    }

    // Tarih / gün
    if (has(t, 'bugün ayın kaçı', 'tarih', 'günlerden ne', 'kaçındayız', 'ayın kaçı')) {
      return {
        text:
          'Bugün ' + new Date().toLocaleDateString('tr-TR', {
            weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
          }) + '.',
      };
    }

    // Kimlik
    if (has(t, 'kimsin', 'adın ne', 'sen kimsin', 'ne işe yararsın', 'neler yapabilirsin', 'yardım')) {
      return {
        text:
          'Ben Nova, senin sesli asistanın. Bulunduğun yerin hava durumunu ve cihazının şarj seviyesini söyleyebilirim; saat ve tarih sorabilir, matematik işlemleri yaptırabilir ve bilmediğim konularda web\'de arama yapabilirim. Mikrofona dokunup konuşman yeterli.',
      };
    }

    // Teşekkür
    if (has(t, 'teşekkür', 'sağ ol', 'sagol', 'eyvallah')) {
      return { text: 'Rica ederim, her zaman!' };
    }

    // Şaka
    if (has(t, 'şaka', 'komik', 'güldür')) {
      const jokes = [
        'Pilim bitmek üzere demiş telefon, şarjım güçlü demiş elektrik. Sonunda güçlü bir birliktelik olmuşlar.',
        'Yağmur yağınca bulut ne demiş biliyor musun? "Ben gitmek zorundayım, yerlere düşeceğim."',
        'Rüzgar sormuş Nova\'ya: neden hep koşuyorsun? Nova cevap vermiş: yerimde duramam, web\'de arayacak çok şey var!',
      ];
      return { text: jokes[Math.floor(Math.random() * jokes.length)] };
    }

    // Matematik
    const math = tryMath(raw);
    if (math !== null) return { text: math };

    // Hızlı bilgiler (web aramasının zayıf kaldığı sık sorular)
    if (has(t, 'başkent')) {
      const capitals = {
        'türkiye': "Türkiye'nin başkenti Ankara'dır.",
        'amerika': "ABD'nin başkenti Washington'dur.",
        'abd': "ABD'nin başkenti Washington'dur.",
        'almanya': "Almanya'nın başkenti Berlin'dir.",
        'fransa': "Fransa'nın başkenti Paris'tir.",
        'ingiltere': "İngiltere'nin başkenti Londra'dır.",
        'italya': "İtalya'nın başkenti Roma'dır.",
        'ispanya': "İspanya'nın başkenti Madrid'dir.",
        'rusya': "Rusya'nın başkenti Moskova'dır.",
        'japonya': "Japonya'nın başkenti Tokyo'dur.",
        'çin': "Çin'in başkenti Pekin'dir.",
        'yunanistan': "Yunanistan'ın başkenti Atina'dır.",
      };
      for (const [c, s] of Object.entries(capitals)) {
        if (t.includes(c)) return { text: s };
      }
    }
    if (has(t, 'türkiye') && has(t, 'ilden', 'kaç il', 'kaç tane il', 'il sayısı')) {
      return { text: 'Türkiye 81 ilden oluşur.' };
    }

    // Uygulama açma / kapama
    const wantsClose = t.includes('kapat');
    const wantsOpen =
      /(?:^|[^a-zçğıöşü0-9])aç(?:$|[^a-zçğıöşü0-9])/.test(t) ||
      t.includes('açar mısın') ||
      t.includes('açarmısın') ||
      t.includes('aç bakalım');

    if (wantsClose) {
      const ok = closeLastApp();
      return {
        text: ok
          ? 'Son açtığım uygulamayı kapattım.'
          : 'Benim açtığım açık bir uygulama yok. Tarayıcının sekmelerinden kapatabilirsin.',
      };
    }

    if (wantsOpen) {
      const app = findApp(t);
      if (app) {
        const ok = openApp(app);
        return ok
          ? { text: app.name + ' yeni sekmede açılıyor.' }
          : {
              text: 'Tarayıcı açıyı engelledi, şu bağlantıya dokunarak açabilirsin:',
              url: app.url,
              linkLabel: app.name + ' aç',
            };
      }
      // Bilinen uygulama yoksa adres varsa onu aç
      const u = raw.match(URL_RE);
      if (u) {
        const url = /^https?:\/\//.test(u[0]) ? u[0] : 'https://' + u[0];
        const ok = openApp({ url });
        return ok
          ? { text: u[0] + ' yeni sekmede açılıyor.' }
          : { text: 'Tarayıcı açıyı engelledi, şu bağlantıya dokun:', url, linkLabel: 'Aç' };
      }
    }

    // Site kontrolü: soruda adres varsa
    const urlMatch = raw.match(URL_RE);
    if (urlMatch && has(t, 'kontrol', 'çalışıyor mu', 'çalişiyor mu', 'açık mı', 'durum', 'bakar mısın', 'kontrol et')) {
      setStatus('Siteyi kontrol ediyorum…');
      const r = await siteCheck(urlMatch[0]);
      if (r) {
        let text = siteCheckSentence(r);
        if (r.analysis) text += ' Özet: ' + firstSentences(mdClean(r.analysis), 260);
        return { text };
      }
    }

    // Yapay zekâ: gelişmiş sorular
    setStatus('Düşünüyorum…');
    const ai = await askLLM(raw);
    if (ai) return { text: ai };

    // Web araması (açık istek veya bilinmeyen konu)
    let query = raw;
    if (has(t, 'webde', 'web\'de', 'internette', 'araştır', 'araştırır mısın')) {
      query = raw
        .replace(/web'?de|internette|araştır|araştırır mısın/gi, '')
        .replace(/\s+/g, ' ')
        .trim();
    }
    if (query) {
      setStatus('Web\'de araştırıyorum…');
      const result = await webAnswer(query);
      return {
        text: result.text,
        source: result.source,
        url: result.url,
      };
    }

    return {
      text:
        'Bunu şu anda yanıtlayamadım. Hava durumu, şarj seviyen, saat, tarih, matematik işlemleri ve genel bilgi sorularında yardım edebilirim. Soruyu biraz farklı sorabilir misin?',
    };
  }

  async function handleQuestion(text) {
    const q = text.trim();
    if (!q) return;
    addMsg('user', q);
    setStatus('Düşünüyorum…');
    let reply;
    try {
      reply = await answer(q);
    } catch {
      reply = { text: 'Bir sorun oluştu, tekrar dener misin?' };
    }
    speak(reply.text);
    if (reply.url) {
      // Konuşma balonuna kaynak bağlantısı ekle
      const last = conversationEl.lastElementChild;
      if (last) {
        last.append(document.createElement('br'));
        const a = document.createElement('a');
        a.href = reply.url;
        a.target = '_blank';
        a.rel = 'noopener';
        a.textContent = reply.linkLabel || 'Kaynak: ' + (reply.source || reply.url);
        last.append(a);
      }
    }
    setStatus('Konuşmak için mikrofona dokun');
  }

  /* ---------- Sesle tanıma ---------- */

  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  let recognition = null;
  let listening = false;

  if (!SR) {
    setStatus('Tarayıcın sesle tanımayı desteklemiyor — yazarak sorabilirsin');
  }

  if (SR) {
    recognition = new SR();
    recognition.lang = 'tr-TR';
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;
    recognition.continuous = false;

    recognition.onresult = (e) => {
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) {
          listening = false;
          micBtn.classList.remove('listening');
          handleQuestion(r[0].transcript);
          return;
        }
        interim += r[0].transcript;
      }
      setStatus('Dinliyorum…', interim);
    };

    recognition.onerror = (e) => {
      listening = false;
      micBtn.classList.remove('listening');
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
        setStatus('Mikrofon izni verilmedi. Tarayıcı izinlerinden mikrofona izin verebilirsin');
        addMsg('bot', 'Mikrofon izni verilmediği için seni duyamıyorum. İzin verdikten sonra tekrar dener misin?');
      } else if (e.error === 'no-speech') {
        setStatus('Seni duyamadım, tekrar dener misin?');
      } else {
        setStatus('Ses tanıma hatası: ' + e.error);
      }
    };

    recognition.onend = () => {
      listening = false;
      micBtn.classList.remove('listening');
      if (statusEl.textContent.startsWith('Dinliyorum')) {
        setStatus('Konuşmak için mikrofona dokun');
      }
    };
  }

  function toggleMic() {
    if (!recognition) {
      setStatus('Tarayıcın sesle tanımayı desteklemiyor — yazarak sorabilirsin');
      return;
    }
    if (listening) {
      recognition.stop();
      return;
    }
    if (synth) synth.cancel();
    try {
      recognition.start();
      listening = true;
      micBtn.classList.add('listening');
      setStatus('Dinliyorum…');
    } catch {
      /* zaten açık */
    }
  }

  micBtn.addEventListener('click', toggleMic);

  /* ---------- Uygulama kontrolü ---------- */

  const checkResultEl = $('check-result');

  function setCheckResult(html) {
    checkResultEl.innerHTML = html;
    checkResultEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // Ham Markdown işaretlerini temizle
  function mdClean(s) {
    return String(s || '')
      .replace(/```[a-z]*\n?/gi, '')
      .replace(/^#{1,4}\s*/gm, '')
      .replace(/\*\*([^*]+)\*\*/g, '$1')
      .replace(/\*([^*]+)\*/g, '$1')
      .replace(/`([^`]+)`/g, '$1')
      .trim();
  }

  // Sohbetten URL sorusu: "ornek.com çalışıyor mu?"
  const URL_RE = /(https?:\/\/[^\s]+)|((?:[a-z0-9-]+\.)+(?:com|net|org|io|dev|tr|app|ai|co|me|xyz|tech|dev)(?:\/[^\s]*)?)/i;

  async function siteCheck(url) {
    try {
      const res = await fetchWithTimeout(AI_BASE + '/api/site-check', 60000, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
      });
      if (!res.ok) return null;
      return await res.json();
    } catch {
      return null;
    }
  }

  function siteCheckSentence(r) {
    if (!r) return 'Site kontrolü şu anda yapılamadı, biraz sonra tekrar dener misin?';
    if (r.error) return 'Kontrol edemedim: ' + r.error;
    if (!r.up) {
      return (
        (r.url || 'Site') + ' şu anda erişilemiyor. ' +
        (r.status ? 'HTTP durum kodu ' + r.status + '.' : 'Sunucuya bağlantı kurulamadı.')
      );
    }
    let s =
      (r.url || 'Site') + ' çalışıyor. HTTP ' + r.status +
      ', yanıt süresi ' + r.responseTime + ' milisaniye' +
      (r.size ? ', sayfa boyutu ' + Math.round(r.size / 1024) + ' kilobayt' : '') + '.';
    if (r.title) s += ' Sayfa başlığı: ' + r.title + '.';
    return s;
  }

  function renderSiteResult(r) {
    if (!r) {
      setCheckResult('<p class="check-err">Kontrol yapılamadı, tekrar dene.</p>');
      return;
    }
    let html = '';
    if (r.error) {
      html += '<p class="check-err">' + esc(r.error) + '</p>';
    } else if (!r.up) {
      html += '<p class="check-err">' + esc(r.url) + ' erişilemiyor' +
        (r.status ? ' (HTTP ' + esc(r.status) + ')' : '') + '</p>';
    } else {
      html +=
        '<div class="check-ok"><span class="dot dot-ok" aria-hidden="true"></span>' +
        '<strong>' + esc(r.url) + '</strong> çalışıyor</div>' +
        '<dl class="check-facts">' +
        '<div><dt>Durum</dt><dd>HTTP ' + esc(r.status) + '</dd></div>' +
        '<div><dt>Yanıt süresi</dt><dd>' + esc(r.responseTime) + ' ms</dd></div>' +
        (r.size ? '<div><dt>Boyut</dt><dd>' + Math.round(r.size / 1024) + ' KB</dd></div>' : '') +
        (r.title ? '<div><dt>Başlık</dt><dd>' + esc(r.title) + '</dd></div>' : '') +
        '</dl>';
      if (r.analysis) {
        html += '<div class="check-analysis"><h3>Nova analizi</h3><p>' + esc(mdClean(r.analysis)) + '</p></div>';
      }
    }
    setCheckResult(html);
  }

  async function codeReview(code, filename) {
    try {
      const res = await fetchWithTimeout(AI_BASE + '/api/review', 90000, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code, filename }),
      });
      if (!res.ok) return null;
      const d = await res.json();
      return (d && d.review) || null;
    } catch {
      return null;
    }
  }

  function renderReviewResult(review, filename) {
    if (!review) {
      setCheckResult('<p class="check-err">İnceleme yapılamadı, tekrar dene.</p>');
      return;
    }
    setCheckResult(
      '<div class="check-ok"><span class="dot dot-ok" aria-hidden="true"></span>' +
      '<strong>' + esc(filename || 'Kod') + '</strong> incelemesi hazır</div>' +
      '<div class="check-analysis"><h3>Nova incelemesi</h3><p>' + esc(mdClean(review)) + '</p></div>'
    );
  }

  // Site kontrol formu
  $('site-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const url = $('site-url').value.trim();
    if (!url) return;
    setCheckResult('<p class="check-loading">Kontrol ediliyor…</p>');
    const r = await siteCheck(url);
    renderSiteResult(r);
    speak(siteCheckSentence(r));
  });

  // Dosya seçme
  $('file-input').addEventListener('change', (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    if (file.size > 300000) {
      setCheckResult('<p class="check-err">Dosya çok büyük (en fazla 300 KB).</p>');
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      $('code-input').value = String(reader.result || '');
      if (!$('code-filename').value) $('code-filename').value = file.name;
    };
    reader.readAsText(file);
  });

  // Kod inceleme formu
  $('code-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const code = $('code-input').value.trim();
    const filename = $('code-filename').value.trim();
    if (!code) {
      setCheckResult('<p class="check-err">Önce kod yapıştır ya da dosya seç.</p>');
      return;
    }
    setCheckResult('<p class="check-loading">Nova kodunu inceliyor…</p>');
    const review = await codeReview(code, filename);
    renderReviewResult(review, filename);
    speak(
      review
        ? 'İncelemen hazır. ' + (filename ? filename + ' dosyasını' : 'kodunu') + ' inceledim, sonuçları uygulama kontrolü bölümünde görebilirsin.'
        : 'İnceleme şu anda yapılamadı, tekrar dener misin?'
    );
  });

  /* ---------- Uygulama açma / kapama ---------- */

  const APPS = [
    { key: 'youtube', name: 'YouTube', url: 'https://www.youtube.com', aliases: ['youtube'] },
    { key: 'whatsapp', name: 'WhatsApp', url: 'https://web.whatsapp.com', aliases: ['whatsapp'] },
    { key: 'instagram', name: 'Instagram', url: 'https://www.instagram.com', aliases: ['instagram'] },
    { key: 'gmail', name: 'Gmail', url: 'https://mail.google.com', aliases: ['gmail', 'mail', 'eposta', 'e-posta'] },
    { key: 'github', name: 'GitHub', url: 'https://github.com', aliases: ['github'] },
    { key: 'spotify', name: 'Spotify', url: 'https://open.spotify.com', aliases: ['spotify'] },
    { key: 'netflix', name: 'Netflix', url: 'https://www.netflix.com', aliases: ['netflix'] },
    { key: 'google', name: 'Google', url: 'https://www.google.com', aliases: ['google'] },
    { key: 'haritalar', name: 'Google Haritalar', url: 'https://maps.google.com', aliases: ['harita', 'haritalar', 'maps'] },
    { key: 'vikipedi', name: 'Vikipedi', url: 'https://tr.wikipedia.org', aliases: ['vikipedi', 'wikipedia'] },
    { key: 'chatgpt', name: 'ChatGPT', url: 'https://chatgpt.com', aliases: ['chatgpt', 'chat gpt'] },
  ];

  const openedWindows = [];

  function openApp(app) {
    try {
      const w = window.open(app.url, '_blank');
      if (w) {
        openedWindows.push(w);
        if (openedWindows.length > 8) openedWindows.shift();
        return true;
      }
    } catch {
      /* popup engellendi */
    }
    return false;
  }

  function closeLastApp() {
    while (openedWindows.length) {
      const w = openedWindows.pop();
      try {
        if (w) {
          // Not: çapraz origin pencerelerde w.closed güvenilir değil,
          // script ile açılan pencereler w.close() ile kapanabilir.
          w.close();
          return true;
        }
      } catch {
        /* kapatılamadı, sıradakini dene */
      }
    }
    return false;
  }

  function findApp(text) {
    return APPS.find((a) => a.aliases.some((al) => text.includes(al))) || null;
  }

  // Uygulama butonları
  document.querySelectorAll('.app-btn[data-app]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const app = APPS.find((a) => a.key === btn.dataset.app);
      if (!app) return;
      const ok = openApp(app);
      addMsg('user', app.name + ' aç');
      if (ok) {
        speak(app.name + ' yeni sekmede açılıyor.');
      } else {
        addMsg('bot', 'Tarayıcı açıyı engelledi. Şu bağlantıya dokunarak açabilirsin:');
        const last = conversationEl.lastElementChild;
        const a = document.createElement('a');
        a.href = app.url;
        a.target = '_blank';
        a.rel = 'noopener';
        a.textContent = app.name;
        last.append(document.createElement('br'), a);
      }
    });
  });

  $('close-app-btn').addEventListener('click', () => {
    addMsg('user', 'Son açılanı kapat');
    const ok = closeLastApp();
    speak(
      ok
        ? 'Son açtığım uygulamayı kapattım.'
        : 'Benim açtığım açık bir uygulama yok. Tarayıcının sekmelerinden kapatabilirsin.'
    );
  });

  /* ---------- Hızlı sorular ve form ---------- */

  document.querySelectorAll('.chip').forEach((chip) => {
    chip.addEventListener('click', () => handleQuestion(chip.dataset.q));
  });

  $('text-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const input = $('text-input');
    const val = input.value;
    input.value = '';
    handleQuestion(val);
  });

  /* ---------- Başlangıç ---------- */

  initWeather();
  initBattery();
  setInterval(initWeather, 10 * 60 * 1000);
})();
