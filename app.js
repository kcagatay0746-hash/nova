/* ============================================================
   Nova v2 — Türkçe, araç kullanabilen yapay zekâ asistanı (istemci)

   Katmanlar:
     1. Yardımcılar         : DOM, kaçış, markdown-lite
     2. Tema                : açık/koyu mod
     3. Konuşma (TTS)       : cümle bazlı akış kuyruğu
     4. Durum               : yerel hava/pil/sağlık bilgisi
     5. Yerel hızlı yanıtlar: hava, pil, saat, tarih, uygulamalar
     6. Ajan istemcisi      : /api/chat/stream (SSE) + /api/ask yedeği
     7. Sohbet arayüzü      : baloncuklar, araç etiketleri, kaynaklar
     8. Bellek paneli       : /api/memory CRUD
     9. Site kontrolü/kod   : /api/site-check, /api/review
    10. Uygulamalar, sesle tanıma, başlangıç
   ============================================================ */

(function () {
  'use strict';

  /* ---------- 1. Yardımcılar ---------- */

  const $ = (id) => document.getElementById(id);
  const API_BASE = window.NOVA_API_BASE || '';

  const statusEl = $('assistant-status');
  const conversationEl = $('conversation');
  const micBtn = $('mic-btn');

  function setStatus(text, interim) {
    statusEl.textContent = text;
    if (interim) {
      const span = document.createElement('span');
      span.className = 'interim';
      span.textContent = ' ' + interim;
      statusEl.append(span);
    }
  }

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // Modelin ürettiği hafif markdown'ı güvenli HTML'e çevirir.
  // Önce kaçış yapılır, sonra yalnızca bilinen kalıplar biçimlendirilir.
  function renderMarkdown(raw) {
    let text = esc(String(raw || ''));
    text = text.replace(/```[a-zA-Z]*\n?/g, '');
    text = text.replace(/^#{1,4}\s*/gm, '');
    text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    text = text.replace(/`([^`]+)`/g, '<code>$1</code>');
    const lines = text.split(/\n/);
    let html = '';
    let inList = false;
    for (const line of lines) {
      const item = line.match(/^\s*[-•]\s+(.*)$/);
      if (item) {
        if (!inList) {
          html += '<ul>';
          inList = true;
        }
        html += '<li>' + item[1] + '</li>';
      } else {
        if (inList) {
          html += '</ul>';
          inList = false;
        }
        if (line.trim()) html += '<p>' + line + '</p>';
      }
    }
    if (inList) html += '</ul>';
    // Bağlantıları tıklanabilir yap
    html = html.replace(
      /(https?:\/\/[^\s<]+)/g,
      '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>'
    );
    return html || '<p></p>';
  }

  function sessionId() {
    let id = localStorage.getItem('nova.session');
    if (!id) {
      id = 'web-' + Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4);
      localStorage.setItem('nova.session', id);
    }
    return id;
  }

  /* ---------- 2. Tema ---------- */

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

  /* ---------- 3. Konuşma (TTS) ---------- */

  const synth = window.speechSynthesis;
  const voiceToggle = $('voice-toggle');
  const stopSpeakBtn = $('stop-speak');
  let ttsEnabled = localStorage.getItem('nova.tts') !== 'off';
  let trVoice = null;
  let speakQueue = [];
  let speakBuffer = '';
  let speaking = false;

  function pickVoice() {
    if (!synth) return;
    const voices = synth.getVoices();
    trVoice =
      voices.find((v) => v.lang === 'tr-TR') ||
      voices.find((v) => v.lang && v.lang.toLowerCase().startsWith('tr')) ||
      null;
  }

  function updateVoiceButton() {
    voiceToggle.setAttribute('aria-pressed', ttsEnabled ? 'true' : 'false');
    voiceToggle.textContent = ttsEnabled ? 'Sesli yanıt: açık' : 'Sesli yanıt: kapalı';
  }

  function resetSpeech() {
    speakQueue = [];
    speakBuffer = '';
    if (synth) synth.cancel();
    speaking = false;
    stopSpeakBtn.hidden = true;
  }

  function speakChunk(text) {
    if (!ttsEnabled || !synth || !text.trim()) return;
    const utterance = new SpeechSynthesisUtterance(text.trim());
    utterance.lang = 'tr-TR';
    if (trVoice) utterance.voice = trVoice;
    utterance.rate = 1;
    utterance.onstart = () => {
      speaking = true;
      stopSpeakBtn.hidden = false;
    };
    utterance.onend = () => {
      speaking = false;
      if (!speakQueue.length) stopSpeakBtn.hidden = true;
    };
    synth.speak(utterance);
  }

  function queueSpeech(text) {
    if (!ttsEnabled) return;
    speakQueue.push(text);
    while (speakQueue.length) speakChunk(speakQueue.shift());
  }

  // Akış sırasında gelen metni cümle sınırlarında seslendirir.
  function feedSpeech(delta) {
    if (!ttsEnabled || !delta) return;
    speakBuffer += delta;
    const match = speakBuffer.match(/^([\s\S]*?[.!?…])\s+/);
    if (match) {
      speakBuffer = speakBuffer.slice(match[0].length);
      queueSpeech(match[1]);
    } else if (speakBuffer.length > 220) {
      queueSpeech(speakBuffer);
      speakBuffer = '';
    }
  }

  function flushSpeech() {
    if (speakBuffer.trim()) queueSpeech(speakBuffer);
    speakBuffer = '';
  }

  if (synth) {
    pickVoice();
    synth.addEventListener('voiceschanged', pickVoice);
  }

  voiceToggle.addEventListener('click', () => {
    ttsEnabled = !ttsEnabled;
    localStorage.setItem('nova.tts', ttsEnabled ? 'on' : 'off');
    if (!ttsEnabled) resetSpeech();
    updateVoiceButton();
  });

  stopSpeakBtn.addEventListener('click', () => {
    resetSpeech();
    setStatus('Konuşmayı durdurdum');
  });

  updateVoiceButton();
  if (!synth) {
    voiceToggle.disabled = true;
    voiceToggle.textContent = 'Bu tarayıcı seslendirmeyi desteklemiyor';
  }

  /* ---------- 4. Durum ---------- */

  const state = { weather: null, placeName: null, battery: null, health: null };
  const history = [];

  function pushHistory(who, text) {
    history.push({ who, text });
    if (history.length > 12) history.splice(0, history.length - 12);
  }

  /* ---------- 5. Hava durumu ---------- */

  const FALLBACK_LOC = { lat: 36.8969, lon: 30.7133, name: 'Antalya' };

  const WMO = {
    0: ['Açık ve güneşli', 'sun'], 1: ['Az bulutlu', 'cloud-sun'], 2: ['Parçalı bulutlu', 'cloud-sun'],
    3: ['Kapalı', 'cloud'], 45: ['Sisli', 'fog'], 48: ['Kırağılı sis', 'fog'],
    51: ['Hafif çisenti', 'rain'], 53: ['Çisenti', 'rain'], 55: ['Yoğun çisenti', 'rain'],
    56: ['Dondurucu çisenti', 'rain'], 57: ['Yoğun dondurucu çisenti', 'rain'],
    61: ['Hafif yağmur', 'rain'], 63: ['Yağmur', 'rain'], 65: ['Şiddetli yağmur', 'rain'],
    66: ['Dondurucu yağmur', 'rain'], 67: ['Şiddetli dondurucu yağmur', 'rain'],
    71: ['Hafif kar', 'snow'], 73: ['Kar', 'snow'], 75: ['Yoğun kar', 'snow'], 77: ['Kar taneleri', 'snow'],
    80: ['Hafif sağanak', 'rain'], 81: ['Sağanak', 'rain'], 82: ['Şiddetli sağanak', 'rain'],
    85: ['Kar sağanağı', 'snow'], 86: ['Yoğun kar sağanağı', 'snow'],
    95: ['Gök gürültülü fırtına', 'storm'], 96: ['Dolulu fırtına', 'storm'], 99: ['Şiddetli dolulu fırtına', 'storm'],
  };

  function weatherText(code) {
    return (WMO[code] || ['Bilinmeyen', 'cloud'])[0];
  }

  function weatherIcon(code, isDay) {
    const kind = (WMO[code] || ['', 'cloud'])[1];
    const sun = '<circle cx="12" cy="12" r="4.2" fill="currentColor"/>';
    const rays = '<g stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.2 5.2l1.4 1.4M17.4 17.4l1.4 1.4M18.8 5.2l-1.4 1.4M6.6 17.4l-1.4 1.4"/></g>';
    const cloud = '<path d="M6.5 17.5h11a3.5 3.5 0 0 0 .3-7 5 5 0 0 0-9.6-1.2A4 4 0 0 0 6.5 17.5z" fill="currentColor"/>';
    if (kind === 'sun') return '<svg class="weather-icon" viewBox="0 0 24 24" aria-hidden="true">' + sun + rays + '</svg>';
    if (kind === 'cloud-sun') return '<svg class="weather-icon" viewBox="0 0 24 24" aria-hidden="true"><g opacity="0.85">' + sun + '</g><path d="M7 18.5h10.2a3.2 3.2 0 0 0 .2-6.4 4.6 4.6 0 0 0-8.8-1A3.7 3.7 0 0 0 7 18.5z" fill="currentColor"/></svg>';
    if (kind === 'rain') return '<svg class="weather-icon" viewBox="0 0 24 24" aria-hidden="true">' + cloud + '<g stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M8 19.5l-1 2M12 19.5l-1 2M16 19.5l-1 2"/></g></svg>';
    if (kind === 'snow') return '<svg class="weather-icon" viewBox="0 0 24 24" aria-hidden="true">' + cloud + '<g fill="currentColor"><circle cx="8" cy="20" r="1.1"/><circle cx="12" cy="21" r="1.1"/><circle cx="16" cy="20" r="1.1"/></g></svg>';
    if (kind === 'storm') return '<svg class="weather-icon" viewBox="0 0 24 24" aria-hidden="true">' + cloud + '<path d="M12.5 18.5l-2 3h2.5l-1.2 2.2" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';
    if (kind === 'fog') return '<svg class="weather-icon" viewBox="0 0 24 24" aria-hidden="true"><g stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4 9h16M6 13h12M4 17h16"/></g></svg>';
    return '<svg class="weather-icon" viewBox="0 0 24 24" aria-hidden="true">' + cloud + '</svg>';
  }

  async function reverseGeocode(lat, lon) {
    try {
      const res = await fetch(
        'https://api.bigdatacloud.net/data/reverse-geocode-client?latitude=' + lat +
          '&longitude=' + lon + '&localityLanguage=tr'
      );
      const data = await res.json();
      return data.city || data.locality || data.principalSubdivision || null;
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
    const data = await res.json();
    state.weather = data;
    state.placeName = placeName || (await reverseGeocode(lat, lon)) || 'Bulunduğun yer';
    renderWeather();
  }

  function renderWeather() {
    const weather = state.weather;
    if (!weather) return;
    $('weather-loc').textContent = state.placeName;
    const current = weather.current;
    const days = ['Paz', 'Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt'];
    const dayLabels = weather.daily.time.slice(1, 4).map((iso) => days[new Date(iso + 'T12:00:00').getDay()]);

    $('weather-body').innerHTML =
      '<div class="weather-main"><div>' +
        '<p class="weather-temp" data-testid="text-temp">' + Math.round(current.temperature_2m) + '°C</p>' +
        '<p class="weather-desc"><span data-testid="text-condition">' + weatherText(current.weather_code) + '</span></p>' +
      '</div>' +
      weatherIcon(current.weather_code, current.is_day).replace('class="weather-icon"', 'class="weather-icon weather-icon-lg"') +
      '</div>' +
      '<dl class="weather-grid">' +
        '<div class="w-stat"><dt>Hissedilen</dt><dd>' + Math.round(current.apparent_temperature) + '°C</dd></div>' +
        '<div class="w-stat"><dt>Nem</dt><dd>%' + current.relative_humidity_2m + '</dd></div>' +
        '<div class="w-stat"><dt>Rüzgar</dt><dd>' + Math.round(current.wind_speed_10m) + ' km/s</dd></div>' +
      '</dl>' +
      '<div class="weather-days">' +
        dayLabels.map((label, index) =>
          '<div class="day"><span>' + label + '</span>' +
          weatherIcon(weather.daily.weather_code[index + 1], 1).replace('class="weather-icon"', 'class="weather-icon weather-icon-sm"') +
          '<span class="day-temp">' + Math.round(weather.daily.temperature_2m_max[index + 1]) + '°</span></div>'
        ).join('') +
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

  /* ---------- 6. Pil ---------- */

  function renderBattery() {
    const battery = state.battery;
    if (!battery) return;
    const pct = Math.round(battery.level * 100);
    const fill = $('battery-fill');
    fill.style.width = pct + '%';
    fill.classList.toggle('low', pct <= 20 && !battery.charging);
    $('battery-pct').textContent = pct + '%';
    $('battery-state').textContent = battery.charging ? 'Şarj oluyor' : 'Şarjda değil';
    $('battery-note').textContent =
      pct <= 20 && !battery.charging
        ? 'Pil azalıyor, şarj aletini takman iyi olur.'
        : battery.charging
          ? 'Cihaz prize bağlı.'
          : 'Pil durumu normal görünüyor.';
  }

  async function initBattery() {
    if (!navigator.getBattery) {
      $('battery-state').textContent = 'Desteklenmiyor';
      $('battery-note').textContent = 'Bu tarayıcı pil bilgisini paylaşmıyor.';
      return;
    }
    try {
      const battery = await navigator.getBattery();
      state.battery = { level: battery.level, charging: battery.charging };
      renderBattery();
      const sync = () => {
        state.battery = { level: battery.level, charging: battery.charging };
        renderBattery();
      };
      battery.addEventListener('levelchange', sync);
      battery.addEventListener('chargingchange', sync);
    } catch {
      $('battery-note').textContent = 'Pil bilgisi okunamadı.';
    }
  }

  /* ---------- 7. Yerel hızlı yanıtlar ---------- */

  const norm = (text) =>
    String(text || '')
      .toLocaleLowerCase('tr')
      .replace(/[.!?,;:]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();

  const has = (text, ...words) => words.some((word) => text.includes(word));

  const APPS = [
    { key: 'youtube', name: 'YouTube', url: 'https://www.youtube.com', aliases: ['youtube'] },
    { key: 'whatsapp', name: 'WhatsApp', url: 'https://web.whatsapp.com', aliases: ['whatsapp', 'whats app'] },
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
      const win = window.open(app.url, '_blank');
      if (win) {
        openedWindows.push(win);
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
      const win = openedWindows.pop();
      try {
        if (win) {
          win.close();
          return true;
        }
      } catch {
        /* sıradakini dene */
      }
    }
    return false;
  }

  function findApp(text) {
    return APPS.find((app) => app.aliases.some((alias) => text.includes(alias))) || null;
  }

  function weatherSentence() {
    if (!state.weather) return null;
    const current = state.weather.current;
    return (
      'Şu anda ' + state.placeName + "'da hava " + Math.round(current.temperature_2m) +
      ' derece, ' + weatherText(current.weather_code).toLocaleLowerCase('tr') +
      '. Hissedilen ' + Math.round(current.apparent_temperature) + ' derece, nem yüzde ' +
      current.relative_humidity_2m + ', rüzgar saatte ' + Math.round(current.wind_speed_10m) + ' kilometre.'
    );
  }

  function tomorrowSentence() {
    if (!state.weather) return null;
    const daily = state.weather.daily;
    return (
      'Yarın ' + state.placeName + ' için en yüksek ' + Math.round(daily.temperature_2m_max[1]) +
      ' derece, en düşük ' + Math.round(daily.temperature_2m_min[1]) + ' derece; hava ' +
      weatherText(daily.weather_code[1]).toLocaleLowerCase('tr') + ' bekleniyor.'
    );
  }

  function batterySentence() {
    if (!state.battery) return null;
    const pct = Math.round(state.battery.level * 100);
    if (state.battery.charging) return 'Pilin yüzde ' + pct + ' seviyesinde ve şarj oluyor.';
    return 'Pil seviyen yüzde ' + pct + '.' +
      (pct <= 20 ? ' Az kalmış, şarj aletini takman iyi olur.' : ' Günlük kullanım için yeterli görünüyor.');
  }

  // Yerel olarak (ağ beklemeden) yanıtlanabilen niyetler.
  function localAnswer(raw) {
    const t = norm(raw);

    if (t.length <= 50 && has(t, 'merhaba', 'selam', 'günaydın', 'iyi akşamlar', 'naber', 'nasılsın')) {
      if (has(t, 'nasılsın', 'naber')) {
        return { text: 'Çok iyiyim, sorduğun için sağ ol! Hava, saat, hesap, web araması, site kontrolü ve hafıza konularında yardımcı olabilirim.' };
      }
      return { text: 'Merhaba! Ben Nova. Hava durumundan hesaplamaya, web aramasından kod incelemesine kadar yardımcı olabilirim. Ne öğrenmek istersin?' };
    }

    if (has(t, 'hava', 'sıcaklık', 'yağmur', 'yağacak', 'nem', 'rüzgar', 'rüzgâr', 'derece') && state.weather) {
      if (has(t, 'yarın')) {
        const sentence = tomorrowSentence();
        if (sentence) return { text: sentence };
      }
      if (has(t, 'yağmur', 'yağacak')) {
        const codes = [state.weather.current.weather_code, state.weather.daily.weather_code[1]];
        const rainy = codes.some((code) => [51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99].includes(code));
        return {
          text: (rainy ? 'Yağış görünüyor, şemsiyeni alman iyi olur. ' : 'Şu anki verilere göre yağış beklenmiyor. ') + weatherSentence(),
        };
      }
      return { text: weatherSentence() };
    }

    if (has(t, 'şarj', 'pil', 'batarya', 'battery')) {
      const sentence = batterySentence();
      if (sentence) return { text: sentence };
    }

    if (has(t, 'saat') && !has(t, 'kaç saat sürer')) {
      const now = new Date();
      return { text: 'Şu anda saat ' + now.getHours() + '.' + String(now.getMinutes()).padStart(2, '0') + '.' };
    }

    if (has(t, 'tarih', 'günlerden ne', 'ayın kaçı', 'bugün günlerden')) {
      return {
        text: 'Bugün ' + new Date().toLocaleDateString('tr-TR', {
          weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
        }) + '.',
      };
    }

    if (t.includes('kapat')) {
      const ok = closeLastApp();
      return { text: ok ? 'Son açtığım uygulamayı kapattım.' : 'Benim açtığım açık bir uygulama yok.' };
    }

    const wantsOpen = /(^|[^a-zçğıöşü0-9])aç($|[^a-zçğıöşü0-9])/.test(t) || t.includes('açar mısın');
    if (wantsOpen) {
      const app = findApp(t);
      if (app) {
        const ok = openApp(app);
        return {
          text: ok ? app.name + ' yeni sekmede açılıyor.' : app.name + ' açılmadı; tarayıcı yeni sekmeyi engelledi.',
          url: ok ? null : app.url,
        };
      }
    }

    return null;
  }

  /* ---------- 8. Ajan istemcisi (SSE + yedek uç nokta) ---------- */

  const AGENT = { busy: false };

  const TOOL_LABELS = {
    get_weather: 'Hava durumu',
    web_search: 'Web araması',
    calculate: 'Hesap',
    current_datetime: 'Tarih/saat',
    check_site: 'Site kontrolü',
    memory_save: 'Hafızaya kaydet',
    memory_search: 'Hafıza araması',
  };

  function buildContext() {
    const context = {};
    if (state.placeName) context.place = state.placeName;
    if (state.weather) {
      const current = state.weather.current;
      context.weather = weatherText(current.weather_code).toLocaleLowerCase('tr') + ', ' + Math.round(current.temperature_2m) + ' derece';
    }
    if (state.battery) {
      context.battery = 'yüzde ' + Math.round(state.battery.level * 100) + (state.battery.charging ? ', şarj oluyor' : '');
    }
    return context;
  }

  function chatPayload(question) {
    return JSON.stringify({
      question: question,
      session_id: sessionId(),
      context: buildContext(),
      history: history.slice(-8),
      voice: ttsEnabled,
    });
  }

  async function streamAnswer(question, onEvent) {
    const response = await fetch(API_BASE + '/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: chatPayload(question),
    });
    if (!response.ok || !response.body) throw new Error('Akış kullanılamıyor (' + response.status + ')');
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let index = buffer.indexOf('\n\n');
      while (index >= 0) {
        const chunk = buffer.slice(0, index);
        buffer = buffer.slice(index + 2);
        for (const line of chunk.split('\n')) {
          if (!line.startsWith('data:')) continue;
          const payload = line.slice(5).trim();
          if (!payload) continue;
          try {
            onEvent(JSON.parse(payload));
          } catch {
            /* bozuk satırı atla */
          }
        }
        index = buffer.indexOf('\n\n');
      }
    }
  }

  async function askOnce(question) {
    const response = await fetch(API_BASE + '/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: chatPayload(question),
    });
    if (!response.ok) throw new Error('Sunucu hatası (' + response.status + ')');
    return response.json();
  }

  /* ---------- 9. Sohbet arayüzü ---------- */

  function scrollConversation() {
    conversationEl.scrollTop = conversationEl.scrollHeight;
  }

  function createBubble(who) {
    const root = document.createElement('div');
    root.className = 'msg msg-' + who;
    root.setAttribute('data-testid', 'msg-' + who);
    const tools = document.createElement('div');
    tools.className = 'tools-row';
    const body = document.createElement('div');
    body.className = 'bubble-text';
    root.append(tools, body);
    conversationEl.append(root);
    scrollConversation();
    return { root, tools, body };
  }

  // Eski kodla uyumlu basit mesaj ekleyici.
  function addMsg(who, text, link) {
    pushHistory(who === 'bot' ? 'bot' : 'user', text);
    const bubble = createBubble(who);
    bubble.body.innerHTML = renderMarkdown(text);
    if (link && link.url) {
      const anchor = document.createElement('a');
      anchor.href = link.url;
      anchor.target = '_blank';
      anchor.rel = 'noopener noreferrer';
      anchor.textContent = link.label || 'Bağlantıyı aç';
      bubble.body.append(document.createElement('br'), anchor);
    }
    scrollConversation();
    return bubble;
  }

  function createStreamingBubble() {
    const { root, tools, body } = createBubble('bot');
    let raw = '';
    let paintScheduled = false;
    const pills = new Map();

    const paint = () => {
      paintScheduled = false;
      body.innerHTML = renderMarkdown(raw);
      root.classList.toggle('streaming', true);
      scrollConversation();
    };

    return {
      root,
      get text() {
        return raw;
      },
      append(delta) {
        if (!delta) return;
        raw += delta;
        if (!paintScheduled) {
          paintScheduled = true;
          requestAnimationFrame(paint);
        }
      },
      set(text) {
        raw = text || '';
        paint();
      },
      addTool(name, label) {
        const pill = document.createElement('span');
        pill.className = 'tool-pill';
        pill.dataset.state = 'running';
        pill.dataset.tool = name;
        pill.innerHTML = '<span class="tool-dot" aria-hidden="true"></span>' +
          '<span class="tool-name">' + esc(TOOL_LABELS[name] || label || name) + '</span>';
        pills.set(name, pill);
        tools.append(pill);
        tools.classList.add('visible');
        scrollConversation();
      },
      updateTool(name, ok, summary) {
        const pill = pills.get(name);
        if (!pill) return;
        pill.dataset.state = ok ? 'ok' : 'error';
        const detail = pill.querySelector('.tool-name');
        if (detail && summary) detail.textContent = (TOOL_LABELS[name] || name) + ' · ' + summary;
      },
      addSources(sources) {
        if (!sources || !sources.length) return;
        const list = document.createElement('div');
        list.className = 'sources';
        sources.slice(0, 4).forEach((item) => {
          if (!item || !item.url) return;
          const anchor = document.createElement('a');
          anchor.href = item.url;
          anchor.target = '_blank';
          anchor.rel = 'noopener noreferrer';
          anchor.textContent = item.source ? item.source + ' · ' + (item.title || item.url) : (item.title || item.url);
          list.append(anchor);
        });
        if (list.children.length) {
          root.append(list);
          scrollConversation();
        }
      },
      addError(message) {
        const note = document.createElement('p');
        note.className = 'bubble-error';
        note.textContent = message;
        root.append(note);
        scrollConversation();
      },
      finish() {
        root.classList.remove('streaming');
      },
    };
  }

  function speakReply(text, link) {
    const bubble = addMsg('bot', text, link);
    queueSpeech(text);
    return bubble;
  }

  async function handleQuestion(raw) {
    const question = String(raw == null ? '' : raw).trim();
    if (!question) return;

    resetSpeech();
    setStatus('Düşünüyorum…');
    addMsg('user', question);

    // 1) Yerel, anında yanıtlanabilen niyetler (ağ beklemez).
    const local = localAnswer(question);
    if (local) {
      speakReply(local.text, local.url ? { url: local.url, label: 'Bağlantıyı aç' } : null);
      setStatus('Konuşmak için mikrofona dokun');
      return;
    }

    if (AGENT.busy) {
      addMsg('bot', 'Önceki yanıtı tamamlıyorum, bir saniye…');
      return;
    }

    // 2) Ajan: araç kullanabilen, akan yanıt.
    AGENT.busy = true;
    const bubble = createStreamingBubble();
    let completed = false;
    try {
      await streamAnswer(question, (event) => {
        switch (event.type) {
          case 'status':
            if (event.text) setStatus(event.text);
            break;
          case 'tool_start':
            bubble.addTool(event.name, event.label);
            if (event.label) setStatus(event.label);
            break;
          case 'tool_result':
            bubble.updateTool(event.name, event.ok, event.summary);
            if (event.name === 'memory_save' || event.name === 'memory_search') loadMemory();
            break;
          case 'delta':
            bubble.append(event.text);
            feedSpeech(event.text);
            break;
          case 'done':
            completed = true;
            if (!bubble.text.trim() && event.answer) bubble.set(event.answer);
            bubble.addSources(event.sources);
            bubble.finish();
            pushHistory('bot', bubble.text.trim());
            flushSpeech();
            break;
          case 'error':
            bubble.addError(event.text || 'Bir hata oluştu.');
            break;
          default:
            break;
        }
      });
    } catch {
      // SSE başarısızsa klasik uç noktaya düş.
      try {
        const data = await askOnce(question);
        const answer = (data && data.answer) || 'Yanıt oluşturamadım.';
        bubble.set(answer);
        bubble.addSources(data && data.sources);
        bubble.finish();
        pushHistory('bot', answer);
        flushSpeech();
        completed = true;
      } catch {
        bubble.addError('Sunucuya ulaşamıyorum. Terminalde `uvicorn server:app --port 5000` çalıştığından emin ol.');
        bubble.finish();
      }
    } finally {
      AGENT.busy = false;
      if (!completed) bubble.finish();
      setStatus('Konuşmak için mikrofona dokun');
    }
  }

  /* ---------- 10. Bellek paneli ---------- */

  async function loadMemory() {
    const list = $('memory-list');
    if (!list) return;
    try {
      const response = await fetch(API_BASE + '/api/memory?session_id=' + encodeURIComponent(sessionId()));
      if (!response.ok) throw new Error('bellek');
      const data = await response.json();
      renderMemory(data.facts || []);
    } catch {
      list.innerHTML = '<li class="memory-empty">Bellek sunucudan okunamadı.</li>';
    }
  }

  function renderMemory(facts) {
    const list = $('memory-list');
    list.innerHTML = '';
    if (!facts.length) {
      list.innerHTML = '<li class="memory-empty">Henüz not yok. “Benim adım Cem, bunu hatırla” diyebilirsin.</li>';
      return;
    }
    facts.forEach((fact) => {
      const item = document.createElement('li');
      item.className = 'memory-item';
      const text = document.createElement('span');
      text.textContent = fact.text;
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'memory-delete';
      remove.dataset.id = fact.id;
      remove.setAttribute('aria-label', 'Notu sil');
      remove.textContent = '×';
      item.append(text, remove);
      list.append(item);
    });
  }

  $('memory-list').addEventListener('click', async (event) => {
    const button = event.target.closest('.memory-delete');
    if (!button) return;
    const id = button.dataset.id;
    try {
      await fetch(API_BASE + '/api/memory?fact_id=' + encodeURIComponent(id), { method: 'DELETE' });
    } catch {
      /* sessizce yoksay */
    }
    loadMemory();
  });

  $('memory-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const input = $('memory-input');
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    try {
      const response = await fetch(API_BASE + '/api/memory', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: text, session_id: sessionId() }),
      });
      if (!response.ok) throw new Error('kaydedilemedi');
      speakReply('Bunu hafızama kaydettim.');
      loadMemory();
    } catch {
      speakReply('Belleğe kaydedemedim, sunucuya ulaşamıyorum.');
    }
  });

  $('memory-clear').addEventListener('click', async () => {
    try {
      await fetch(API_BASE + '/api/memory?session_id=' + encodeURIComponent(sessionId()), { method: 'DELETE' });
    } catch {
      /* sessizce yoksay */
    }
    loadMemory();
  });

  /* ---------- 11. Site kontrolü ve kod incelemesi ---------- */

  const checkResultEl = $('check-result');

  function setCheckResult(html) {
    checkResultEl.innerHTML = html;
    checkResultEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function mdClean(text) {
    return String(text || '')
      .replace(/```[a-z]*\n?/gi, '')
      .replace(/^#{1,4}\s*/gm, '')
      .replace(/\*\*([^*]+)\*\*/g, '$1')
      .replace(/\*([^*]+)\*/g, '$1')
      .replace(/`([^`]+)`/g, '$1')
      .trim();
  }

  async function siteCheck(url) {
    try {
      const response = await fetch(API_BASE + '/api/site-check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: url }),
      });
      if (!response.ok) return null;
      return await response.json();
    } catch {
      return null;
    }
  }

  function siteCheckSentence(result) {
    if (!result) return 'Site kontrolü şu anda yapılamadı, biraz sonra tekrar dener misin?';
    if (result.error) return 'Kontrol edemedim: ' + result.error;
    if (!result.up) {
      return (result.url || 'Site') + ' şu anda erişilemiyor.' +
        (result.status ? ' HTTP durum kodu ' + result.status + '.' : ' Sunucuya bağlantı kurulamadı.');
    }
    let sentence =
      (result.url || 'Site') + ' çalışıyor. HTTP ' + result.status +
      ', yanıt süresi ' + result.responseTime + ' milisaniye' +
      (result.size ? ', sayfa boyutu ' + Math.round(result.size / 1024) + ' kilobayt' : '') + '.';
    if (result.title) sentence += ' Sayfa başlığı: ' + result.title + '.';
    return sentence;
  }

  function renderSiteResult(result) {
    if (!result) {
      setCheckResult('<p class="check-err">Kontrol yapılamadı, tekrar dene.</p>');
      return;
    }
    if (result.error || !result.up) {
      setCheckResult(
        '<p class="check-err">' + esc(result.error || result.url + ' erişilemiyor') +
          (result.status ? ' (HTTP ' + esc(result.status) + ')' : '') + '</p>'
      );
      return;
    }
    let html =
      '<div class="check-ok"><span class="dot dot-ok" aria-hidden="true"></span>' +
      '<strong>' + esc(result.url) + '</strong> çalışıyor</div>' +
      '<dl class="check-facts">' +
      '<div><dt>Durum</dt><dd>HTTP ' + esc(result.status) + '</dd></div>' +
      '<div><dt>Yanıt süresi</dt><dd>' + esc(result.responseTime) + ' ms</dd></div>' +
      (result.size ? '<div><dt>Boyut</dt><dd>' + Math.round(result.size / 1024) + ' KB</dd></div>' : '') +
      '<div><dt>HTTPS</dt><dd>' + (result.https ? 'evet' : 'hayır') + '</dd></div>' +
      (result.lang ? '<div><dt>Dil</dt><dd>' + esc(result.lang) + '</dd></div>' : '') +
      (result.h1Count !== undefined && result.h1Count !== null ? '<div><dt>H1</dt><dd>' + esc(result.h1Count) + '</dd></div>' : '') +
      (result.title ? '<div><dt>Başlık</dt><dd>' + esc(result.title) + '</dd></div>' : '') +
      '</dl>';
    if (result.description) {
      html += '<p class="check-desc">' + esc(result.description) + '</p>';
    }
    if (result.analysis) {
      html += '<div class="check-analysis"><h3>Nova analizi</h3><p>' + esc(mdClean(result.analysis)) + '</p></div>';
    }
    setCheckResult(html);
  }

  $('site-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const url = $('site-url').value.trim();
    if (!url) return;
    setCheckResult('<p class="check-loading">Kontrol ediliyor…</p>');
    const result = await siteCheck(url);
    renderSiteResult(result);
    queueSpeech(siteCheckSentence(result));
  });

  async function codeReview(code, filename) {
    try {
      const response = await fetch(API_BASE + '/api/review', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: code, filename: filename }),
      });
      if (!response.ok) return null;
      const data = await response.json();
      return (data && data.review) || null;
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

  $('file-input').addEventListener('change', (event) => {
    const file = event.target.files && event.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      $('code-input').value = String(reader.result || '');
      if (!$('code-filename').value.trim()) $('code-filename').value = file.name;
    };
    reader.readAsText(file);
  });

  $('code-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const code = $('code-input').value.trim();
    const filename = $('code-filename').value.trim();
    if (!code) {
      setCheckResult('<p class="check-err">İncelemek için kod yapıştır ya da dosya seç.</p>');
      return;
    }
    setCheckResult('<p class="check-loading">Kod inceleniyor…</p>');
    const review = await codeReview(code, filename);
    renderReviewResult(review, filename);
    if (review) queueSpeech('Kod incelemesi hazır.');
  });

  /* ---------- 12. Uygulamalar ---------- */

  document.querySelectorAll('.app-btn[data-app]').forEach((button) => {
    button.addEventListener('click', () => {
      const app = APPS.find((item) => item.key === button.dataset.app);
      if (!app) return;
      const ok = openApp(app);
      addMsg('user', app.name + ' aç');
      speakReply(ok ? app.name + ' yeni sekmede açılıyor.' : 'Tarayıcı yeni sekmeyi engelledi; bağlantıya dokunarak açabilirsin.', ok ? null : { url: app.url, label: app.name + ' aç' });
    });
  });

  $('close-app-btn').addEventListener('click', () => {
    addMsg('user', 'Son açılanı kapat');
    const ok = closeLastApp();
    speakReply(ok ? 'Son açtığım uygulamayı kapattım.' : 'Benim açtığım açık bir uygulama yok.');
  });

  /* ---------- 13. Sesle tanıma ---------- */

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  let recognition = null;
  let listening = false;

  if (!SpeechRecognition) {
    setStatus('Tarayıcın sesle tanımayı desteklemiyor — yazarak sorabilirsin');
  } else {
    recognition = new SpeechRecognition();
    recognition.lang = 'tr-TR';
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;
    recognition.continuous = false;

    recognition.onresult = (event) => {
      let interim = '';
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index];
        if (result.isFinal) {
          listening = false;
          micBtn.classList.remove('listening');
          handleQuestion(result[0].transcript);
          return;
        }
        interim += result[0].transcript;
      }
      setStatus('Dinliyorum…', interim);
    };

    recognition.onerror = (event) => {
      listening = false;
      micBtn.classList.remove('listening');
      if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
        setStatus('Mikrofon izni verilmedi. Tarayıcı izinlerinden mikrofona izin ver.');
        addMsg('bot', 'Mikrofon izni olmadan seni duyamıyorum. İzin verdikten sonra tekrar dener misin?');
      } else if (event.error === 'no-speech') {
        setStatus('Seni duyamadım, tekrar dener misin?');
      } else {
        setStatus('Ses tanıma hatası: ' + event.error);
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
    resetSpeech();
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

  /* ---------- 14. Sağlık rozeti ve başlangıç ---------- */

  async function loadHealth() {
    const badge = $('ai-badge');
    try {
      const response = await fetch(API_BASE + '/api/health');
      if (!response.ok) throw new Error('sağlık');
      const data = await response.json();
      state.health = data;
      badge.dataset.mode = data.mode || 'live';
      badge.textContent = data.mode === 'demo' ? 'Demo · ' + data.model : data.provider + ' · ' + data.model;
      badge.title =
        'Nova ' + data.version + ' · sağlayıcı: ' + data.provider + ' · model: ' + data.model +
        ' · bellek: ' + (data.memory ? data.memory.facts : 0) + ' not';
    } catch {
      badge.dataset.mode = 'offline';
      badge.textContent = 'Sunucu yok';
      badge.title = 'Backend çalışmıyor: uvicorn server:app --port 5000';
    }
  }

  document.querySelectorAll('.chip').forEach((chip) => {
    chip.addEventListener('click', () => handleQuestion(chip.dataset.q));
  });

  $('text-form').addEventListener('submit', (event) => {
    event.preventDefault();
    const input = $('text-input');
    const value = input.value;
    input.value = '';
    handleQuestion(value);
  });

  $('new-chat').addEventListener('click', () => {
    localStorage.setItem('nova.session', 'web-' + Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4));
    history.length = 0;
    conversationEl.innerHTML = '';
    resetSpeech();
    addMsg('bot', 'Yeni sohbet başladı. Ne konuşalım?');
    loadMemory();
    setStatus('Konuşmak için mikrofona dokun');
  });

  initWeather();
  initBattery();
  loadHealth();
  loadMemory();
  setInterval(initWeather, 10 * 60 * 1000);
})();
