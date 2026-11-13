/* ================= 家庭通知中控台 · 管理后台 ================= */
"use strict";

const $ = (id) => document.getElementById(id);
let TAGS = [];
let MSGS = [];
let CFG = {};
let editingTag = null;
let pickedColor = "#3b82f6";

/* ---------- 通用 ---------- */
function toast(msg, ms) {
  const el = $("toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove("show"), ms || 2400);
}
function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}
function fmtTime(ts) {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
function avatar(name) {
  const n = (name || "").trim();
  if (!n) return '<span class="av-s" style="background:#475569">?</span>';
  let h = 0;
  for (let i = 0; i < n.length; i++) h = (h * 31 + n.charCodeAt(i)) >>> 0;
  h %= 360;
  return `<span class="av-s" style="background:linear-gradient(145deg,hsl(${h} 56% 54%),hsl(${(h + 28) % 360} 60% 43%))">${esc(n.slice(0, 1))}</span>`;
}

async function api(path, opts) {
  opts = opts || {};
  opts.credentials = "same-origin";
  opts.headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
  if (opts.body && typeof opts.body !== "string") opts.body = JSON.stringify(opts.body);
  const r = await fetch(path, opts);
  let j = null;
  try { j = await r.json(); } catch (e) { /* 非 JSON */ }
  if (r.status === 401) { showLogin(); throw new Error("未登录"); }
  if (!r.ok) throw new Error((j && j.detail) || ("HTTP " + r.status));
  return j;
}

/* ---------- 登录 / 设定口令 ---------- */
function showGate(which) {
  $("gate-setup").classList.toggle("show", which === "setup");
  $("gate-login").classList.toggle("show", which === "login");
}
function showLogin() {
  $("app").style.display = "none";
  showGate("login");
}
function togglePw(id, el) {
  const inp = $(id);
  const on = inp.type === "password";
  inp.type = on ? "text" : "password";
  el.textContent = on ? "🙈" : "👁";
}
function checkStrength(v) {
  let lv = 0;
  if (v.length >= 6) lv = 1;
  if (v.length >= 8) lv = 2;
  if (v.length >= 10 && /[a-zA-Z]/.test(v) && /\d/.test(v)) lv = 3;
  if (v.length >= 12 && /[a-zA-Z]/.test(v) && /\d/.test(v) && /[^a-zA-Z0-9]/.test(v)) lv = 4;
  $("st").className = "strength" + (lv ? " lv" + lv : "");
  const txt = ["6 位起步；含大小写、数字、符号更安全", "偏弱 · 建议再加长", "一般 · 建议加数字和符号", "不错", "很强"];
  $("sthint").textContent = txt[lv];
}
function gateErr(id, msg) {
  const el = $(id);
  el.textContent = msg;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 3600);
}

async function doSetup() {
  const a = $("pw1").value.trim(), b = $("pw2").value.trim();
  if (a.length < 6) return gateErr("err-setup", "口令至少 6 位");
  if (a !== b) return gateErr("err-setup", "两次输入不一致");
  try {
    await api("/api/admin/setup", { method: "POST", body: { password: a, remember: true } });
    showGate(null);
    $("app").style.display = "";
    await bootData();
    toast("口令已设置");
  } catch (e) { gateErr("err-setup", e.message); }
}

async function doLogin() {
  const v = $("pwd").value.trim();
  if (!v) return gateErr("err-login", "请输入口令");
  try {
    await api("/api/admin/login", { method: "POST", body: { password: v, remember: $("remember").checked } });
    $("pwd").value = "";
    showGate(null);
    $("app").style.display = "";
    await bootData();
  } catch (e) { gateErr("err-login", e.message); }
}

async function doLogout() {
  try { await api("/api/admin/logout", { method: "POST" }); } catch (e) { }
  location.reload();
}

async function changePwd() {
  const o = $("pwdOld").value.trim(), n = $("pwdNew").value.trim(), n2 = $("pwdNew2").value.trim();
  if (!o) return toast("请输入当前口令");
  if (n.length < 6) return toast("新口令至少 6 位");
  if (n !== n2) return toast("两次输入的新口令不一致");
  try {
    await api("/api/admin/password", { method: "POST", body: { old: o, new: n } });
    toast("口令已修改，请重新登录");
    setTimeout(() => location.reload(), 1200);
  } catch (e) { toast(e.message); }
}

/* ---------- 页签（V5：7 个一级菜单，点进去是整页） ---------- */
const PAGE_KEYS = ["sys", "data", "tags", "bot", "board", "ha", "loc"];
function switchTab(key) {
  if (!PAGE_KEYS.includes(key)) key = "sys";
  document.querySelectorAll(".nav[data-tab]").forEach(x => x.classList.toggle("active", x.dataset.tab === key));
  PAGE_KEYS.forEach(k => {
    const el = $("page-" + k);
    if (el) el.style.display = (k === key) ? "" : "none";
  });
}
document.querySelectorAll(".nav[data-tab]").forEach(n => {
  n.onclick = () => { switchTab(n.dataset.tab); location.hash = n.dataset.tab; window.scrollTo({ top: 0, behavior: "smooth" }); };
});

/* ================= 图标库 ================= */
const ICONS = [
  { cat: "提醒", items: [["🚨", "紧急 报警 重要 警告"], ["⚠️", "警告 注意 风险"], ["⏰", "闹钟 定时 提醒"], ["🔔", "铃声 通知 提醒"], ["📢", "广播 公告 通知"], ["📌", "置顶 常驻 固定"], ["❗", "感叹 重要 注意"], ["💡", "灯泡 提示 注意"], ["🔥", "火 紧急 热门"], ["🚩", "旗帜 标记"]] },
  { cat: "学习", items: [["📚", "书 作业 学习"], ["✏️", "铅笔 写字 作业"], ["📝", "笔记 记录 作业"], ["🎒", "书包 上学"], ["🏫", "学校 上学"], ["📖", "看书 阅读"], ["🖍️", "蜡笔 画画"], ["🧮", "算盘 数学 口算"], ["📐", "三角尺 数学"], ["🎓", "毕业 学位"]] },
  { cat: "生活", items: [["🍲", "菜 做饭 菜单 吃"], ["🥬", "蔬菜 买菜"], ["🛒", "采购 超市 买"], ["🧾", "小票 账单 收据"], ["💰", "钱 缴费 账单"], ["🧺", "洗衣 衣服"], ["🧹", "打扫 家务 清洁"], ["🧽", "清洁 洗碗"], ["🧴", "日用品 洗护"], ["🍎", "水果 吃"]] },
  { cat: "时间", items: [["📅", "日程 日期 安排"], ["🗓️", "日历 计划"], ["🕐", "时间 几点"], ["⏳", "倒计时 等待"], ["🎂", "生日 蛋糕"], ["🎉", "庆祝 节日"], ["🌙", "晚上 睡觉"], ["☀️", "晴天 早上"], ["🌤️", "天气 多云"], ["❄️", "冷 下雪 冬天"]] },
  { cat: "出行", items: [["🚗", "开车 出行 接送"], ["🚌", "公交 校车 出行"], ["✈️", "飞机 旅行"], ["🚲", "骑车 出行"], ["🏥", "医院 看病"], ["💊", "吃药 药"], ["🏃", "运动 跑步"], ["🛌", "睡觉 休息"], ["🚿", "洗澡"], ["🧳", "行李 出差 旅行"]] },
  { cat: "其他", items: [["📦", "快递 包裹"], ["🐶", "狗 宠物"], ["🐱", "猫 宠物"], ["🎁", "礼物 惊喜"], ["🔧", "维修 修理"], ["🏠", "家 房子"], ["💬", "通知 留言 聊天"], ["⭐", "重要 收藏"], ["🍽️", "餐具 吃饭"], ["🔌", "电器 电"]] }
];
let ICON_CAT = "全部";
function allIcons() { return ICONS.flatMap(g => g.items.map(it => ({ e: it[0], k: it[1], cat: g.cat }))); }
function renderCats() {
  const cats = ["全部"].concat(ICONS.map(g => g.cat));
  $("iconCats").innerHTML = cats.map(c => `<span class="cat${c === ICON_CAT ? " on" : ""}" onclick="setCat('${c}')">${c}</span>`).join("");
}
function setCat(c) { ICON_CAT = c; renderCats(); renderIcons(); }
function renderIcons() {
  const q = ($("iconSearch").value || "").trim();
  const cur = ($("iconBox").value || "").trim();
  let list = allIcons();
  if (ICON_CAT !== "全部") list = list.filter(i => i.cat === ICON_CAT);
  if (q) list = list.filter(i => i.k.indexOf(q) >= 0 || i.e === q);
  const grid = $("iconGrid");
  if (!list.length) { grid.innerHTML = '<div class="icon-empty">没找到匹配图标，可直接在左侧方框粘贴 emoji</div>'; return; }
  grid.innerHTML = list.map(i =>
    `<button type="button" class="icon-opt${i.e === cur ? " sel" : ""}" title="${i.k}" onclick="pickIcon('${i.e}')">${i.e}</button>`).join("");
}
function pickIcon(e) { $("iconBox").value = e; renderIcons(); }

