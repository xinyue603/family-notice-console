/* ================= 家庭通知中控台 · 看板 ================= */
"use strict";

const $ = (s) => document.querySelector(s);
const html = document.documentElement;

let CFG = {
  refresh_sec: 3, theme: "dark", cols: "auto", show_sender: 1, show_group: 0,
  speak_default: 1, speak_rate: 1.05, autoscroll: 0, autoscroll_sec: 30,
  board_limit: 20, pin_limit: 5
};
let TAGS = {};
let MSGS = [];
let PINNED = [];
let lastSig = "";
let lastMaxId = 0;
let booted = false;
let voiceOn = true;
let failCount = 0;
let pollTimer = null;
let scrollTimer = null;

/* ---------- 工具 ---------- */
function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}
function hashHue(s) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return h % 360;
}
function avatarHTML(name) {
  const h = hashHue(name);
  const bg = `linear-gradient(145deg,hsl(${h} 56% 54%),hsl(${(h + 28) % 360} 60% 43%))`;
  return `<span class="av" style="background:${bg}" title="${esc(name)}">${esc(name.slice(0, 1))}</span>`;
}
function sizeClass(t) {
  const n = (t || "").replace(/\s/g, "").length;
  if (n <= 12) return "lg";
  if (n <= 28) return "md";
  if (n <= 60) return "sm";
  return "xs";
}
function pad(n) { return String(n).padStart(2, "0"); }
function hhmm(ts) {
  const d = new Date(ts * 1000);
  return pad(d.getHours()) + ":" + pad(d.getMinutes());
}
function dayLabel(ts) {
  const d = new Date(ts * 1000), n = new Date();
  const a = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const b = new Date(n.getFullYear(), n.getMonth(), n.getDate()).getTime();
  const diff = Math.round((b - a) / 86400000);
  if (diff <= 0) return "今天";
  if (diff === 1) return "昨天";
  if (diff < 7) return "周" + "日一二三四五六"[d.getDay()];
  return (d.getMonth() + 1) + "月" + d.getDate() + "日";
}

/* ---------- 主题 ---------- */
function applyTheme() {
  const q = new URLSearchParams(location.search).get("theme");
  const t = q || localStorage.getItem("ntheme") || CFG.theme || "dark";
  html.setAttribute("data-theme", t === "light" ? "light" : "dark");
  const btn = $("#theme");
  if (btn) btn.textContent = t === "light" ? "☀️" : "🌙";
}

/* ---------- 列数 ---------- */
function applyCols() {
  const q = new URLSearchParams(location.search).get("cols");
  const c = q || String(CFG.cols || "auto");
  if (c === "1" || c === "2") html.style.setProperty("--cols", c);
  else html.style.removeProperty("--cols");
}

/* ---------- 卡片 ---------- */
function makeCard(m, isNew, showGrp) {
  const t = TAGS[m.tag] || TAGS["普通通知"] || {};
  const color = t.color || m.color || "#64748b";
  const emoji = t.emoji || "💬";

  const card = document.createElement("article");
  card.className = "card" + (isNew ? " is-new" : "") + (m.pinned ? " pinned" : "");
  card.style.setProperty("--c", color);
  card.dataset.id = m.id;

  const head = document.createElement("div");
  head.className = "card-head";
  head.innerHTML =
    `<span class="badge"><span class="emoji">${esc(emoji)}</span>${esc(m.tag)}</span>` +
    (m.pinned ? '<span class="pin-tag">📌 常驻</span>' : "") +
    `<span class="time">${esc(m.ts ? hhmm(m.ts) : "")}</span>`;
  card.appendChild(head);

  if (m.image) {
    const shot = document.createElement("div");
    shot.className = "shot";
    const frame = document.createElement("div");
    frame.className = "frame";
    const img = document.createElement("img");
    img.src = "/" + String(m.image).replace(/^\/+/, "");
    img.loading = "lazy";
    img.alt = "通知图片";
    img.title = "点击查看大图";
    img.onclick = () => {
      $("#lbimg").src = img.src;
      $("#lb").classList.add("show");
    };
    img.onerror = () => { frame.style.display = "none"; };
    frame.appendChild(img);
    shot.appendChild(frame);
    card.appendChild(shot);
  }

  if (m.content) {
    const text = document.createElement("div");
    text.className = "text " + sizeClass(m.content);
    text.textContent = m.content;
    card.appendChild(text);
  }

  if (CFG.show_sender || (showGrp && m.group)) {
    const who = document.createElement("div");
    who.className = "who";
    const nm = (m.sender || "").trim();
    let inner = "";
    if (CFG.show_sender) {
      inner += avatarHTML(nm || "未署名") +
        `<span class="nm">${esc(nm || "未署名")}</span>`;
    }
    if (showGrp && m.group) {
      inner += `<span class="grp" title="${esc(m.group)}">${esc(m.group)}</span>`;
    }
    who.innerHTML = inner;
    card.appendChild(who);
  }
  return card;
}

