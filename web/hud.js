/* J.A.R.V.I.S. HUD: reactor animation, voice in/out, and the link to the brain. */
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
  const labels = { idle: "STANDBY", listening: "LISTENING", thinking: "PROCESSING", speaking: "SPEAKING" };

  function setState(next, broadcast = true) {
    state = next;
    const el = $("state-label");
    el.textContent = labels[next] || next.toUpperCase();
    el.className = "state " + next;
    $("mic").classList.toggle("active", next === "listening");
    if (broadcast && socket && socket.readyState === 1) socket.send(JSON.stringify({ type: "state", state: next }));
  }

  // ---------------------------------------------------------------- clock --
  function tick() {
    const now = new Date();
    $("clock-time").textContent = now.toLocaleTimeString([], { hour12: false });
    $("clock-date").textContent = now.toLocaleDateString([], { weekday: "short", day: "2-digit", month: "short", year: "numeric" }).toUpperCase();
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

  const CYAN = "79,209,255", AMBER = "255,181,71";
  function arc(r, a0, a1, width, alpha, color = CYAN) {
    ctx.beginPath();
    ctx.strokeStyle = `rgba(${color},${alpha})`;
    ctx.lineWidth = width;
    ctx.arc(0, 0, r, a0, a1);
    ctx.stroke();
  }

  function draw(t) {
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
    level *= 0.9;
    requestAnimationFrame(draw);
  }
  requestAnimationFrame(draw);

  // ------------------------------------------------------------ transcript --
  function addMsg(kind, text, channel) {
    const div = document.createElement("div");
    div.className = "msg " + kind;
    const who = kind === "user" ? "YOU" : kind === "tool" ? "ACTION" : "JARVIS";
    const via = channel && channel !== "hud" ? ` · ${channel.toUpperCase()}` : "";
    const label = document.createElement("span");
    label.className = "who"; label.textContent = who + via;
    div.append(label, document.createTextNode(text));
    $("log").append(div);
    $("log").scrollTop = $("log").scrollHeight;
    return div;
  }
  function addActivity(html) {
    const li = document.createElement("li");
    li.innerHTML = html;
    $("activity").prepend(li);
    while ($("activity").children.length > 30) $("activity").lastChild.remove();
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

  // Speech is queued sentence by sentence, so Jarvis starts talking while
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
  //   - Wake word: always listening; "Jarvis ..." questions are sent after a pause.
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
    rec.continuous = true;
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
  const END_PHRASES = /^(that'?s (all|it)|thanks?( you)?( jarvis)?|thank you( jarvis)?|goodbye|bye|stop|never ?mind|no thanks?|nothing( else)?)[.!]?$/i;
  let followupTimer = null, lastInputVoice = false;
  function maybeFollowup(channel) {
    if (channel !== "hud" || !lastInputVoice || !$("convo-on").checked || !rec) return;
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
      const m = text.match(/\bjarvis\b[,.!?]?\s*(.*)$/i);
      if (!m) { $("caption").textContent = ""; return; }   // not addressed to Jarvis
      text = m[1].trim();
      if (!text) { speak("Yes?"); return; }
    }
    send(text, true);
  }

  function startSession(newMode) {
    if (!rec) return;
    if (newMode !== "followup") stopSpeaking();      // pressing talk interrupts Jarvis
    clearTimeout(followupTimer);
    clearHeard();
    mode = newMode;
    if (!recActive) { try { rec.start(); } catch { /* already running */ } }
    else if (mode !== "wake") setState("listening");
  }
  function stopSession() {
    mode = wantContinuous ? "wake" : null;
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
    if (wantContinuous) { addActivity("<b>WAKE WORD</b> say “Jarvis …”"); startSession("wake"); }
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
    socket.onopen = () => { retry = 0; $("link-core").classList.add("on"); };
    socket.onclose = (e) => {
      $("link-core").classList.remove("on");
      if (e.code === 4403) { $("locked").hidden = false; return; }
      setTimeout(connect, Math.min(10000, 1000 * 2 ** retry++));
    };
    socket.onmessage = (e) => onEvent(JSON.parse(e.data));
  }

  function onEvent(ev) {
    switch (ev.type) {
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
        if (ev.channel !== "hud" && ev.channel !== "briefing") addMsg("user", ev.text, ev.channel);
        break;
      case "partial":
        onPartial(ev);
        break;
      case "reply": {
        const t = turns[ev.turn];
        const spokenChannel = ev.channel === "hud" || ev.channel === "briefing";
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
        if (spokenChannel) whenSpeechDone(() => maybeFollowup(ev.channel));
        break;
      }
      case "tool":
        if (ev.channel === "hud" || ev.channel === "briefing") {
          const t = turnOf(ev);
          if (!t.spoke && FILLERS[ev.name]) { enqueueSpeech(FILLERS[ev.name]); t.spoke = true; }
        }
        addMsg("tool", `${ev.name} ${JSON.stringify(ev.input)}`);
        addActivity(`<b>${esc(ev.name.toUpperCase())}</b> ${esc(JSON.stringify(ev.input)).slice(0, 80)}`);
        break;
      case "state":
        if (ev.state === "thinking" || (ev.state === "idle" && state === "thinking")) setState(ev.state, false);
        break;
      case "reminder":
        addMsg("jarvis", ev.text, "reminder");
        addActivity(`<b>REMINDER</b> ${esc(ev.text)}`);
        speak(ev.text);
        break;
      case "activity":
        addActivity(`<b>${esc(ev.label)}</b> ${esc(ev.text)}`);
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
  function renderDashboard(d) {
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

  connect();
})();