/* ================= 标签 ================= */
async function loadTags() {
  const j = await api("/api/admin/tags");
  TAGS = j.data || [];
  renderTagRows();
  const sel = $("fTag");
  const keep = sel.value;
  sel.innerHTML = '<option value="">全部标签</option>' +
    TAGS.map(t => `<option value="${esc(t.name)}">${esc(t.name)}</option>`).join("");
  sel.value = keep;
}

function renderTagRows() {
  $("tagRows").innerHTML = TAGS.map(t => `
    <tr>
      <td><span class="swatch" style="background:${esc(t.color)}"></span></td>
      <td><span class="tag-name"><span class="tag-emoji">${esc(t.emoji || "💬")}</span>${esc(t.name)}</span></td>
      <td>
        <label class="tg-sw ${t.speak ? "on" : ""}" title="点一下切换，立即生效"
               onclick="toggleSpeak('${esc(t.name)}', ${t.speak ? 0 : 1})">
          <span class="pill"><span class="knob"></span></span>
          <span class="lb">${t.speak ? "播报" : "静音"}</span>
        </label>
      </td>
      <td class="muted">${t.sort}</td>
      <td><div class="row-actions">
        <button class="mini" onclick="openDlg('${esc(t.name)}')">编辑</button>
        <button class="mini del" onclick="delTag('${esc(t.name)}')">删除</button>
      </div></td>
    </tr>`).join("") || '<tr><td colspan="5" class="muted" style="padding:22px">还没有标签</td></tr>';
}

/* 列表内联开关：直接改 speak，不用进编辑弹窗 */
async function toggleSpeak(name, val) {
  const t = TAGS.find(x => x.name === name);
  if (!t) return;
  const dlg = $("tagRows");
  dlg.style.opacity = ".6";
  try {
    await api("/api/admin/tags", {
      method: "POST", body: {
        name: t.name, emoji: t.emoji || "", color: t.color || "#64748b",
        speak: !!val, sort: t.sort || 0
      }
    });
    t.speak = val ? 1 : 0;
    renderTagRows();
    toast(val ? `「${name}」已开启语音播报` : `「${name}」已静音`);
  } catch (e) {
    toast("切换失败：" + e.message);
  } finally {
    $("tagRows").style.opacity = "";
  }
}

function openDlg(name) {
  editingTag = name || null;
  const t = name ? TAGS.find(x => x.name === name) : null;
  $("dlgTitle").textContent = t ? "编辑标签" : "新增标签";
  $("tagName").value = t ? t.name : "";
  $("tagName").disabled = !!t;
  $("iconBox").value = t ? (t.emoji || "💬") : "🛒";
  $("tagSort").value = t ? t.sort : 50;
  pickedColor = t ? t.color : "#3b82f6";
  document.querySelectorAll("#colorRow .color-dot").forEach(d => {
    d.classList.toggle("sel", d.dataset.c.toLowerCase() === String(pickedColor).toLowerCase());
  });
  renderCats(); renderIcons();
  $("dlg").classList.add("show");
}
function closeDlg() { $("dlg").classList.remove("show"); }
$("dlg").onclick = (e) => { if (e.target.id === "dlg") closeDlg(); };
document.querySelectorAll("#colorRow .color-dot").forEach(d => {
  d.onclick = () => {
    document.querySelectorAll("#colorRow .color-dot").forEach(x => x.classList.remove("sel"));
    d.classList.add("sel");
    pickedColor = d.dataset.c;
  };
});

async function saveTag() {
  const name = $("tagName").value.trim();
  if (!name) return toast("请填标签名");
  // 播报开关已移到列表里单独控制，编辑时保留原值；新建默认开启
  const orig = editingTag ? TAGS.find(x => x.name === editingTag) : null;
  try {
    await api("/api/admin/tags", {
      method: "POST", body: {
        name, emoji: $("iconBox").value.trim(), color: pickedColor,
        speak: orig ? !!orig.speak : true,
        sort: parseInt($("tagSort").value, 10) || 0
      }
    });
    closeDlg();
    await loadTags();
    toast("标签已保存");
  } catch (e) { toast(e.message); }
}

async function delTag(name) {
  if (!confirm(`删除标签「${name}」？已有消息不会被删除，只是不再有专属配色。`)) return;
  try {
    await api("/api/admin/tags/" + encodeURIComponent(name), { method: "DELETE" });
    await loadTags();
    toast("已删除");
  } catch (e) { toast(e.message); }
}

/* ================= 配置 ================= */
function pickIM(v) {
  CFG.im_channel = v;
  document.querySelectorAll(".im-opt").forEach(el => {
    el.classList.toggle("on", el.dataset.im === v);
  });
  $("credDing").style.display = v === "ding" ? "" : "none";
  $("credWecom").style.display = v === "wecom" ? "" : "none";
}

async function loadConfig() {
  const j = await api("/api/admin/config");
  CFG = j.data || {};
  $("cfgKey").value = CFG.bot_app_key || "";
  $("cfgSecret").value = "";
  $("cfgSecret").placeholder = CFG.has_secret ? (CFG.bot_app_secret_masked + "（留空不修改）") : "尚未设置";
  $("cfgDedup").value = CFG.dedup_window;
  $("cfgTagLen").value = CFG.tag_max_len;
  $("cfgImgEdge").value = CFG.image_max_edge;

  /* --- 消息接入渠道 --- */
  pickIM(CFG.im_channel === "wecom" ? "wecom" : "ding");
  $("cfgWecomCorp").value = CFG.wecom_corp_id || "";
  $("cfgWecomAgent").value = CFG.wecom_agent_id || "";
  $("cfgWecomToken").value = CFG.wecom_token || "";
  $("cfgWecomSecret").value = "";
  $("cfgWecomSecret").placeholder = CFG.has_wecom_secret
    ? (CFG.wecom_secret_masked + "（留空不修改）") : "尚未设置";
  $("cfgWecomAes").value = "";
  $("cfgWecomAes").placeholder = CFG.has_wecom_aes_key
    ? (CFG.wecom_aes_key_masked + "（留空不修改）") : "尚未设置";
  $("cfgWecomCallback").value = location.origin + "/wecom/callback";

  /* --- Home Assistant --- */
  $("cfgHaBase").value = CFG.ha_base_url || "";
  $("cfgHaInterval").value = CFG.ha_interval;
  $("cfgHaToken").value = "";
  $("cfgHaToken").placeholder = CFG.has_ha_token
    ? (CFG.ha_token_masked + "（留空不修改）") : "尚未设置，去 HA 生成长期令牌";
  /* --- 看板显示偏好（5 个胶囊开关）---
     后端默认值是 "1"，配置里万一缺键也按"开"处理，别显示成关 */
  Object.keys(HA_PREF).forEach(k => haPrefSet(k, String(CFG[k] == null ? "1" : CFG[k]) === "1"));

  $("cfgLimit").value = CFG.board_limit;
  $("cfgRefresh").value = CFG.refresh_sec;
  $("cfgCols").value = CFG.cols;
  $("cfgTheme").value = CFG.theme;
  $("cfgSpeak").value = String(CFG.speak_default);
  $("cfgRate").value = CFG.speak_rate;
  $("cfgShowSender").value = String(CFG.show_sender);
  $("cfgShowGroup").value = String(CFG.show_group);
  $("cfgAutoScroll").value = String(CFG.autoscroll);
  $("cfgScrollSec").value = CFG.autoscroll_sec;
  $("cfgPinLimit").value = CFG.pin_limit;
  $("cfgRetention").value = CFG.retention_days;
  syncHaEnabled();   // V6-1：总开关 / 数据源块 / 天气位置卡联动
}

