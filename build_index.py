# -*- coding: utf-8 -*-
"""用示例页 CSS + 线上 HTML/JS 组装 index.html"""
import io, os

BASE = os.path.dirname(os.path.abspath(__file__))
PROTO = os.path.join(BASE, "prototype", "dashboard.html")

src = io.open(PROTO, encoding="utf-8").read()
head = src.split("</style>")[0]

EXTRA_CSS = """
  /* ---------- 线上补充 ---------- */
  .pill.bad{color:#fca5a5;border-color:rgba(239,68,68,.3);background:rgba(239,68,68,.1)}
  .pill.bad .dot{background:#ef4444;box-shadow:0 0 0 3px rgba(239,68,68,.16)}
  .card{animation-fill-mode:both}
"""

BODY = """</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="brand">
      <div class="logo">\U0001F3E0</div>
      <div>\u5bb6\u5ead\u901a\u77e5\u4e2d\u63a7\u53f0<small>FAMILY NOTICE CONSOLE</small></div>
    </div>
    <div class="clock"><b id="now">--:--</b><span id="date"></span></div>
    <span class="pill" id="conn"><span class="dot"></span><span id="connText">\u8fde\u63a5\u4e2d</span></span>
    <button class="icon-btn on" id="voice" title="\u8bed\u97f3\u64ad\u62a5">\U0001F50A</button>
    <button class="icon-btn" id="theme" title="\u5207\u6362\u4e3b\u9898">\U0001F319</button>
    <a class="icon-btn" href="/admin" title="\u7ba1\u7406\u540e\u53f0">\u2699\ufe0f</a>
  </header>

  <div class="statusbar">
    <span class="chip" id="chipTotal">\u5171 0 \u6761</span>
    <span class="chip" id="chipPin">\U0001F4CC \u5e38\u9a7b 0 \u6761</span>
    <span class="chip" id="chipUpdated">\u6682\u65e0\u6d88\u606f</span>
    <span class="chip" id="chipSender">\u53d1\u9001\u4eba 0 \u4f4d</span>
    <span class="chip r" id="chipTip">\u81ea\u52a8\u5237\u65b0</span>
  </div>

  <div id="board"></div>
</div>

<div class="lb" id="lb"><span class="close">\u2715</span><img id="lbimg" alt=""></div>
"""

out = head + EXTRA_CSS + BODY
js = io.open(os.path.join(BASE, "board.js"), encoding="utf-8").read()
out += "\n<script>\n" + js + "\n</script>\n</body>\n</html>\n"

io.open(os.path.join(BASE, "index.html"), "w", encoding="utf-8").write(out)
print("index.html", len(out), "bytes")
