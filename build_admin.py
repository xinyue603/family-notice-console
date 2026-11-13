# -*- coding: utf-8 -*-
"""用示例页 CSS + 线上 HTML/JS 组装 admin.html"""
import io, os

BASE = os.path.dirname(os.path.abspath(__file__))
PROTO = os.path.join(BASE, "prototype", "admin.html")

src = io.open(PROTO, encoding="utf-8").read()
head = src.split("</style>")[0]          # 到 <style> 内容结束

body = io.open(os.path.join(BASE, "admin_body.html"), encoding="utf-8-sig").read().lstrip()
assert body.startswith("</style>"), body[:40]

out = head + body + "\n"
js = io.open(os.path.join(BASE, "admin.js"), encoding="utf-8").read()
out += "\n<script>\n" + js + "\n</script>\n</body>\n</html>\n"

io.open(os.path.join(BASE, "admin.html"), "w", encoding="utf-8").write(out)
print("admin.html", len(out), "bytes")