/* V5：原来一个大 saveBot 包打天下，页面拆成 7 个后按各页自己的字段拆开保存 */
async function saveChannel(restart) {
  const body = {
    im_channel: CFG.im_channel || "ding",
    bot_app_key: $("cfgKey").value.trim(),
    wecom_corp_id: $("cfgWecomCorp").value.trim(),
    wecom_agent_id: $("cfgWecomAgent").value.trim(),
    wecom_token: $("cfgWecomToken").value.trim(),
  };
  const sec = $("cfgSecret").value.trim();
  if (sec) body.bot_app_secret = sec;
  const wsec = $("cfgWecomSecret").value.trim();
  if (wsec) body.wecom_secret = wsec;
  const waes = $("cfgWecomAes").value.trim();
  if (waes) body.wecom_aes_key = waes;

  try {
    await api("/api/admin/config", { method: "POST", body });
    await loadConfig();
    toast("渠道配置已保存");
    if (restart) {
      toast("正在重启机器人…");
      const r = await api("/api/admin/bot/restart", { method: "POST" });
      toast("机器人已重启：" + r.active);
      loadBotStatus();
    }
  } catch (e) { toast(e.message); }
}

async function saveRecv() {
  try {
    await api("/api/admin/config", { method: "POST", body: {
      dedup_window: $("cfgDedup").value,
      tag_max_len: $("cfgTagLen").value,
      image_max_edge: $("cfgImgEdge").value,
    }});
    await loadConfig();
    toast("接收参数已保存");
  } catch (e) { toast(e.message); }
}

async function saveHa() {
  const body = {
    ha_base_url: $("cfgHaBase").value.trim().replace(/\/+$/, ""),
    ha_interval: $("cfgHaInterval").value,
  };
  const htok = $("cfgHaToken").value.trim();
  if (htok) body.ha_token = htok;
  try {
    await api("/api/admin/config", { method: "POST", body });
    await loadConfig();
    toast("HA 配置已保存");
  } catch (e) { toast(e.message); }
}

/* 看板显示偏好：5 个胶囊（跟显示偏好同页保存） */
async function savePrefs() {
  const body = {};
  Object.keys(HA_PREF).forEach(k => {
    if (k.indexOf("ha_show_") === 0) body[k] = haPrefGet(k);
  });
  try {
    await api("/api/admin/config", { method: "POST", body });
    await loadConfig();
    toast("显示偏好已保存，看板下次刷新就变");
  } catch (e) { toast(e.message); }
}

async function saveBoard() {
  const body = {
    board_limit: $("cfgLimit").value,
    refresh_sec: $("cfgRefresh").value,
    cols: $("cfgCols").value,
    theme: $("cfgTheme").value,
    speak_default: $("cfgSpeak").value,
    speak_rate: $("cfgRate").value,
    show_sender: $("cfgShowSender").value,
    show_group: $("cfgShowGroup").value,
    autoscroll: $("cfgAutoScroll").value,
    autoscroll_sec: $("cfgScrollSec").value,
    pin_limit: $("cfgPinLimit").value,
    retention_days: $("cfgRetention").value
  };
  Object.keys(HA_PREF).forEach(k => {
    if (k.indexOf("ha_show_") === 0) body[k] = haPrefGet(k);
  });
  try {
    await api("/api/admin/config", { method: "POST", body });
    await loadConfig();
    toast("看板设置已保存，看板会在下次轮询生效");
  } catch (e) { toast(e.message); }
}

/* ================= 看板显示偏好 + 设备映射 =================
   开关状态直接挂在 .pfs 的 on 类上，保存时按类取值。
   注意别用 .pt/.pd 当类名：.pt 是「接入方式」选择卡的类，会串事件。 */
const HA_PREF = {
  ha_show_offline: "pfsOffline",
  ha_show_zero_power: "pfsZero",
  ha_show_lights: "pfsLights",
  ha_show_climates: "pfsClimates",
  ha_show_tv: "pfsTv",
  /* V5：顶部天气的两个开关，在「设置家庭位置」页 */
  weather_enabled: "pfsWeather",
  weather_show_range: "pfsWxRange"
};

function haPrefSet(key, on) {
  const el = $(HA_PREF[key]);
  if (el) el.classList.toggle("on", !!on);
}
function haPrefGet(key) {
  const el = $(HA_PREF[key]);
  return (el && el.classList.contains("on")) ? "1" : "0";
}
/* 偏好行点击翻转开关：V5 起两处列表（显示偏好 / 天气），统一按 .pref-list 绑 */
document.querySelectorAll(".pref-list .pref").forEach(el => {
  el.onclick = () => {
    const sw = el.querySelector(".pfs");
    if (sw) sw.classList.toggle("on");
  };
});

/* ============ 设备映射（V6）：搜索已同步 HA 设备 → 加入映射表 ============
   实体来自 /api/admin/ha/entities（light/switch/climate/media_player 四域全量），
   当前生效映射来自 /api/ha/board 的 mapping（含实时状态与启用位）。
   表格 6 列：看板显示 / 类型 / HA实体名称 / 当前状态 / 是否启用 / 删除。
   en = 是否启用（配置保留，但不参与看板统计）；on = 设备当前是否开着。
   保存写 ha_lights_map / ha_climates_map / ha_tv_map，每项 {n,eid,en}。 */
let MAP = [];            // [{k,n,eid,s,on,en}]
let MAP_ENT = null;      // 四域实体分组缓存
let MAP_DIRTY = false;

const MAP_DOMAIN_OF = { light: "灯", switch: "灯", climate: "空调", media_player: "电视" };
const MAP_STATE = { on: "开启", off: "关闭", heat: "制热", cool: "制冷", dry: "除湿",
                    auto: "自动", fan_only: "送风", idle: "待机", standby: "待机",
                    unavailable: "不可用", unknown: "未知", playing: "播放中",
                    paused: "暂停", open: "开启", closed: "关闭" };
const MAP_OFF = { off: 1, standby: 1, unavailable: 1, unknown: 1, "": 1, none: 1 };

/* V6-1：HA 接入总开关是否启用（配置缺键按启用处理） */
function haEnabled() {
  return String(CFG.ha_enabled == null ? "1" : CFG.ha_enabled) !== "0";
}

async function mapLoadEntities(force) {
  if (MAP_ENT && !force) return MAP_ENT;
  const j = await api("/api/admin/ha/entities");
  if (!j || j.ok === false) throw new Error((j && j.msg) || "取实体列表失败");
  MAP_ENT = j.data || {};
  return MAP_ENT;
}

/* 拉平成一个数组，指示灯排到最后，搜索结果里另外标「指示灯」 */
function devAll() {
  const out = [];
  if (!MAP_ENT) return out;
  Object.keys(MAP_ENT).forEach(dom => (MAP_ENT[dom] || []).forEach(it => {
    out.push({ eid: it.eid, name: it.name || it.eid, state: it.state || "",
               dom: dom, k: MAP_DOMAIN_OF[dom] || "灯", ind: !!it.ind });
  }));
  out.sort((a, b) => (a.ind ? 1 : 0) - (b.ind ? 1 : 0));
  return out;
}
function devEntOf(eid) {
  return devAll().find(x => x.eid === eid) || null;
}
function devStateText(st) {
  return MAP_STATE[String(st || "").toLowerCase()] || st || "—";
}
function devStateCls(st, on) {
  const s = String(st || "").toLowerCase();
  return (s === "unavailable" || s === "unknown") ? "st-bad" : (on ? "st-on" : "st-off");
}