/* ---------- 渲染 ---------- */
function render() {
  const board = $("#board");
  board.innerHTML = "";

  if (!PINNED.length && !MSGS.length) {
    board.innerHTML =
      '<div class="empty-state"><div class="ico">📭</div><h3>还没有通知</h3>' +
      "<p>在钉钉群里 @机器人 说一句话就会出现在这里<br>" +
      '支持 <code>#作业: 数学第12页</code> 或 <code>#采购 牛奶</code></p></div>';
    return;
  }

  let first = true;

  if (PINNED.length) {
    const sec = document.createElement("section");
    sec.className = "pin-sec";
    const head = document.createElement("div");
    head.className = "pin-head";
    head.innerHTML = `<span>📌 常驻看板 · ${PINNED.length}</span><span class="ln"></span>`;
    sec.appendChild(head);
    const cols = document.createElement("div");
    cols.className = "cols";
    sec.appendChild(cols);
    board.appendChild(sec);
    let lastG = null;
    PINNED.forEach((m, i) => {
      const showG = !!m.group && m.group !== lastG;
      lastG = m.group || lastG;
      cols.appendChild(makeCard(m, false, showG));
    });
    first = false;
  }

  let curDay = null, colsEl = null, lastGrp = null;
  MSGS.forEach((m, i) => {
    const d = dayLabel(m.ts);
    if (d !== curDay) {
      curDay = d;
      const sec = document.createElement("section");
      sec.className = "group";
      const h = document.createElement("div");
      h.className = "day";
      h.textContent = d;
      sec.appendChild(h);
      colsEl = document.createElement("div");
      colsEl.className = "cols";
      sec.appendChild(colsEl);
      board.appendChild(sec);
    }
    const showG = !!m.group && m.group !== lastGrp;
    lastGrp = m.group || lastGrp;
    colsEl.appendChild(makeCard(m, first && i === 0, showG));
    first = false;
  });
}

/* ---------- 状态条 ---------- */
function updateChips() {
  const total = MSGS.length + PINNED.length;
  $("#chipTotal").textContent = `共 ${total} 条`;
  $("#chipPin").textContent = `📌 常驻 ${PINNED.length} 条`;
  const newest = Math.max(0, ...MSGS.map(m => m.ts), ...PINNED.map(m => m.ts));
  $("#chipUpdated").textContent = newest ? "最后更新 " + hhmm(newest) : "暂无消息";
  const senders = new Set([...MSGS, ...PINNED].map(m => (m.sender || "").trim()).filter(Boolean));
  $("#chipSender").textContent = `发送人 ${senders.size} 位`;
  $("#chipTip").textContent = `${CFG.refresh_sec} 秒自动刷新`;
}

/* ---------- 语音 ---------- */
function speak(m) {
  if (!voiceOn || !window.speechSynthesis) return;
  const t = TAGS[m.tag] || {};
  if (t.speak === 0 || t.speak === false) return;
  if (!m.content) return;
  let body = m.content.replace(/\s+/g, " ").slice(0, 120);
  const nm = (m.sender || "").trim();
  const text = [m.tag, nm, body].filter(Boolean).join("，");
  try {
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "zh-CN";
    u.rate = Number(CFG.speak_rate) || 1.05;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(u);
  } catch (e) { /* 忽略 */ }
}

