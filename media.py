# -*- coding: utf-8 -*-
"""图片落盘与压缩 —— 钉钉机器人、企微回调共用

压缩时有三件事必须做对，否则压缩本身会把图弄坏：
  1. EXIF 方向：手机竖拍的像素常是横的，靠 Orientation 标记旋转，
     重编码丢 EXIF 后会躺倒 —— 先用 exif_transpose 把方向落到像素上。
  2. 透明通道：convert("RGB") 会丢 alpha，截图圆角/表情包透明区变黑 —— 先铺白底再合成。
  3. 调色板 PNG（P 模式 + transparency）同理。
"""
import io
import os
import time
import secrets
import logging

logger = logging.getLogger("media")

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")


def shrink(raw, max_edge):
    """有 Pillow 就压到最长边 max_edge，没有就原样返回"""
    if not max_edge or int(max_edge) <= 0:
        return raw
    max_edge = int(max_edge)
    try:
        from PIL import Image, ImageOps
    except Exception:
        return raw
    try:
        im = Image.open(io.BytesIO(raw))
        im = ImageOps.exif_transpose(im)
        if max(im.size) <= max_edge:
            return raw
        try:
            rs = Image.Resampling.LANCZOS
        except AttributeError:              # Pillow < 9.1
            rs = Image.LANCZOS
        im.thumbnail((max_edge, max_edge), rs)
        if im.mode in ("RGBA", "LA", "PA") or (
                im.mode == "P" and "transparency" in im.info):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1])
            im = bg
        else:
            im = im.convert("RGB")
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=90, optimize=True)
        return buf.getvalue()
    except Exception as e:
        logger.warning("图片压缩失败，保留原图：%s", e)
        return raw


def guess_ext(content_type, raw):
    """先看 Content-Type，再看文件头魔数"""
    ct = (content_type or "").lower()
    if "png" in ct:
        return ".png"
    if "webp" in ct:
        return ".webp"
    if "jpeg" in ct or "jpg" in ct:
        return ".jpg"
    if "gif" in ct:
        return ".gif"
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return ".webp"
    if raw[:3] == b"GIF":
        return ".gif"
    return ".jpg"


def save_image_bytes(raw, max_edge=1920, content_type=""):
    """压缩后写入 uploads/YYYYMM/，返回可直接入库的相对路径"""
    out = shrink(raw, max_edge)
    # shrink 压过就会重编码成 JPEG（PNG 还会被铺白底），此时扩展名必须跟着变，
    # 否则会出现「.png 后缀里装着 JPEG 字节」，静态服务的 MIME 也跟着错。
    ext = ".jpg" if out is not raw else guess_ext(content_type, raw)
    sub = time.strftime("%Y%m")
    d = os.path.join(UPLOAD_DIR, sub)
    os.makedirs(d, exist_ok=True)
    name = secrets.token_hex(8) + ext
    with open(os.path.join(d, name), "wb") as f:
        f.write(out)
    return "uploads/%s/%s" % (sub, name)