function devClose() {
  const box = $("devResults");
  if (box) { box.classList.remove("show"); box.innerHTML = ""; }
}

function devSearch(q) {
  const box = $("devResults");
  if (!box) return;
  const kw = String(q || "").trim().toLowerCase();
  if (!kw) { devClose(); return; }
  const all = devAll();
  const cnt = $("devCount");
  if (cnt) cnt.textContent = "已同步 " + all.length + " 个";
  const used = new Set(MAP.map(m => m.eid));
  const hit = all.filter(x => (x.name + " " + x.eid).toLowerCase().indexOf(kw) >= 0).slice(0, 40);
  box.innerHTML = '<div class="dev-res-h">检索到 ' + hit.length +
    ' 个已同步设备 · 点一条加入映射表</div>' +
    (hit.length ? hit.map(e => {
      const added = used.has(e.eid);
      const s = String(e.state || "");
      const on = !MAP_OFF[s.toLowerCase()];
      return `<div class="dev-item${added ? " added" : ""}" data-eid="${esc(e.eid)}">
        <span class="dn">${esc(e.name)}</span>
        ${e.ind ? '<span class="dev-badge ind">指示灯</span>' : ""}
        <span class="de">${esc(e.eid)}</span>
        <span class="dk">${esc(e.k)}</span>
        <span class="ds${on ? "" : " off"}">${esc(devStateText(s))}</span>
        ${added ? '<span class="dev-badge added">已添加</span>' : ""}
      </div>`;
    }).join("") : '<div class="dev-empty">没有匹配的设备，换个名称或 entity_id 试试</div>');
  box.classList.add("show");
  box.querySelectorAll(".dev-item:not(.added)").forEach(el => {
    el.onclick = () => devPick(el.dataset.eid);
  });
}
document.addEventListener("click", e => {
  if (!e.target.closest(".dev-search-wrap")) devClose();
});

function devPick(eid) {
  const e = devEntOf(eid);
  if (!e || MAP.some(m => m.eid === eid)) return;
  const s = String(e.state || "");
  MAP.push({ k: e.k, n: e.name, eid: e.eid, s: s || "—",
             on: !MAP_OFF[s.toLowerCase()], en: true });
  MAP_DIRTY = true;
  const inp = $("devSearch");
  if (inp) inp.value = "";
  devClose();
  mapRender();
  toast("已加入：" + e.name + "（" + e.k + "）");
}

function mapRender() {
  const tb = $("mapBody");
  if (!tb) return;
  if (!MAP.length) {
    tb.innerHTML = '<tr><td colspan="6" style="color:var(--text3)">还没有任何映射，用上面的搜索框添加设备。</td></tr>';
  } else {
    tb.innerHTML = MAP.map((m, i) => {
      const ent = devEntOf(m.eid);
      const name = ent ? ent.name : (m.eid || "—");
      const st = String(m.s || "—");
      const cls = devStateCls(st, !!m.on);
      return `<tr data-i="${i}" class="${m.en === false ? "off" : ""}">
        <td><input class="map-name" value="${esc(m.n)}" placeholder="看板显示的名字"
             oninput="mapEdit(${i},'n',this.value)"></td>
        <td class="kind">${esc(m.k)}</td>
        <td><span class="ent-name">${esc(name)}</span><span class="ent-eid">${esc(m.eid)}</span></td>
        <td class="${cls}">${esc(devStateText(st))}</td>
        <td><span class="mini-sw ${m.en === false ? "" : "on"}" title="是否启用"
             onclick="mapToggle(${i})"></span></td>
        <td><button class="map-del" title="删掉这一行" onclick="mapDel(${i})">✕</button></td>
      </tr>`;
    }).join("");
  }
  const tip = $("mapTip");
  if (tip) {
    tip.textContent = MAP_DIRTY ? "有改动还没保存" : "";
    tip.style.color = MAP_DIRTY ? "var(--warn)" : "";
  }
  const cnt = $("mapCnt");
  if (cnt) cnt.textContent = "共 " + MAP.length + " 台（启用 " +
    MAP.filter(m => m.en !== false).length + " 台）";
  const dc = $("devCount");
  if (dc && MAP_ENT) dc.textContent = "已同步 " + devAll().length + " 个";
}

function mapEdit(i, key, val) {
  if (!MAP[i]) return;
  MAP[i][key] = val;
  MAP_DIRTY = true;
  const tr = document.querySelector('#mapBody tr[data-i="' + i + '"]');
  if (tr) tr.classList.add("dirty");
  const tip = $("mapTip");
  if (tip) { tip.textContent = "有改动还没保存"; tip.style.color = "var(--warn)"; }
}

/* 停用 = 保留这行配置，但不参与看板统计；删除 = 从映射里移除 */
function mapToggle(i) {
  if (!MAP[i]) return;
  MAP[i].en = MAP[i].en === false;
  MAP_DIRTY = true;
  mapRender();
}

function mapDel(i) {
  MAP.splice(i, 1);
  MAP_DIRTY = true;
  mapRender();
}

async function mapSave() {
  const lights = [], clims = [], tv = [];
  for (const m of MAP) {
    const n = (m.n || "").trim();
    const eid = (m.eid || "").trim();
    if (!n || !eid) { toast("有「" + (m.k || "") + "」没填名字或没选实体"); return; }
    const o = { n: n, eid: eid, en: m.en !== false };
    if (m.k === "灯") lights.push(o);
    else if (m.k === "空调") clims.push(o);
    else if (m.k === "电视") tv.push(o);
  }
  if (tv.length > 1) { toast("电视只能留一个"); return; }
  const names = lights.concat(clims, tv).map(x => x.n);
  const dup = names.filter((x, i) => names.indexOf(x) !== i);
  if (dup.length) { toast("名字重复：" + dup[0]); return; }
  try {
    await api("/api/admin/config", { method: "POST", body: {
      ha_lights_map: JSON.stringify(lights),
      ha_climates_map: JSON.stringify(clims),
      ha_tv_map: JSON.stringify(tv),
    }});
    MAP_DIRTY = false;
    toast("映射已保存，看板下次刷新就变");
    await loadHaMap();
  } catch (e) { toast(e.message); }
}

async function mapReset() {
  if (!confirm("恢复成内置默认的 14 盏灯 / 5 台空调 / 示例电视？")) return;
  try {
    await api("/api/admin/config", { method: "POST", body: {
      ha_lights_map: "", ha_climates_map: "", ha_tv_map: "",
    }});
    MAP_DIRTY = false;
    toast("已恢复默认映射");
    await loadHaMap();
  } catch (e) { toast(e.message); }
}

/* 进页面时：先拿实体列表，再拿当前生效映射（含实时状态与启用位） */
async function loadHaMap() {
  const tb = $("mapBody");
  if (!tb) return;
  try { await mapLoadEntities(false); } catch (e) { /* 实体列表可选 */ }
  try {
    const r = await fetch("/api/ha/board", { cache: "no-store" });
    const j = await r.json();
    const d = j.data || {};
    const rows = d.mapping || [];
    if (!rows.length) {
      tb.innerHTML = `<tr><td colspan="6" style="color:var(--text3)">`
        + esc(d.error || d.reason || "暂无数据，请先保存 HA 地址和令牌") + `</td></tr>`;
      $("mapWarn").style.display = "none";
      return;
    }
    // 只在没有未保存改动时覆盖，免得把用户正在编辑的内容冲掉
    if (!MAP_DIRTY) {
      MAP = rows.map(m => ({ k: m.k, n: m.n, eid: m.eid, s: m.s,
                             on: !!m.on, en: m.en !== false }));
      mapRender();
    }
    const bad = rows.filter(m => m.s === "unavailable");
    const w = $("mapWarn");
    if (bad.length) {
      w.style.display = "";
      $("mapWarnTxt").innerHTML = "有 " + bad.length + " 路报 <b>unavailable</b>（"
        + bad.map(m => esc(m.n)).join("、")
        + "）。设备本身离线，不是取错实体——恢复后看板自动出现，不会报错。";
    } else {
      w.style.display = "none";
    }
  } catch (e) {
    tb.innerHTML = `<tr><td colspan="6" style="color:#f87171">读取失败：`
      + esc(e.message) + `</td></tr>`;
  }
}