/* ---------- 自动滚动 ---------- */
function setupScroll() {
  if (scrollTimer) { clearInterval(scrollTimer); scrollTimer = null; }
  if (!Number(CFG.autoscroll)) return;
  const step = () => {
    const h = document.documentElement;
    if (h.scrollTop + window.innerHeight >= h.scrollHeight - 8) {
      window.scrollTo({ top: 0, behavior: "smooth" });
    } else {
      window.scrollBy({ top: Math.round(window.innerHeight * 0.85), behavior: "smooth" });
    }
  };
  scrollTimer = setInterval(step, Math.max(5, Number(CFG.autoscroll_sec) || 30) * 1000);
}

/* ---------- 连接状态 ---------- */
function setConn(ok) {
  const pill = $("#conn");
  if (!pill) return;
  pill.classList.toggle("bad", !ok);
  $("#connText").textContent = ok ? "已连接" : "连接中断";
}

/* ---------- 拉数据 ---------- */
async function pull() {
  try {
    const r = await fetch("/api/board", { cache: "no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const j = await r.json();
    if (j.code !== 200) throw new Error("bad code");

    const oldRefresh = CFG.refresh_sec;
    CFG = Object.assign(CFG, j.config || {});
    TAGS = {};
    (j.tags || []).forEach(t => { TAGS[t.name] = t; });
    PINNED = j.pinned || [];
    MSGS = j.data || [];

    const sig = JSON.stringify([
      PINNED.map(m => [m.id, m.pinned, m.image]),
      MSGS.map(m => [m.id, m.content, m.image, m.ts, m.sender, m.tag])
    ]);

    if (sig !== lastSig) {
      render();
      updateChips();
      lastSig = sig;
    }

    const maxId = Math.max(0, ...MSGS.map(m => m.id), ...PINNED.map(m => m.id));
    if (booted && maxId > lastMaxId) {
      const fresh = [...MSGS, ...PINNED].filter(m => m.id > lastMaxId).sort((a, b) => b.id - a.id);
      if (fresh.length) speak(fresh[0]);
    }
    lastMaxId = Math.max(lastMaxId, maxId);
    booted = true;

    if (Number(CFG.refresh_sec) !== Number(oldRefresh)) startPolling();
    setConn(true);
    failCount = 0;
  } catch (e) {
    failCount++;
    if (failCount >= 2) setConn(false);
  }
}

function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(pull, Math.max(1, Number(CFG.refresh_sec) || 3) * 1000);
}

/* ---------- 时钟 ---------- */
function tick() {
  const d = new Date();
  const n = $("#now"), dt = $("#date");
  if (n) n.textContent = pad(d.getHours()) + ":" + pad(d.getMinutes());
  if (dt) dt.textContent = `${d.getMonth() + 1}月${d.getDate()}日 周${"日一二三四五六"[d.getDay()]}`;
}

/* ---------- 交互 ---------- */
function bind() {
  $("#lb").onclick = () => $("#lb").classList.remove("show");

  $("#theme").onclick = () => {
    const next = html.getAttribute("data-theme") === "light" ? "dark" : "light";
    html.setAttribute("data-theme", next);
    localStorage.setItem("ntheme", next);
    $("#theme").textContent = next === "light" ? "☀️" : "🌙";
  };

  const v = $("#voice");
  voiceOn = localStorage.getItem("nvoice") !== "0";
  v.classList.toggle("on", voiceOn);
  v.textContent = voiceOn ? "🔊" : "🔇";
  v.onclick = () => {
    voiceOn = !voiceOn;
    localStorage.setItem("nvoice", voiceOn ? "1" : "0");
    v.classList.toggle("on", voiceOn);
    v.textContent = voiceOn ? "🔊" : "🔇";
    if (!voiceOn && window.speechSynthesis) window.speechSynthesis.cancel();
  };

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") $("#lb").classList.remove("show");
  });
}

/* ---------- 启动 ---------- */
tick();
setInterval(tick, 10000);
applyTheme();
bind();
pull().then(() => { applyCols(); setupScroll(); startPolling(); });
