/* The HUD: voice scope (or classic reactor), voice in/out, and the link to the brain. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);

  // ---------------------------------------------------------------- token --
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  };
  const urlToken = new URLSearchParams(location.search).get("token");
  if (urlToken) { store.set("jarvis-token", urlToken); history.replaceState(null, "", "/"); }
  const token = urlToken || store.get("jarvis-token");

  // ---------------------------------------------------------------- state --
  let state = "idle";            // idle | listening | thinking | speaking
  let level = 0;                 // 0..1 audio energy driving the core
  let speakingPulse = 0;
  const labels = { idle: "STANDBY", listening: "LISTENING", thinking: "PROCESSING", speaking: "TRANSMITTING" };
  const THEME = document.body.dataset.theme === "classic" ? "classic" : "phosphor";
  const NAME = (document.body.dataset.name || "Huxley").trim();
  const NAME_UP = NAME.toUpperCase();
  // The wake word, plus spellings speech recognition tends to produce for "Huxley".
  const NAME_RE = "(?:huxley|huxly|hucksley|huxleigh|hux ?lee|hugsley|huckley)";
  // Phones and tablets: tap-to-talk only (no wake word), and no extra mic tap for the
  // scope, which would compete with speech recognition for the microphone.
  const MOBILE = /Android|iPhone|iPad|Mobile/i.test(navigator.userAgent) && matchMedia("(pointer: coarse)").matches;
  if (MOBILE) document.body.classList.add("mobile");

  // Which window this is. Replies are spoken only on the screen that asked.
  let clientId = "", remote = false;
  const mine = (ev) => !ev.origin || ev.origin === clientId;

  // ----------------------------------------------------------- phone tabs --
  function showTab(name) {
    document.body.dataset.tab = name;
    document.querySelectorAll(".tabs [data-tab]").forEach((b) =>
      b.setAttribute("aria-selected", String(b.dataset.tab === name)));
    store.set("jarvis-tab", name);
    requestAnimationFrame(() => resize());
  }
  document.querySelectorAll(".tabs [data-tab]").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));

  function setState(next, broadcast = true) {
    state = next;
    const el = $("state-label");
    el.textContent = labels[next] || next.toUpperCase();
    el.className = "state " + next;
    $("mic").classList.toggle("active", next === "listening");
    $("scope-state").textContent = "● " + (next === "idle" ? "IDLE" : (labels[next] || next.toUpperCase()));
    if (broadcast && socket && socket.readyState === 1) socket.send(JSON.stringify({ type: "state", state: next }));
  }

  // ---------------------------------------------------------------- clock --
  function tick() {
    const now = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    $("clock-time").textContent = $("mini-clock").textContent = `${pad(now.getHours())}:${pad(now.getMinutes())}`;
    const DAYS = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];
    const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
    $("clock-date").textContent = `${DAYS[now.getDay()]} ${pad(now.getDate())} ${MONTHS[now.getMonth()]} ${now.getFullYear()}`;
  }
  setInterval(tick, 1000); tick();

  // -------------------------------------------------------------- reactor --
  const canvas = $("reactor");
  const ctx = canvas.getContext("2d");
  let W = 0, H = 0, DPR = 1;
  function resize() {
    DPR = window.devicePixelRatio || 1;
    W = canvas.clientWidth; H = canvas.clientHeight;
    canvas.width = W * DPR; canvas.height = H * DPR;
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  }
  window.addEventListener("resize", resize); resize();
  showTab(["talk", "day", "status"].includes(store.get("jarvis-tab")) ? store.get("jarvis-tab") : "talk");

  const CYAN = "79,209,255", AMBER = "255,181,71";
  function arc(r, a0, a1, width, alpha, color = CYAN) {
    ctx.beginPath();
    ctx.strokeStyle = `rgba(${color},${alpha})`;
    ctx.lineWidth = width;
    ctx.arc(0, 0, r, a0, a1);
    ctx.stroke();
  }

  function drawReactor(t) {
    const s = t / 1000;
    ctx.clearRect(0, 0, W, H);
    const R = Math.min(W, H) * 0.42;
    const speed = state === "thinking" ? 3.2 : state === "listening" ? 1.4 : state === "speaking" ? 1.1 : 0.45;
    const accent = state === "thinking" ? AMBER : CYAN;
    if (state === "speaking") speakingPulse = Math.max(speakingPulse * 0.92, 0.25 + 0.25 * Math.sin(s * 9) ** 2);
    else speakingPulse *= 0.9;
    const energy = Math.min(1, level + speakingPulse);

    ctx.save();
    ctx.translate(W / 2, H / 2);

    // Outer tick ring
    ctx.save(); ctx.rotate(s * 0.05 * speed);
    for (let i = 0; i < 120; i++) {
      const a = (i / 120) * Math.PI * 2;
      const long = i % 10 === 0;
      ctx.beginPath();
      ctx.strokeStyle = `rgba(${CYAN},${long ? 0.7 : 0.25})`;
      ctx.lineWidth = long ? 2 : 1;
      ctx.moveTo(Math.cos(a) * R, Math.sin(a) * R);
      ctx.lineTo(Math.cos(a) * (R - (long ? 14 : 7)), Math.sin(a) * (R - (long ? 14 : 7)));
      ctx.stroke();
    }
    ctx.restore();

    // Rotating segmented rings
    const rings = [
      { r: 0.86, n: 3, gap: 0.5, w: 3, dir: 1, sp: 0.4, a: 0.8 },
      { r: 0.76, n: 8, gap: 0.25, w: 8, dir: -1, sp: 0.25, a: 0.35 },
      { r: 0.66, n: 2, gap: 1.2, w: 2, dir: 1, sp: 0.9, a: 0.9 },
      { r: 0.58, n: 24, gap: 0.12, w: 5, dir: -1, sp: 0.15, a: 0.5 },
    ];
    for (const g of rings) {
      ctx.save(); ctx.rotate(s * g.sp * g.dir * speed);
      const seg = (Math.PI * 2) / g.n;
      for (let i = 0; i < g.n; i++) arc(R * g.r, i * seg, (i + 1) * seg - g.gap, g.w, g.a, i === 0 ? accent : CYAN);
      ctx.restore();
    }

    // Voice waveform ring
    ctx.beginPath();
    const base = R * 0.46;
    for (let i = 0; i <= 180; i++) {
      const a = (i / 180) * Math.PI * 2;
      const wobble = energy * R * 0.06 * (Math.sin(a * 6 + s * 7) * 0.6 + Math.sin(a * 11 - s * 5) * 0.4);
      const r = base + wobble;
      const x = Math.cos(a) * r, y = Math.sin(a) * r;
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    }
    ctx.strokeStyle = `rgba(${accent},${0.5 + energy * 0.5})`;
    ctx.lineWidth = 2;
    ctx.shadowColor = `rgba(${accent},0.9)`; ctx.shadowBlur = 14;
    ctx.stroke();
    ctx.shadowBlur = 0;

    // Core
    const coreR = R * (0.26 + energy * 0.05 + Math.sin(s * 2) * 0.008);
    const grad = ctx.createRadialGradient(0, 0, 0, 0, 0, coreR);
    grad.addColorStop(0, "rgba(255,255,255,0.95)");
    grad.addColorStop(0.35, `rgba(${accent},0.85)`);
    grad.addColorStop(1, `rgba(${accent},0)`);
    ctx.fillStyle = grad;
    ctx.beginPath(); ctx.arc(0, 0, coreR, 0, Math.PI * 2); ctx.fill();
    arc(coreR * 0.75, 0, Math.PI * 2, 1.5, 0.6, accent);

    ctx.restore();
  }

  // Green CRT oscilloscope: your real mic waveform while listening, a speech-shaped
  // trace while speaking, a sweeping sine while thinking, a quiet line at rest.
  const cssVar = (n) => getComputedStyle(document.body).getPropertyValue(n).trim();
  let FG = cssVar("--fg") || "#4dff88", GRID = cssVar("--line") || "#1d5c33", FAINT = cssVar("--faint") || "#1f7a44";
  function drawScope(t) {
    const s = t / 1000;
    if (state === "speaking") speakingPulse = Math.max(speakingPulse * 0.92, 0.25 + 0.25 * Math.sin(s * 9) ** 2);
    else speakingPulse *= 0.9;
    ctx.clearRect(0, 0, W, H);
    ctx.lineWidth = 1; ctx.strokeStyle = FAINT; ctx.globalAlpha = 0.35; ctx.shadowBlur = 0;
    ctx.beginPath();
    for (let i = 1; i < 10; i++) { const x = (W * i) / 10; ctx.moveTo(x, 0); ctx.lineTo(x, H); }
    for (let i = 1; i < 8; i++) { const y = (H * i) / 8; ctx.moveTo(0, y); ctx.lineTo(W, y); }
    ctx.stroke();
    ctx.globalAlpha = 0.8; ctx.strokeStyle = GRID; ctx.beginPath();
    ctx.moveTo(0, H / 2); ctx.lineTo(W, H / 2); ctx.moveTo(W / 2, 0); ctx.lineTo(W / 2, H); ctx.stroke();
    ctx.globalAlpha = 1;

    const mid = H / 2, amp = H * 0.36, n = Math.max(160, Math.floor(W / 3));
    const live = analyser && state === "listening";
    if (live) analyser.getByteTimeDomainData(waveData);
    ctx.beginPath();
    for (let i = 0; i <= n; i++) {
      const x = (i / n) * W;
      let y;
      if (live) {
        y = mid + ((waveData[Math.floor((i / n) * (waveData.length - 1))] - 128) / 128) * amp * 2.2;
      } else if (state === "speaking") {
        const env = 0.3 + 0.7 * speakingPulse;
        y = mid + amp * env * (0.6 * Math.sin(i * 0.2 + s * 17) * Math.sin(i * 0.033 + s * 2.7) + 0.28 * Math.sin(i * 0.61 - s * 13));
      } else if (state === "thinking") {
        y = mid + amp * 0.4 * Math.sin(i * 0.07 - s * 8) * (0.55 + 0.45 * Math.sin(s * 2.4));
      } else if (state === "listening") {
        y = mid + amp * level * 0.6 * Math.sin(i * 0.3 + s * 21);
      } else {
        y = mid + Math.sin(i * 0.045 + s * 1.3) * 2 + (Math.random() - 0.5) * 1.4;
      }
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    }
    ctx.strokeStyle = FG; ctx.lineWidth = 2.5; ctx.shadowColor = FG; ctx.shadowBlur = 12;
    ctx.stroke();
    ctx.shadowBlur = 0;
  }

  function draw(t) {
    if (THEME === "classic") drawReactor(t); else drawScope(t);
    level *= 0.9;
    requestAnimationFrame(draw);
  }
  requestAnimationFrame(draw);

  // Real microphone waveform for the scope (only while listening).
  let audioCtx = null, analyser = null, micStream = null, waveData = null;
  async function startAnalyser() {
    if (analyser || THEME === "classic" || MOBILE || !navigator.mediaDevices) return;
    try {
      micStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      audioCtx = new AudioContext();
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 1024;
      audioCtx.createMediaStreamSource(micStream).connect(analyser);
      waveData = new Uint8Array(analyser.fftSize);
    } catch { analyser = null; }
  }
  function stopAnalyser() {
    if (micStream) micStream.getTracks().forEach((tr) => tr.stop());
    if (audioCtx) audioCtx.close();
    micStream = null; audioCtx = null; analyser = null;
  }

  // ------------------------------------------------------------ transcript --
  function addMsg(kind, text, channel) {
    const div = document.createElement("div");
    div.className = "msg " + kind;
    const now = new Date();
    const hhmm = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
    const src = (channel && !["hud", "briefing", "reminder"].includes(channel) ? channel : "HUD").toUpperCase();
    const who = kind === "user" ? `${src} ▸` : (kind === "tool" || kind === "sys") ? "SYS" : `${NAME_UP} ◂`;
    const label = document.createElement("span");
    label.className = "who"; label.textContent = `${hhmm} ${who}`;
    div.append(label, document.createTextNode(text));
    $("log").append(div);
    $("log").scrollTop = $("log").scrollHeight;
    return div;
  }
  function addActivity(html) {            // callers escape their variable parts
    const tmp = document.createElement("div");
    tmp.innerHTML = html;
    addMsg("sys", tmp.textContent);
    while ($("log").children.length > 200) $("log").firstChild.remove();
  }
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  // ---------------------------------------------------------------- voice --
  let voice = null;
  function pickVoice() {
    const voices = speechSynthesis.getVoices();
    const prefs = [/Ryan.*Natural/i, /Thomas.*Natural/i, /Google UK English Male/i, /Daniel/i, /George/i, /en-GB/i];
    for (const p of prefs) {
      const v = voices.find((v) => p.test(v.name) || p.test(v.lang));
      if (v) return v;
    }
    return voices.find((v) => /^en/i.test(v.lang)) || null;
  }
  if ("speechSynthesis" in window) {
    speechSynthesis.onvoiceschanged = () => { voice = pickVoice(); };
    voice = pickVoice();
  }

  // Speech is queued sentence by sentence, so Huxley starts talking while
  // Claude is still writing the rest of the reply.
  let speechPending = 0;
  const idleCallbacks = [];
  function cleanForSpeech(t) {
    return t.replace(/\[([^\]]*)\]\([^)]*\)/g, "$1").replace(/https?:\/\/\S+/g, "the link")
            .replace(/[*#`>]+/g, "").replace(/(^|\s)_+|_+(\s|$)/g, "$1$2").replace(/\s+/g, " ").trim();
  }
  function enqueueSpeech(text) {
    text = cleanForSpeech(text);
    if (!text) return;
    $("caption").textContent = text;
    if (!$("voice-on").checked || !("speechSynthesis" in window)) return;
    const u = new SpeechSynthesisUtterance(text);
    if (voice) u.voice = voice;
    u.rate = 1.04; u.pitch = 0.9;
    speechPending++;
    u.onstart = () => { pauseRecognitionForSpeech(true); setState("speaking"); };
    u.onboundary = () => { speakingPulse = 0.9; };
    u.onend = u.onerror = () => { speechPending = Math.max(0, speechPending - 1); if (!speechPending) speechIdle(); };
    speechSynthesis.speak(u);
  }
  function speechIdle() {
    if (speechPending) return;
    if (state === "speaking") setState("idle");
    pauseRecognitionForSpeech(false);
    idleCallbacks.splice(0).forEach((fn) => fn());
  }
  function whenSpeechDone(fn) { if (speechPending) idleCallbacks.push(fn); else fn(); }
  function stopSpeaking() { idleCallbacks.length = 0; speechPending = 0; speechSynthesis.cancel(); }
  function speak(text) { enqueueSpeech(text); if (!speechPending) setState("idle"); }

  // Speech recognition (Chrome / Edge).
  //
  // The browser decides on its own that you've stopped talking after a short
  // pause, and a web page can't change that. So recognition runs continuously,
  // the words are collected across pauses, and the question is only sent after
  // you've been quiet for PAUSE_MS. If the browser ends a session early, it is
  // restarted without losing what was already heard.
  //   - Hold Space: listens while held, sends when you let go.
  //   - Click MIC: listens until you pause (or click again to send now).
  //   - Wake word: always listening; "Huxley ..." questions are sent after a pause.
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  let rec = null, recActive = false, wantContinuous = false, pausedForSpeech = false;
  let mode = null;                 // null | "hold" | "tap" | "wake"
  let heard = [], interimText = "", silenceTimer = null;
  let PAUSE_MS = Number(store.get("jarvis-pause-ms")) || 2500;

  function currentText() { return (heard.join(" ") + " " + interimText).replace(/\s+/g, " ").trim(); }
  function clearHeard() { heard = []; interimText = ""; clearTimeout(silenceTimer); }

  if (SR) {
    rec = new SR();
    rec.lang = "en-GB";
    rec.interimResults = true;
    // Android repeats words in continuous mode; there, each phrase is its own
    // session and onend restarts it, which collects the words the same way.
    rec.continuous = !MOBILE;
    rec.onresult = (e) => {
      if (!mode) return;                 // not listening any more: ignore stragglers
      interimText = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) heard.push(r[0].transcript.trim());
        else interimText += r[0].transcript;
      }
      level = Math.min(1, level + 0.35);
      const text = currentText();
      if (text) $("caption").textContent = text;
      clearTimeout(silenceTimer);
      clearTimeout(followupTimer);
      if (mode !== "hold") silenceTimer = setTimeout(finishUtterance, pauseFor(text, !interimText));
    };
    rec.onstart = () => { recActive = true; if (mode && mode !== "wake") setState("listening"); };
    rec.onend = () => {
      recActive = false;
      // Chrome ends sessions on its own (silence, ~60s limit, network blips): keep going.
      if (mode && !pausedForSpeech) { try { rec.start(); } catch { /* already starting */ } }
      else if (state === "listening") setState("idle");
    };
    rec.onerror = (e) => {
      if (e.error === "not-allowed") { addActivity("<b>MIC</b> permission denied"); mode = null; }
    };
  } else {
    $("mic").disabled = true;
    $("always-listen").disabled = true;
    $("mic").title = "Speech recognition needs Chrome or Edge";
  }
  if (MOBILE) $("always-listen").disabled = true;   // a wake word would beep all day on Android

  // Send sooner when the sentence sounds finished, wait longer when it trails off.
  const TRAILING = /\b(and|or|but|so|um+|uh+|erm|like|the|a|an|to|of|with|because|that|is|my|your|for|in|on|at|if|then|also)$/i;
  function pauseFor(text, settled) {
    if (TRAILING.test(text)) return PAUSE_MS * 1.6;
    const words = text.split(/\s+/).length;
    if (settled && (words >= 3 || (mode === "followup" && words >= 1))) return Math.max(900, PAUSE_MS * 0.6);
    return PAUSE_MS;
  }

  // Conversation mode: after a spoken answer, listen for a follow-up without
  // needing the wake word or a button. Silence or "that's all" ends it.
  const FOLLOWUP_MS = 7000;
  const END_PHRASES = new RegExp(`^(that'?s (all|it)|thanks?( you)?( ${NAME_RE})?|thank you( ${NAME_RE})?|goodbye|bye|stop|never ?mind|no thanks?|nothing( else)?)[.!]?$`, "i");
  let followupTimer = null, lastInputVoice = false;
  function maybeFollowup(ev) {
    if (ev.channel !== "hud" || !mine(ev) || !lastInputVoice || !$("convo-on").checked || !rec) return;
    if (mode && mode !== "wake") return;            // already listening some other way
    startSession("followup");
    $("caption").textContent = "Listening…";
    followupTimer = setTimeout(() => {
      if (mode === "followup" && !currentText()) { stopSession(); $("caption").textContent = ""; }
    }, FOLLOWUP_MS);
  }

  function finishUtterance() {
    clearTimeout(silenceTimer);
    const was = mode;               // decide using the mode the words were spoken in
    let text = currentText();
    clearHeard();
    if (was === "tap" || was === "followup") stopSession();
    if (!text) return;
    if ((was === "followup" || was === "tap") && END_PHRASES.test(text)) {
      lastInputVoice = false;
      enqueueSpeech("Very good.");
      return;
    }
    if (was === "wake") {
      const m = text.match(new RegExp(`\\b${NAME_RE}\\b[,.!?]?\\s*(.*)$`, "i"));
      if (!m) { $("caption").textContent = ""; return; }   // not addressed to Huxley
      text = m[1].trim();
      if (!text) { speak("Yes?"); return; }
    }
    send(text, true);
  }

  function startSession(newMode) {
    if (!rec) return;
    if (newMode !== "followup") stopSpeaking();      // pressing talk interrupts Huxley
    clearTimeout(followupTimer);
    clearHeard();
    mode = newMode;
    startAnalyser();
    if (!recActive) { try { rec.start(); } catch { /* already running */ } }
    else if (mode !== "wake") setState("listening");
  }
  function stopSession() {
    mode = wantContinuous ? "wake" : null;
    if (!mode) stopAnalyser();
    if (!mode && rec && recActive) rec.stop();
    if (state === "listening") setState("idle");
  }
  function pauseRecognitionForSpeech(pause) {
    if (!rec || (!mode && !pausedForSpeech)) return;
    pausedForSpeech = pause;
    if (pause && recActive) rec.stop();
    if (!pause && !recActive && mode) { try { rec.start(); } catch { /* ignore */ } }
  }

  $("mic").addEventListener("click", () => {
    if (mode === "tap") finishUtterance();          // click again = send now
    else startSession("tap");
  });
  const typing = () => ["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName);
  document.addEventListener("keydown", (e) => {
    if (e.code === "Space" && !typing() && !e.repeat) { e.preventDefault(); startSession("hold"); }
  });
  document.addEventListener("keyup", (e) => {
    if (e.code === "Space" && !typing() && mode === "hold") {
      // A short grace period lets the last words arrive before sending.
      setTimeout(() => { finishUtterance(); stopSession(); }, 700);
    }
  });
  $("always-listen").addEventListener("change", (e) => {
    wantContinuous = e.target.checked;
    if (wantContinuous) { addActivity(`<b>WAKE WORD</b> say “${esc(NAME)} …”`); startSession("wake"); }
    else { mode = null; clearHeard(); if (rec && recActive) rec.stop(); }
  });
  $("pause-length").value = String(PAUSE_MS);
  $("pause-length").addEventListener("change", (e) => {
    PAUSE_MS = Number(e.target.value);
    store.set("jarvis-pause-ms", String(PAUSE_MS));
  });

  // --------------------------------------------------------------- socket --
  let socket = null, retry = 0;
  function connect() {
    if (!token) { $("locked").hidden = false; return; }
    const proto = location.protocol === "https:" ? "wss" : "ws";
    socket = new WebSocket(`${proto}://${location.host}/ws?token=${encodeURIComponent(token)}`);
    socket.onopen = () => { retry = 0; $("link-core").classList.add("on"); setState(state, false); };
    socket.onclose = (e) => {
      $("link-core").classList.remove("on");
      $("state-label").textContent = "NO LINK";   // e.g. the laptop is asleep
      if (e.code === 4403) { $("locked").hidden = false; return; }
      setTimeout(connect, Math.min(10000, 1000 * 2 ** retry++));
    };
    socket.onmessage = (e) => onEvent(JSON.parse(e.data));
  }

  function onEvent(ev) {
    switch (ev.type) {
      case "hello":
        clientId = ev.client; remote = !!ev.remote;
        document.body.classList.toggle("remote", remote);
        break;
      case "status":
        $("cpu-bar").style.width = ev.cpu + "%"; $("cpu-val").textContent = Math.round(ev.cpu) + "%";
        $("mem-bar").style.width = ev.mem + "%"; $("mem-val").textContent = Math.round(ev.mem) + "%";
        $("link-telegram").classList.toggle("on", ev.telegram);
        $("telegram-status").textContent = ev.telegram_status || "";
        $("link-phone").classList.toggle("on", ev.phone);
        $("call-me").disabled = !ev.phone;
        $("model-name").textContent = ev.model;
        if (ev.dashboard) renderDashboard(ev.dashboard);
        break;
      case "user":
        // Your own typing/speech is already shown; show what other screens asked.
        if (ev.channel === "briefing" || (ev.channel === "hud" && mine(ev))) break;
        addMsg("user", ev.text, ev.channel === "hud" ? (String(ev.origin).startsWith("m-") ? "mobile" : "desk") : ev.channel);
        break;
      case "partial":
        onPartial(ev);
        break;
      case "reply": {
        const t = turns[ev.turn];
        const spokenChannel = (ev.channel === "hud" || ev.channel === "briefing") && mine(ev);
        if (t && t.text) {
          if (t.buf.trim()) enqueueSpeech(t.buf);
          if (!t.text.includes(ev.text.trim().slice(0, 40))) {   // e.g. an error after partial text
            addMsg("jarvis", ev.text, ev.channel);
            if (spokenChannel) enqueueSpeech(ev.text);
          }
        } else {
          addMsg("jarvis", ev.text, ev.channel);
          if (spokenChannel) enqueueSpeech(ev.text);
        }
        delete turns[ev.turn];
        if (!speechPending) setState("idle", false);
        if (spokenChannel) whenSpeechDone(() => maybeFollowup(ev));
        break;
      }
      case "tool":
        if ((ev.channel === "hud" || ev.channel === "briefing") && mine(ev)) {
          const t = turnOf(ev);
          if (!t.spoke && FILLERS[ev.name]) { enqueueSpeech(FILLERS[ev.name]); t.spoke = true; }
        }
        addMsg("tool", `${ev.name.toUpperCase()} ${JSON.stringify(ev.input).slice(0, 80)}`);
        break;
      case "state":
        if (ev.state === "thinking" || (ev.state === "idle" && state === "thinking")) setState(ev.state, false);
        break;
      case "reminder":
        addMsg("jarvis", ev.text, "reminder");
        speak(ev.text);
        break;
      case "activity":
        addActivity(`<b>${esc(ev.label)}</b> ${esc(ev.text)}`);
        break;
      case "listen":                       // the laptop's global talk hotkey
        if (rec && !remote && mode !== "tap") startSession("tap");
        break;
      case "memory":
        renderMemory(ev.facts || []);
        break;
      case "viewer":
        showViewer(ev);
        break;
      case "call":
        addActivity(`<b>PHONE</b> ${esc(ev.status)}`);
        break;
    }
  }

  function fillList(id, items, emptyText) {
    const ul = $(id);
    ul.replaceChildren();
    if (!items || !items.length) {
      const li = document.createElement("li");
      li.className = "empty"; li.textContent = emptyText;
      ul.append(li); return;
    }
    for (const item of items) {
      const li = document.createElement("li");
      li.textContent = item;
      ul.append(li);
    }
  }
  function renderRain(hours) {
    const box = $("dash-rain");
    box.replaceChildren();
    for (const h of hours || []) {
      const bar = document.createElement("span");
      bar.style.height = Math.max(3, h.p) + "%";
      if (h.p >= 50) bar.className = "wet";
      bar.title = `${h.h}:00 · ${h.p}%`;
      box.append(bar);
    }
    const wet = (hours || []).filter((h) => h.p >= 50);
    $("dash-rain-note").textContent = !hours || !hours.length ? ""
      : wet.length ? `${wet[0].kind || "RAIN"} ${wet[0].h}:00–${String((Number(wet[wet.length - 1].h) + 1) % 24).padStart(2, "0")}:00 · ${Math.max(...wet.map((h) => h.p))}%`
      : "NO RAIN EXPECTED";
  }
  function renderDashboard(d) {
    renderRain(d.rain_hours);
    $("dash-weather").textContent = d.weather || "--";
    fillList("dash-upcoming", d.upcoming, "No reminders");
    fillList("dash-todo", d.todo, "Nothing on the list");
    fillList("dash-today", d.today, "Nothing scheduled");
    if (d.memory && JSON.stringify(d.memory) !== JSON.stringify(memoryFacts)) renderMemory(d.memory);
  }

  // ------------------------------------------------------ streamed turns --
  const turns = {};   // turn id -> { buf, text, spoke, el }
  const FILLERS = {
    get_weather: "Checking the weather.", web_search: "Let me look that up.",
    web_fetch: "Reading the page.", show_on_screen: "Pulling that up.",
    show_map: "Bringing up the map.", run_protocol: "Running it now.", system_status: "One moment.",
    look_at_screen: "Let me have a look.", get_calendar: "Checking your calendar.",
    read_clipboard: "Let me see what you copied.", find_files: "Searching your files.",
  };
  function turnOf(ev) { return turns[ev.turn] || (turns[ev.turn] = { buf: "", text: "", spoke: false, el: null }); }
  function onPartial(ev) {
    const t = turnOf(ev);
    t.text += ev.text; t.buf += ev.text;
    if (!t.el) t.el = addMsg("jarvis", "", ev.channel);
    t.el.lastChild.textContent = t.text;
    $("log").scrollTop = $("log").scrollHeight;
    if (!mine(ev)) { t.buf = ""; return; }   // asked on another screen: show, don't speak
    let m;
    while ((m = t.buf.match(/^([\s\S]*?[.!?…])(\s+)/)) || (m = t.buf.match(/^([^\n]+)(\n+)/))) {
      enqueueSpeech(m[1]); t.spoke = true;
      t.buf = t.buf.slice(m[0].length);
    }
    if (t.buf.length > 180) {             // very long sentence: break at a comma
      const cut = t.buf.lastIndexOf(", ");
      if (cut > 60) { enqueueSpeech(t.buf.slice(0, cut + 1)); t.spoke = true; t.buf = t.buf.slice(cut + 2); }
    }
  }

  // ------------------------------------------------------------- viewer --
  let viewerUrl = "";
  const MODE_LABEL = { frame: "LIVE PAGE", embed: "EMBED", reader: "READER", error: "ERROR" };
  function showViewer(ev) {
    const frame = $("viewer-frame"), reader = $("viewer-reader-body");
    if (ev.mode === "close") {
      $("viewer").hidden = true; frame.src = "about:blank"; return;
    }
    viewerUrl = ev.url || "";
    $("viewer").hidden = false;
    $("viewer-mode").textContent = MODE_LABEL[ev.mode] || ev.mode.toUpperCase();
    $("viewer-url").value = viewerUrl;
    $("viewer-external").href = /^https?:\/\//.test(viewerUrl) ? viewerUrl : "#";
    if (ev.mode === "frame" || ev.mode === "embed") {
      reader.hidden = true; frame.hidden = false; frame.src = ev.embed_url;
      return;
    }
    frame.hidden = true; frame.src = "about:blank"; reader.hidden = false;
    reader.replaceChildren();
    const h = document.createElement("h1");
    h.textContent = ev.title || viewerUrl;
    reader.append(h);
    if (ev.note) {
      const p = document.createElement("p");
      p.className = "note"; p.textContent = ev.note; reader.append(p);
    }
    for (const b of ev.blocks || []) {
      const tag = ["h1", "h2", "h3", "h4", "li", "blockquote", "pre"].includes(b.tag) ? (b.tag === "h1" ? "h2" : b.tag) : "p";
      const el = document.createElement(tag);
      el.textContent = b.text;   // text only: page HTML is never inserted
      reader.append(el);
    }
    reader.scrollTop = 0;
  }
  function requestView(url, reader) {
    if (!url || !socket || socket.readyState !== 1) return;
    $("viewer-mode").textContent = "LOADING";
    socket.send(JSON.stringify({ type: "view", text: url, reader: !!reader }));
  }
  $("viewer-form").addEventListener("submit", (e) => { e.preventDefault(); requestView($("viewer-url").value.trim(), false); });
  $("viewer-reader").addEventListener("click", () => requestView(viewerUrl, true));
  $("viewer-close").addEventListener("click", () => showViewer({ mode: "close" }));

  // ------------------------------------------------------- memory panel --
  let memoryFacts = [];
  function renderMemory(facts) {
    memoryFacts = facts.slice();
    const ul = $("memory-list");
    ul.replaceChildren();
    if (!facts.length) {
      const li = document.createElement("li");
      li.className = "empty"; li.textContent = "Nothing saved yet. Mention things like your birthday, family or preferences.";
      ul.append(li); return;
    }
    facts.forEach((fact, i) => {
      const li = document.createElement("li");
      const span = document.createElement("span"); span.textContent = fact;
      const btn = document.createElement("button");
      btn.type = "button"; btn.className = "vbtn"; btn.textContent = "FORGET";
      btn.setAttribute("aria-label", "Forget: " + fact);
      btn.addEventListener("click", () => {
        if (socket && socket.readyState === 1) socket.send(JSON.stringify({ type: "forget", text: String(i + 1) }));
        li.remove();
      });
      li.append(span, btn); ul.append(li);
    });
  }
  $("memory-btn").addEventListener("click", () => { $("memory-modal").hidden = false; $("memory-close").focus(); });
  $("memory-close").addEventListener("click", () => { $("memory-modal").hidden = true; });
  $("memory-modal").addEventListener("click", (e) => { if (e.target.id === "memory-modal") $("memory-modal").hidden = true; });

  // "Think harder" applies to the next question only.
  let deepNext = false;
  $("think").addEventListener("click", () => {
    deepNext = !deepNext;
    $("think").setAttribute("aria-pressed", String(deepNext));
  });

  function send(text, viaVoice = false) {
    if (!text || !socket || socket.readyState !== 1) return;
    lastInputVoice = viaVoice;
    addMsg("user", text, "hud");
    $("caption").textContent = "";
    setState("thinking", false);
    socket.send(JSON.stringify({ type: "chat", text, deep: deepNext }));
    if (deepNext) { deepNext = false; $("think").setAttribute("aria-pressed", "false"); }
  }

  $("chat-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const input = $("chat-input");
    send(input.value.trim()); input.value = "";
  });
  $("briefing").addEventListener("click", () => {
    if (socket && socket.readyState === 1) { setState("thinking", false); socket.send(JSON.stringify({ type: "briefing" })); }
  });
  $("reset").addEventListener("click", () => socket && socket.send(JSON.stringify({ type: "reset" })));
  $("call-me").addEventListener("click", async () => {
    addActivity("<b>PHONE</b> requesting call…");
    const r = await fetch("/api/call-me", { method: "POST", headers: { "x-jarvis-token": token } });
    const data = await r.json().catch(() => ({}));
    addActivity(`<b>PHONE</b> ${esc(data.result || r.statusText)}`);
  });

  // ----------------------------------------------------------- pair phone --
  // Sets up Tailscale's private address on this laptop, then shows a QR code that
  // opens Huxley on your phone (see jarvis/tailnet.py).
  const PAIR_STEPS = {
    install: (r) => `<p>Huxley reaches your phone through <b>Tailscale</b>, a free private network
      between your own devices. Nobody else can see it.</p>
      <ol><li>Install Tailscale on this laptop: <a href="${esc(r.link)}" target="_blank" rel="noopener">tailscale.com/download</a>,
      and sign in (a Google account is fine).</li>
      <li>Install <b>Tailscale</b> from the Play Store on your phone and sign in with the <b>same account</b>.</li>
      <li>Press <b>TRY AGAIN</b>.</li></ol>`,
    signin: (r) => `<p>Tailscale is installed but not connected (${esc(r.detail || "signed out")}).</p>
      <ol><li>Click the Tailscale icon near the clock and sign in / connect.</li><li>Press <b>TRY AGAIN</b>.</li></ol>`,
    enable_https: (r) => `<p>One switch to flip: your Tailscale account needs <b>HTTPS</b> turned on, so your
      phone's browser will let Huxley use the microphone.</p>
      <ol><li>Open <a href="${esc(r.link)}" target="_blank" rel="noopener">this link</a> and press <b>Enable</b>
      (or turn on <b>MagicDNS</b> and <b>HTTPS Certificates</b>).</li><li>Press <b>TRY AGAIN</b>.</li></ol>`,
    restart: () => `<p>Huxley's screen has updated, but the program behind it is still the old version.</p>
      <ol><li>Right-click the green <b>H</b> near the clock → <b>Restart Huxley</b>.</li>
      <li>Wait about 20 seconds, open Huxley again, and press <b>PAIR PHONE</b>.</li>
      <li>Still this message? Quit Huxley from the tray, end any <b>Python</b> entries in Task Manager,
        then run <b>start-huxley.bat</b>.</li></ol>`,
    error: (r) => `<p>Tailscale said:</p><p class="note">${esc(r.detail || "unknown error")}</p>
      <p>Press <b>TRY AGAIN</b>. If it keeps happening, take a photo of this and send it to Claude.</p>`,
    ready: (r) => `<div class="pair-ready">
        <div class="qr" role="img" aria-label="QR code for your phone">${r.qr || ""}</div>
        <div><ol>
          <li>On your phone, install <b>Tailscale</b> from the Play Store if you haven't, sign in with the <b>same account</b> as this laptop, and make sure it's <b>connected</b>.</li>
          <li>Scan this code with the phone's camera and open the link in <b>Chrome</b>. The first load can take
            up to a minute while Tailscale sets up the secure address.</li>
          <li>In Chrome: <b>⋮ menu → Add to Home screen → Install</b>. Huxley gets its own icon.</li>
          <li>Tap <b>[ TALK ]</b> and allow the microphone.</li>
        </ol>
        ${r.detail ? `<p class="note">${esc(r.detail)}</p>` : ""}
        <p class="note">Only works while this laptop is on and Huxley is running. Keep this code private:
          it contains your access key.</p>
        <p class="pair-url">${esc(r.url || "")}</p></div>
      </div>`,
  };
  async function pairPhone() {
    const body = $("pair-body");
    $("pair-modal").hidden = false;
    body.innerHTML = "<p>CONTACTING TAILSCALE…</p>";
    let r;
    try {
      const resp = await fetch("/api/phone/pair", { method: "POST", headers: { "x-jarvis-token": token } });
      r = resp.ok ? await resp.json()
        : resp.status === 404 ? { state: "restart" }
        : { state: "error", detail: `Huxley said ${resp.status}` };
    } catch (e) { r = { state: "error", detail: String(e) }; }
    body.innerHTML = (PAIR_STEPS[r.state] || PAIR_STEPS.error)(r) +
      (r.state === "ready" ? "" : `<button type="button" class="pill" id="pair-retry">[ TRY AGAIN ]</button>`);
    const retry = $("pair-retry");
    if (retry) retry.addEventListener("click", pairPhone);
  }
  $("pair-btn").addEventListener("click", pairPhone);
  $("pair-close").addEventListener("click", () => { $("pair-modal").hidden = true; });
  $("pair-modal").addEventListener("click", (e) => { if (e.target.id === "pair-modal") $("pair-modal").hidden = true; });

  // Installable app on phones: the service worker only shows an offline screen.
  if ("serviceWorker" in navigator && window.isSecureContext && location.hostname !== "localhost" && location.hostname !== "127.0.0.1") {
    navigator.serviceWorker.register("/sw.js").catch(() => { /* not essential */ });
  }

  connect();
})();