/* ============ 成员与传感器映射（V7）：三组 sensor 后台可维护 ============
   取数：/api/ha/board 的 sensor_mapping（配置行 + 实时值，HA 挂了也回配置行）
   检索：/api/admin/ha/sensor_entities（只回 sensor.*，与 V6 四域实体分开）
   保存：ha_sensor_map = JSON [{k,n,eid,en}]；空串 = 回落到内置 22 行默认
   k: people 成员 / total 用电总表（只能一条）/ power 用电分路 / temp 房间温度
   en = 是否启用（配置保留但不参与看板统计），与 v 当前值无关。 */
const SENS_KINDS = {
  people: { label: "成员",     group: "成员（在家）" },
  total:  { label: "总表",     group: "用电总表（只能一条）" },
  power:  { label: "用电分路", group: "用电分路" },
  temp:   { label: "温度",     group: "房间温度" },
};
const SENS_ORDER = ["people", "total", "power", "temp"];
const SENS_HINT = { people: "在线状态", total: "总功率", power: "功率",
                    temp: "温度", other: "数值" };
let SENS = [];            // [{k,n,eid,en,nm,v,s}]
let SENS_ENT = null;      // 已同步的 sensor 实体
let SENS_DIRTY = false;

async function sensLoadEntities(force) {
  if (SENS_ENT && !force) return SENS_ENT;
  const j = await api("/api/admin/ha/sensor_entities");
  if (!j || j.ok === false) throw new Error((j && j.msg) || "取 sensor 列表失败");
  SENS_ENT = j.data || [];
  return SENS_ENT;
}
function sensAll() { return SENS_ENT || []; }
function sensEntOf(eid) { return sensAll().find(x => x.eid === eid) || null; }

function sensClose() {
  const b = $("sensResults");
  if (b) { b.classList.remove("show"); b.innerHTML = ""; }
}

function sensDoSearch(q) {
  const box = $("sensResults");
  if (!box) return;
  const kw = String(q || "").trim().toLowerCase();
  if (!kw) { sensClose(); return; }
  const as = $("sensAddAs") ? $("sensAddAs").value : "people";
  const used = new Set(SENS.map(r => r.eid));
  const hit = sensAll().filter(e =>
    ((e.name || "") + " " + (e.eid || "") + " " + (SENS_HINT[e.kind] || ""))
      .toLowerCase().indexOf(kw) >= 0).slice(0, 40);
  box.innerHTML = '<div class="dev-res-h">检索到 ' + hit.length +
    ' 个已同步 sensor · 点一条加入「' + esc(SENS_KINDS[as].label) + '」</div>' +
    (hit.length ? hit.map(e => {
      const added = used.has(e.eid);
      return `<div class="dev-item${added ? " added" : ""}" data-eid="${esc(e.eid)}">
        <span class="dn">${esc(e.name || e.eid)}</span>
        <span class="dev-badge k">${esc(SENS_HINT[e.kind] || "数值")}</span>
        <span class="de">${esc(e.eid)}</span>
        <span class="ds">${esc(e.v || e.state || "—")}</span>
        ${added ? '<span class="dev-badge added">已添加</span>' : ""}
      </div>`;
    }).join("") : '<div class="dev-empty">没有匹配的 sensor，换个名称或 entity_id 试试</div>');
  box.classList.add("show");
  box.querySelectorAll(".dev-item:not(.added)").forEach(el => {
    el.onclick = () => sensPick(el.dataset.eid);
  });
}
document.addEventListener("click", e => {
  if (!e.target.closest("#sensorPanel .dev-search-wrap")) sensClose();
});

function sensPick(eid) {
  const e = sensEntOf(eid);
  if (!e || SENS.some(r => r.eid === eid)) return;
  const k = $("sensAddAs").value;
  if (k === "total" && SENS.some(r => r.k === "total")) {
    toast("用电总表只能有一条，请先删掉现有的");
    return;
  }
  SENS.push({ k: k, n: e.name || eid, eid: eid, en: true,
              nm: e.name || eid, v: e.v || e.state || "—", s: e.state || "" });
  SENS_DIRTY = true;
  $("sensSearch").value = "";
  sensClose();
  sensRender();
  toast("已加入：" + (e.name || eid) + "（" + SENS_KINDS[k].label + "）");
}

function sensRender() {
  const tb = $("sensBody");
  if (!tb) return;
  let html = "";
  SENS_ORDER.forEach(k => {
    const list = [];
    SENS.forEach((r, i) => { if (r.k === k) list.push({ r: r, i: i }); });
    html += `<tr class="grp"><td colspan="6"><b>${esc(SENS_KINDS[k].group)}</b> · ${list.length} 项</td></tr>`;
    if (!list.length) {
      html += `<tr><td colspan="6" class="sens-empty">这一类还没有映射，用上面的搜索框添加。</td></tr>`;
      return;
    }
    list.forEach(o => {
      const r = o.r, i = o.i;
      const nm = r.nm || (sensEntOf(r.eid) || {}).name || r.n || r.eid;
      const num = parseFloat(String(r.v || "").replace(/[^\d.\-]/g, "")) || 0;
      const zero = (r.k === "power" || r.k === "total") && num === 0;
      html += `<tr class="${r.en === false ? "off" : ""}">
        <td><input class="map-name" value="${esc(r.n)}" placeholder="看板显示的名字"
             oninput="sensEdit(${i},'n',this.value)"></td>
        <td><span class="sens-tag ${r.k === "total" ? "total" : ""}">${esc(SENS_KINDS[r.k].label)}</span></td>
        <td><span class="ent-name">${esc(nm)}</span><span class="ent-eid">${esc(r.eid)}</span></td>
        <td><span class="sens-val ${zero ? "zero" : ""}">${esc(r.v || "—")}</span></td>
        <td><span class="mini-sw ${r.en === false ? "" : "on"}" title="是否启用"
             onclick="sensToggle(${i})"></span></td>
        <td><button class="map-del" title="删掉这一行" onclick="sensDel(${i})">✕</button></td>
      </tr>`;
    });
  });
  tb.innerHTML = html;
  const cnt = $("sensCnt");
  if (cnt) cnt.textContent = "共 " + SENS.length + " 项（启用 " +
    SENS.filter(r => r.en !== false).length + " 项）";
  const tip = $("sensTip");
  if (tip) {
    tip.textContent = SENS_DIRTY ? "有改动还没保存" : "";
    tip.style.color = SENS_DIRTY ? "var(--warn)" : "";
  }
  const dc = $("sensCount");
  if (dc && SENS_ENT) dc.textContent = "已同步 " + sensAll().length + " 个 sensor";
}

function sensEdit(i, key, val) {
  if (!SENS[i]) return;
  SENS[i][key] = val;
  SENS_DIRTY = true;
  const tip = $("sensTip");
  if (tip) { tip.textContent = "有改动还没保存"; tip.style.color = "var(--warn)"; }
}
function sensToggle(i) {
  if (!SENS[i]) return;
  SENS[i].en = SENS[i].en === false;
  SENS_DIRTY = true;
  sensRender();
}
function sensDel(i) {
  SENS.splice(i, 1);
  SENS_DIRTY = true;
  sensRender();
}

async function sensSave() {
  const rows = [];
  for (const m of SENS) {
    const n = (m.n || "").trim(), eid = (m.eid || "").trim();
    if (!n || !eid) { toast("有「" + SENS_KINDS[m.k].label + "」没填名字或没选实体"); return; }
    rows.push({ k: m.k, n: n, eid: eid, en: m.en !== false });
  }
  if (rows.filter(r => r.k === "total").length > 1) {
    toast("用电总表只能有一条"); return;
  }
  const names = rows.map(r => r.n);
  const dup = names.filter((x, i) => names.indexOf(x) !== i);
  if (dup.length) { toast("名字重复：" + dup[0]); return; }
  try {
    await api("/api/admin/config", { method: "POST", body: {
      ha_sensor_map: JSON.stringify(rows),
    }});
    SENS_DIRTY = false;
    toast("映射已保存，看板下次刷新就变");
    await loadSensorMap();
  } catch (e) { toast(e.message); }
}

