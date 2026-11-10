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

  function speak(text) {
    $("caption").textContent = text;
    if (!$("voice-on").checked || !("speechSynthesis" in window)) { setState("idle"); return; }
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    if (voice) u.voice = voice;
    u.rate = 1.02; u.pitch = 0.9;
    u.onstart = () => { pauseRecognitionForSpeech(true); setState("speaking"); };
    u.onboundary = () => { speakingPulse = 0.9; };
    u.onend = u.onerror = () => { setState("idle"); pauseRecognitionForSpeech(false); };
    speechSynthesis.speak(u);
  }

  // Speech recognition (Chrome / Edge).
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  let rec = null, recActive = false, wantContinuous = false, pausedForSpeech = false;
  if (SR) {
    rec = new SR();
    rec.lang = "en-GB";
    rec.interimResults = true;
    rec.onresult = (e) => {
      let interim = "", final = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        (r.isFinal ? (final += r[0].transcript) : (interim += r[0].transcript));
      }
      level = Math.min(1, level + 0.35);
      if (interim) $("caption").textContent = interim;
      if (final) handleHeard(final.trim());
    };
    rec.onstart = () => { recActive = true; if (!wantContinuous) setState("listening"); };
    rec.onend = () => {
      recActive = false;
      if (wantContinuous && !pausedForSpeech) { try { rec.start(); } catch { /* already starting */ } }
      else if (state === "listening") setState("idle");
    };
    rec.onerror = (e) => { if (e.error === "not-allowed") addActivity("<b>MIC</b> permission denied"); };
  } else {
    $("mic").disabled = true;
    $("always-listen").disabled = true;
    $("mic").title = "Speech recognition needs Chrome or Edge";
  }

  function handleHeard(text) {
    if (wantContinuous) {
      const m = text.match(/\bjarvis\b[,.!?]?\s*(.*)$/i);
      if (!m) return;                       // not addressed to Jarvis
      text = m[1].trim();
      if (!text) { speak("Yes?"); return; }
    }
    send(text);
  }

  function startListening() {
    if (!rec || recActive) return;
    speechSynthesis.cancel();
    try { rec.continuous = wantContinuous; rec.start(); } catch { /* ignore */ }
  }
  function stopListening() { if (rec && recActive && !wantContinuous) rec.stop(); }
  function pauseRecognitionForSpeech(pause) {
    if (!rec || !wantContinuous) return;
    pausedForSpeech = pause;
    if (pause && recActive) rec.stop();
    if (!pause && !recActive) startListening();
  }

  $("mic").addEventListener("click", () => (recActive && !wantContinuous ? stopListening() : startListening()));
  document.addEventListener("keydown", (e) => {
    if (e.code === "Space" && document.activeElement !== $("chat-input") && !e.repeat) { e.preventDefault(); startListening(); }
  });
  document.addEventListener("keyup", (e) => {
    if (e.code === "Space" && document.activeElement !== $("chat-input")) stopListening();
  });
  $("always-listen").addEventListener("change", (e) => {
    wantContinuous = e.target.checked;
    if (wantContinuous) { addActivity("<b>WAKE WORD</b> say “Jarvis …”"); startListening(); }
    else if (rec && recActive) rec.stop();
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
      case "reply":
        addMsg("jarvis", ev.text, ev.channel);
        if (ev.channel === "hud" || ev.channel === "briefing") speak(ev.text); else setState("idle", false);
        break;
      case "tool":
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
  }

  function send(text) {
    if (!text || !socket || socket.readyState !== 1) return;
    addMsg("user", text, "hud");
    $("caption").textContent = "";
    setState("thinking", false);
    socket.send(JSON.stringify({ type: "chat", text }));
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