async function sensReset() {
  if (!confirm("恢复成内置默认的 6 位成员 / 1 个总表 / 8 路用电 / 7 路温度？")) return;
  try {
    await api("/api/admin/config", { method: "POST", body: { ha_sensor_map: "" }});
    SENS_DIRTY = false;
    toast("已恢复默认映射");
    await loadSensorMap();
  } catch (e) { toast(e.message); }
}

/* 进页面时：先拿 sensor 实体列表，再拿当前生效映射（含实时值与启用位） */
async function loadSensorMap() {
  const tb = $("sensBody");
  if (!tb) return;
  try { await sensLoadEntities(false); } catch (e) { /* 实体列表可选 */ }
  try {
    const r = await fetch("/api/ha/board", { cache: "no-store" });
    const j = await r.json();
    const d = j.data || {};
    if (!SENS_DIRTY) {
      SENS = (d.sensor_mapping || []).map(m => ({
        k: m.k, n: m.n, eid: m.eid, en: m.en !== false,
        nm: m.nm || m.n, v: m.v || "—", s: m.s || "",
      }));
      sensRender();
    }
    const dc = $("sensCount");
    if (dc) dc.textContent = "已同步 " + sensAll().length + " 个 sensor";
  } catch (e) {
    tb.innerHTML = `<tr><td colspan="6" style="color:#f87171">读取失败：`
      + esc(e.message) + `</td></tr>`;
  }
}

async function testHA() {
  const badge = $("haBadge"), hint = $("haTestHint");
  badge.className = "live-badge off";
  badge.innerHTML = "<i></i>测试中…";
  hint.textContent = "正在连接 HA…";
  const body = {
    base: $("cfgHaBase").value.trim().replace(/\/+$/, ""),
    token: $("cfgHaToken").value.trim()
  };
  try {
    const j = await api("/api/admin/ha/test", { method: "POST", body });
    if (j.ok) {
      badge.className = "live-badge ok";
      badge.innerHTML = "<i></i>已连接";
      hint.textContent = `读取 ${j.entities} 个实体 · 成员 ${j.sample.people} 人 · 温度 ${j.sample.temps} 路 · 总功率 ${j.sample.power_total == null ? "无" : j.sample.power_total + " W"} · 灯 ${j.sample.lights_on} 盏 · 空调 ${j.sample.climates_on} 台 · 电视 ${j.sample.tv_on ? "开" : "关"}`;
      loadHaMap();
      loadSensorMap();
      toast("HA 连接成功");
    } else {
      badge.className = "live-badge err";
      badge.innerHTML = "<i></i>连接失败";
      hint.textContent = j.msg || "连接失败";
      toast(j.msg || "连接失败", 4000);
    }
  } catch (e) {
    badge.className = "live-badge err";
    badge.innerHTML = "<i></i>连接失败";
    hint.textContent = e.message;
    toast(e.message, 4000);
  }
}

function fmtSize(n) {
  n = Number(n) || 0;
  if (n < 1024) return n + " B";
  if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
  if (n < 1073741824) return (n / 1048576).toFixed(1) + " MB";
  return (n / 1073741824).toFixed(2) + " GB";
}

async function scanImages() {
  const btn = $("btnScan");
  btn.disabled = true;
  $("imgScanHint").textContent = "正在扫描 uploads 目录…";
  try {
    const j = await api("/api/admin/images/scan");
    const d = j.data || {};
    const put = (id, v) => {
      const el = $(id);
      el.textContent = v;
      el.classList.remove("ph");
    };
    put("sScan", d.total);
    put("sOrphan", d.orphan);
    put("sSize", fmtSize(d.orphan_bytes));
    put("sKept", d.kept);
    $("btnClean").disabled = !d.orphan;
    $("imgScanHint").textContent = d.orphan
      ? `扫描完成，可清理 ${d.orphan} 个文件`
      : "扫描完成，没有无引用图片";
    toast("扫描完成：" + (d.orphan || 0) + " 个无引用");
  } catch (e) {
    $("imgScanHint").textContent = e.message;
    toast(e.message, 4000);
  } finally {
    btn.disabled = false;
  }
}

async function cleanImages() {
  const n = $("sOrphan").textContent;
  const size = $("sSize").textContent;
  if (!confirm(`即将删除 ${n} 个无引用图片，释放约 ${size} 空间。\n\n删除后无法恢复（清理前会自动打一次数据库快照，但图片本身不进快照）。确定继续？`)) return;
  const btn = $("btnClean");
  btn.disabled = true;
  $("imgScanHint").textContent = "正在清理…";
  try {
    const j = await api("/api/admin/images/clean", { method: "POST" });
    toast(j.msg || "清理完成", 3500);
    $("imgScanHint").textContent = `已删除 ${j.deleted} 个，释放 ${fmtSize(j.freed)}` +
      (j.failed && j.failed.length ? `，${j.failed.length} 个失败` : "");
    await scanImages();
  } catch (e) {
    $("imgScanHint").textContent = e.message;
    toast(e.message, 4000);
    btn.disabled = false;
  }
}

async function loadBotStatus() {
  try {
    const j = await api("/api/admin/bot/status");
    const d = j.data || {};
    const ok = d.active === "active";
    $("botStateHint").innerHTML = ok
      ? '<span style="color:var(--ok)">● 运行中</span>'
      : '<span style="color:var(--danger)">● ' + esc(d.active) + "</span>";

    const ch = d.channel === "wecom" ? "wecom" : "ding";
    const bd = $("bdChannel");
    if (ch === "wecom") {
      bd.className = "live-badge " + (d.wecom_configured ? "ok" : "err");
      bd.innerHTML = "<i></i>企业微信";
      $("chText").textContent = d.wecom_configured
        ? "凭证齐全，等待企微回调（需公网可达）"
        : "凭证不全：CorpID / Secret / Token / AESKey 缺项";
    } else {
      bd.className = "live-badge " + (ok ? "ok" : "err");
      bd.innerHTML = "<i></i>钉钉 StreamBot";
      $("chText").textContent = ok
        ? "长连接已建立，无需公网入口"
        : "服务未运行：" + (d.active || "unknown");
    }

    const hb = $("bdHa");
    hb.className = "live-badge " + (d.ha_configured ? "ok" : "off");
    hb.innerHTML = "<i></i>Home Assistant";
    $("haText").textContent = d.ha_configured
      ? (d.ha_base_url || "") + " · 令牌已配置"
      : "未配置令牌，看板不显示家庭状态";

    $("botStatusText").textContent = (d.last_log || "（暂无日志）").slice(0, 300);
  } catch (e) { toast(e.message); }
}

async function saveSys() {
  const body = {
    board_limit: $("cfgLimit").value,
    refresh_sec: $("cfgRefresh").value,
    cols: $("cfgCols").value,
    theme: $("cfgTheme").value,
    speak_default: $("cfgSpeak").value,
    speak_rate: $("cfgRate").value,
    show_sender: $("cfgShowSender").value,
    show_group: $("cfgShowGroup").value,
    autoscroll: $("cfgAutoScroll").value,
    autoscroll_sec: $("cfgScrollSec").value,
    pin_limit: $("cfgPinLimit").value,
    retention_days: $("cfgRetention").value
  };
  try {
    await api("/api/admin/config", { method: "POST", body });
    await loadConfig();
    toast("设置已保存，看板会在下次轮询生效");
  } catch (e) { toast(e.message); }
}

/* ================= 消息 ================= */
async function loadMessages() {
  const tag = $("fTag").value;
  const q = $("fQ").value.trim();
  const qs = new URLSearchParams({ limit: "100" });
  if (tag) qs.set("tag", tag);
  if (q) qs.set("q", q);
  const j = await api("/api/admin/messages?" + qs.toString());
  MSGS = j.data || [];
  $("msgTotal").textContent = `共 ${j.total} 条 · 常驻 ${MSGS.filter(m => m.pinned).length} 条`;
  renderMsgs();
  syncSel();
}

function renderMsgs() {
  if (!MSGS.length) {
    $("msgRows").innerHTML = '<tr><td colspan="7" class="muted" style="padding:26px">没有符合条件的消息</td></tr>';
    return;
  }
  $("msgRows").innerHTML = MSGS.map(m => {
    const t = TAGS.find(x => x.name === m.tag) || {};
    const content = m.image
      ? `<span class="muted">🖼</span> ${esc((m.content || "图片消息").slice(0, 60))}`
      : esc((m.content || "").slice(0, 90));
    return `<tr class="${m.pinned ? "is-pinned" : ""}" data-id="${m.id}">
      <td><input type="checkbox" class="pick row-pick" data-id="${m.id}" onchange="syncSel()"></td>
      <td class="muted">${m.id}</td>
      <td><span class="tag-name"><span class="swatch" style="background:${esc(t.color || m.color || "#64748b")}"></span>${esc(m.tag)}</span></td>
      <td><span class="who-cell">${avatar(m.sender)}${esc(m.sender || "未署名")}</span></td>
      <td>${content}</td>
      <td class="muted">${fmtTime(m.ts)}</td>
      <td><div class="row-actions">
        <button class="pin-btn ${m.pinned ? "on" : ""}" onclick="togglePin(${m.id}, this)">📌 常驻</button>
        <button class="mini del" onclick="delMsg(${m.id})">删除</button>
      </div></td>
    </tr>`;
  }).join("");
}

function pickBoxes() { return Array.from(document.querySelectorAll(".row-pick")); }
function syncSel() {
  const boxes = pickBoxes();
  const n = boxes.filter(x => x.checked).length;
  $("selN").textContent = n;
  $("bulkbar").classList.toggle("show", n > 0);
  const all = $("pickAll");
  if (all) {
    all.checked = n > 0 && n === boxes.length;
    all.indeterminate = n > 0 && n < boxes.length;
  }
}
function toggleAll(el) { pickBoxes().forEach(x => x.checked = el.checked); syncSel(); }
function selAllRows() { pickBoxes().forEach(x => x.checked = true); syncSel(); }
function clearSel() { pickBoxes().forEach(x => x.checked = false); $("pickAll").checked = false; syncSel(); }

async function togglePin(id, btn) {
  const on = !btn.classList.contains("on");
  try {
    await api(`/api/admin/messages/${id}/pin`, { method: "POST", body: { pinned: on } });
    btn.classList.toggle("on", on);
    btn.closest("tr").classList.toggle("is-pinned", on);
    toast(on ? "已设为常驻，看板顶部会一直显示" : "已取消常驻");
    loadMessages();
  } catch (e) { toast(e.message); }
}

async function delMsg(id) {
  if (!confirm("删除这条消息？")) return;
  try {
    await api("/api/admin/messages/" + id, { method: "DELETE" });
    await loadMessages();
    toast("已删除");
  } catch (e) { toast(e.message); }
}

async function deleteSelected() {
  const ids = pickBoxes().filter(x => x.checked).map(x => parseInt(x.dataset.id, 10));
  if (!ids.length) return;
  if (!confirm(`删除选中的 ${ids.length} 条消息？`)) return;
  try {
    const r = await api("/api/admin/messages/delete", { method: "POST", body: { ids } });
    await loadMessages();
    toast(`已删除 ${r.deleted} 条`);
  } catch (e) { toast(e.message); }
}

async function doCleanup() {
  const days = parseInt($("cleanDays").value, 10) || 30;
  if (!confirm(`删除 ${days} 天前的消息？常驻消息不会被删除。`)) return;
  try {
    const r = await api("/api/admin/messages/cleanup", { method: "POST", body: { days } });
    await loadMessages();
    toast(`已清理 ${r.deleted} 条`);
  } catch (e) { toast(e.message); }
}

/* ================= 设置天气位置（V5 实现 / V6 改名） =================
   位置来源两种：跟 HA（读 HA 的家 + weather 实体）、手动城市（中国天气网代码）。
   保存写 7 个 weather_* 配置；「测试取数」不落库，只回显一次。 */
let LOC_SRC = "ha";

function pickLoc(src) {
  if (src === "ha" && !haEnabled()) {
    toast("HA 接入已停用，只能用「手动指定城市」");
    return;
  }
  LOC_SRC = src;
  const ha = $("pickHa"), city = $("pickCity");
  if (ha) ha.classList.toggle("on", src === "ha");
  if (city) city.classList.toggle("on", src === "city");
  syncHaEnabled();
}

/* 一条文本往往填不满容器，按宽度补足份数，动画 -50% 才能无缝循环 */
function buildTrack(el, one) {
  if (!el) return;
  el.innerHTML = "";
  const mk = () => {
    const s = document.createElement("span");
    s.textContent = one;
    return s;
  };
  el.appendChild(mk());
  const oneW = el.firstChild.getBoundingClientRect().width || 320;
  const boxW = el.parentElement.getBoundingClientRect().width || 600;
  const need = Math.max(2, Math.ceil((boxW * 2) / oneW) + 1);
  for (let i = 1; i < need; i++) el.appendChild(mk());
  if (need % 2) el.appendChild(mk());
  el.style.animationDuration = Math.round((el.scrollWidth / 2) / 26) + "s";
}

/* V6-1：家庭状态接入总开关。
   关闭 → 看板【家庭状态】整卡隐藏（后端 /api/board 下发 ha_enabled=0），
   同时天气位置来源自动落库成 city；重新启用时保持当前来源，不自动切回 HA。 */
function syncHaEnabled() {
  const on = haEnabled();
  const sw = $("haSw"), st = $("haSwState"), master = $("masterSw");
  if (sw) sw.classList.toggle("on", on);
  if (st) {
    st.textContent = on ? "已启用" : "已停用";
    st.classList.toggle("off", !on);
  }
  if (master) master.classList.toggle("off", !on);
  const panel = $("haSrcPanel"), hint = $("haSrcHint");
  if (panel) panel.classList.toggle("dim", !on);
  if (hint) hint.textContent = on
    ? "只读接入 · 供看板展示" : "接入已停用 · 看板不再显示，配置仍保留";

  const ha = $("pickHa"), city = $("pickCity");
  if (ha) ha.classList.toggle("disabled", !on);
  if (!on) {
    LOC_SRC = "city";
    if (ha) ha.classList.remove("on");
    if (city) city.classList.add("on");
  }
  const fld = $("cfgWxEntity") && $("cfgWxEntity").closest(".fld");
  if (fld) fld.classList.toggle("dim", !(on && LOC_SRC === "ha"));
  const link = $("locLink"), txt = $("locLinkTxt");
  if (link) link.classList.toggle("off", !on);
  if (txt) {
    if (!on) {
      txt.textContent = "HA 接入已停用：位置来源已自动切换为「手动指定城市」，"
        + "「跟随 Home Assistant」暂不可选。重新启用后不会自动切回，需要在这里手动选择。";
    } else if (LOC_SRC === "city") {
      txt.textContent = "当前为「手动指定城市」。如需跟随 HA 位置，点上面那张卡切回。";
    } else {
      txt.textContent = "当前 HA 接入已启用，位置来源可二选一。";
    }
  }
}

async function toggleHa() {
  const next = haEnabled() ? "0" : "1";
  const body = { ha_enabled: next };
  // 线上原本没填城市代码：停用后只切 source 会让天气条因取不到城市而消失。
  // 按 HA 所在位置预填上海（可随时在「设置天气位置」改），保证天气不中断。
  let prefill = false;
  if (next === "0" && !(CFG.weather_city_code || "").trim()) {
    body.weather_city_name = "上海市";
    body.weather_city_code = "101020100";
    prefill = true;
  }
  try {
    await api("/api/admin/config", { method: "POST", body });
    await loadConfig();
    if (next === "0") LOC_SRC = "city";
    await loadLoc();
    syncHaEnabled();
    toast(next === "0"
      ? (prefill ? "已停用：家庭状态卡隐藏，天气按上海市（101020100）取数，可在「设置天气位置」修改"
                 : "已停用：家庭状态卡隐藏，天气改为手动指定城市")
      : "已启用：看板家庭状态恢复显示，天气来源保持当前设置");
  } catch (e) { toast(e.message); }
}

async function loadLoc() {
  pickLoc(CFG.weather_source === "city" ? "city" : "ha");
  $("cfgCityName").value = CFG.weather_city_name || "";
  $("cfgCityCode").value = CFG.weather_city_code || "";
  const mins = Math.max(1, Math.round((Number(CFG.weather_interval) || 600) / 60));
  $("cfgWxInterval").value = String(mins);
  const sel = $("cfgWxEntity");
  try {
    const j = await api("/api/admin/weather/loc");
    const ha = (j.data || {}).ha || {};
    const rd = $("locHaRead");
    if (rd) {
      if (ha.error) {
        rd.innerHTML = "<span>" + esc(ha.error) + "</span>";
      } else {
        rd.innerHTML = "<span>现读到</span><b>" + esc(ha.name || "—") + "</b>" +
          "<code>" + esc(String(ha.lat) + ", " + String(ha.lon)) + "</code>" +
          "<span>·</span><span>时区 " + esc(ha.tz || "—") + "</span>";
      }
    }
    const ents = ha.entities || [];
    let html = '<option value="">自动（取第一个 weather.*）</option>';
    ents.forEach(e => {
      const label = esc(String(e.name) + " · " + String(e.state || ""));
      html += '<option value="' + esc(e.eid) + '"' +
        (e.eid === (CFG.weather_ha_entity || "") ? " selected" : "") + ">" + label + "</option>";
    });
    sel.innerHTML = html;
    sel.value = CFG.weather_ha_entity || "";
  } catch (e) { /* HA 读不到也不影响选手动城市 */ }
}

async function saveLoc() {
  if (LOC_SRC === "city" && !$("cfgCityCode").value.trim()) {
    return toast("手动城市要填城市代码");
  }
  const body = {
    weather_source: LOC_SRC,
    weather_ha_entity: $("cfgWxEntity").value,
    weather_city_name: $("cfgCityName").value.trim(),
    weather_city_code: $("cfgCityCode").value.trim(),
    weather_interval: String(Math.max(1, Number($("cfgWxInterval").value) || 10) * 60),
    weather_enabled: haPrefGet("weather_enabled"),
    weather_show_range: haPrefGet("weather_show_range"),
  };
  try {
    await api("/api/admin/config", { method: "POST", body });
    await loadConfig();
    toast("位置已保存，顶部天气下一个刷新周期生效");
  } catch (e) { toast(e.message); }
}

async function testWeather() {
  $("pvText").textContent = "取数中…";
  $("pvSrc").textContent = "—";
  $("pvNote").textContent = "";
  $("wxDemo").style.display = "none";
  const body = {
    weather_source: LOC_SRC,
    weather_ha_entity: $("cfgWxEntity").value,
    weather_city_name: $("cfgCityName").value.trim(),
    weather_city_code: $("cfgCityCode").value.trim(),
    weather_show_range: haPrefGet("weather_show_range"),
  };
  try {
    const j = await api("/api/admin/weather/test", { method: "POST", body });
    if (j.ok) {
      const d = j.data || {};
      $("pvText").textContent = d.text || "—";
      $("pvIco").textContent = d.ico || "🌤️";
      $("pvSrc").textContent = d.src === "ha"
        ? ("Home Assistant · " + (d.entity || "自动"))
        : ("中国天气网 · " + (d.name || ""));
      $("pvNote").textContent = "今日 " + (d.tmin == null ? "?" : d.tmin) +
        " ~ " + (d.tmax == null ? "?" : d.tmax) + "℃";
      buildTrack($("pvTrack"), d.text || "");
      $("wxDemo").style.display = "";
    } else {
      $("pvText").textContent = "取数失败";
      $("pvNote").textContent = j.msg || "";
    }
  } catch (e) { $("pvText").textContent = "取数失败"; $("pvNote").textContent = e.message; }
}

/* ================= 备份 / 恢复 ================= */
async function doBackup() {
  try {
    const r = await fetch("/api/admin/backup", { credentials: "same-origin" });
    if (r.status === 401) { showLogin(); return; }
    if (!r.ok) throw new Error("备份失败");
    const blob = await r.blob();
    const cd = r.headers.get("content-disposition") || "";
    const m = cd.match(/filename="?([^"]+)"?/);
    const name = m ? m[1] : "notify.db";
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 3000);
    toast("已开始下载 " + name);
    loadBackupInfo();
  } catch (e) { toast(e.message); }
}

async function loadBackupInfo() {
  try {
    const j = await api("/api/admin/backup/info");
    const d = j.data;
    const kb = d.db_size > 1048576 ? (d.db_size / 1048576).toFixed(1) + " MB" : Math.round(d.db_size / 1024) + " KB";
    $("bkInfo").innerHTML =
      `库文件 notify.db · <b style="color:var(--text2)">${kb}</b><br>` +
      `消息 ${d.messages} 条 · 图片消息 ${d.image_msgs} 条 · 标签 ${d.tags} 个<br>` +
      `上传目录 ${d.upload_files} 个文件 · 上次备份 ${d.last_backup || "无"}`;
    $("imgInfo").value = `uploads/ · ${d.upload_files} 个文件`;
  } catch (e) { $("bkInfo").textContent = e.message; }
}

let pendingFile = null;
function onPick(input) {
  const f = input.files && input.files[0];
  if (!f) return;
  setPending(f);
}
function onDrop(e) {
  e.preventDefault();
  $("drop").classList.remove("over");
  const f = e.dataTransfer.files && e.dataTransfer.files[0];
  if (!f) return;
  if (!/\.(db|sqlite|sqlite3)$/i.test(f.name)) return toast("只接受 .db / .sqlite 文件");
  setPending(f);
}
function setPending(f) {
  pendingFile = f;
  $("fname").textContent = f.name;
  $("fsize").textContent = (f.size / 1024).toFixed(0) + " KB";
  $("filecard").classList.add("show");
  $("drop").style.display = "none";
}
function clearFile(e) {
  if (e) e.stopPropagation();
  pendingFile = null;
  $("filecard").classList.remove("show");
  $("drop").style.display = "";
  $("fileInput").value = "";
}

async function doRestore() {
  if (!pendingFile) return toast("请先选择要恢复的 .db 文件");
  if (!confirm("恢复会整体覆盖当前所有数据，确定继续？")) return;
  const fd = new FormData();
  fd.append("file", pendingFile);
  try {
    const r = await fetch("/api/admin/restore", { method: "POST", body: fd, credentials: "same-origin" });
    const j = await r.json().catch(() => ({}));
    if (r.status === 401) { showLogin(); return; }
    if (!r.ok) throw new Error(j.detail || "恢复失败");
    toast("恢复完成，正在重新登录…");
    setTimeout(() => location.reload(), 1500);
  } catch (e) { toast(e.message); }
}

/* ================= 启动 ================= */
async function bootData() {
  await loadTags();
  await loadConfig();
  await loadMessages();
  await loadBackupInfo();
  loadBotStatus();
  loadHaMap();
  loadSensorMap();
  loadLoc();
}

async function boot() {
  renderCats(); renderIcons();
  const h = (location.hash || "").replace("#", "");
  if (PAGE_KEYS.includes(h)) switchTab(h);
  try {
    const st = await api("/api/admin/state");
    if (st.need_setup) { showGate("setup"); return; }
    if (!st.authed) { showGate("login"); return; }
    $("app").style.display = "";
    await bootData();
    if (PAGE_KEYS.includes(h)) switchTab(h);
  } catch (e) {
    showGate("login");
  }
}
boot();
