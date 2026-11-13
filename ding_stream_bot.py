#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
钉钉 Stream 机器人 → 家庭通知中控台
- 支持 文本 / 图片 / 富文本（图文混排）
- 标签兼容：#标签:内容、#标签：内容、#标签 内容
- 无标签消息照常推送（不再丢弃）
- 携带发送人昵称、员工ID、群名
- 凭证、去重窗口、标签长度、图片压缩上限 全部从数据库配置读取，改完点后台「保存并重启」
"""
import os
import re
import time
import sqlite3
import logging
import hashlib

import requests
import dingtalk_stream

from media import guess_ext, shrink, save_image_bytes   # 图片压缩与落盘（与企微共用）

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 数据目录与 main.py 保持一致，支持 NOTIFY_DATA_DIR 环境变量（Docker 持久卷）
DATA_DIR = os.environ.get("NOTIFY_DATA_DIR") or BASE_DIR
DB_PATH = os.path.join(DATA_DIR, "notify.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
API_URL = "http://127.0.0.1:8002/api/message/add"

logger = logging.getLogger("bot")


# ============================================================
# 配置读取（每次收到消息都读，后台改完即时生效；凭证除外需重启）
# ============================================================
def read_config():
    cfg = {"bot_app_key": "", "bot_app_secret": "", "dedup_window": "60",
           "tag_max_len": "12", "image_max_edge": "1920"}
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % DB_PATH, uri=True, timeout=5)
        for k, v in conn.execute("SELECT key,value FROM config"):
            cfg[k] = v
        conn.close()
    except Exception as e:
        logger.warning("读取配置失败，使用默认值：%s", e)
    return cfg


def cfg_int(cfg, key, default):
    try:
        return int(float(cfg.get(key, default)))
    except Exception:
        return default


# ============================================================
# 标签解析
# ============================================================
AT_RE = re.compile(r"^\s*@[^\s@]{1,40}\s*")


def strip_at(text):
    """去掉开头的 @机器人 提及。

    钉钉会把 @机器人 的文本一并放进 text.content，形如「@家庭通知 #作业：xxx」，
    不剥离会导致标签解析失效（整条被当正文）。这里只清理开头连续的 @ 串，
    正文中间或末尾的 @（如 @示例成员 记得买菜）保持不动。
    """
    s = text or ""
    for _ in range(4):          # 最多剥离 4 个连续的 @
        m = AT_RE.match(s)
        if not m:
            break
        s = s[m.end():]
    return s.lstrip()


def parse_tag(text, max_len=12):
    """返回 (tag, content)。支持 #标签:内容 / #标签：内容 / #标签 内容"""
    s = (text or "").strip()
    if not s.startswith("#"):
        return "普通通知", s

    rest = s[1:].lstrip()
    idx, found = len(rest), False
    for i, ch in enumerate(rest):
        if ch in ":：" or ch.isspace():
            idx, found = i, True
            break

    name = rest[:idx].strip()
    body = rest[idx + 1:].strip() if found else ""

    if not name or len(name) > max_len:
        return "普通通知", s
    return name, body


# ============================================================
# 图片处理：统一走 media.py（与企微回调共用同一套压缩逻辑）
# ============================================================


# ============================================================
# 机器人
# ============================================================
class BotHandler(dingtalk_stream.ChatbotHandler):
    def __init__(self, logger_=None):
        super().__init__()
        if logger_:
            self.logger = logger_
        self.seen = {}

    def _dedup(self, key, window):
        now = time.time()
        self.seen = {k: v for k, v in self.seen.items() if now - v < window}
        if key in self.seen:
            return True
        self.seen[key] = now
        return False

    def _download(self, download_code, max_edge):
        try:
            url = self.get_image_download_url(download_code)
            if not url:
                self.logger.error("获取图片下载地址失败")
                return None
            r = requests.get(url, timeout=30)
            if r.status_code != 200:
                self.logger.error("下载图片失败 HTTP %s", r.status_code)
                return None
            return save_image_bytes(r.content, max_edge)
        except Exception as e:
            self.logger.error("图片处理异常：%s", e)
            return None

    async def process(self, callback: dingtalk_stream.CallbackMessage):
        data = callback.data or {}
        cfg = read_config()
        max_edge = cfg_int(cfg, "image_max_edge", 1920)
        max_len = cfg_int(cfg, "tag_max_len", 12)
        window = cfg_int(cfg, "dedup_window", 60)

        msg_id = data.get("msgId") or ""
        mtype = data.get("msgtype") or ("text" if "text" in data else "unknown")

        # ---- 抽出文本与图片 ----
        text = ""
        image_paths = []

        if mtype == "text":
            text = (data.get("text") or {}).get("content", "") or ""
        elif mtype == "picture":
            code = (data.get("content") or {}).get("downloadCode")
            if code:
                p = self._download(code, max_edge)
                if p:
                    image_paths.append(p)
        elif mtype == "richText":
            items = (data.get("content") or {}).get("richText") or []
            texts = []
            for it in items:
                if "text" in it:
                    texts.append(it["text"])
                elif "downloadCode" in it:
                    p = self._download(it["downloadCode"], max_edge)
                    if p:
                        image_paths.append(p)
            text = "\n".join(texts)

        text = strip_at(text.strip())

        dedup_key = msg_id or hashlib.sha1(
            (text + "|" + (image_paths[0] if image_paths else "")).encode("utf-8")).hexdigest()
        if self._dedup(dedup_key, window):
            self.logger.info("重复消息跳过：%s", text[:20])
            return (0, "ok")

        # 只有 @机器人 没有任何内容与图片，不入库
        if not text and not image_paths:
            self.logger.info("空消息（仅 @机器人），忽略")
            return (0, "ok")

        tag, content = parse_tag(text, max_len)
        if not content and not image_paths:
            # #标签 后面什么都没有，退回成正文，避免丢消息
            tag, content = "普通通知", text

        sender = (data.get("senderNick") or "").strip()
        sender_id = (data.get("senderStaffId") or data.get("senderId") or "")
        group = (data.get("conversationTitle") or "").strip()

        create_at = data.get("createAt")
        try:
            ts = int(int(create_at) / 1000) if create_at else int(time.time())
        except Exception:
            ts = int(time.time())

        payload = {
            "content": content,
            "tag": tag,
            "sender": sender,
            "sender_id": str(sender_id),
            "group": group,
            "image": image_paths[0] if image_paths else "",
            "ts": ts,
        }
        # 多图：第一张随主消息，其余拆成追加消息（保持顺序）
        try:
            res = requests.post(API_URL, json=payload, timeout=8)
            self.logger.info("推送成功 tag=%s sender=%s images=%d -> %s",
                             tag, sender or "-", len(image_paths), res.text[:80])
            for p in image_paths[1:]:
                extra = dict(payload)
                extra["content"] = ""
                extra["image"] = p
                extra["ts"] = ts + 1
                requests.post(API_URL, json=extra, timeout=8)
        except Exception as e:
            self.logger.error("推送失败：%s", e)

        return (0, "ok")


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    cfg = read_config()

    # 渠道由后台「消息接入方式」决定。企微走 HTTP 回调，由后端进程接管，
    # 这里保持进程存活但不连钉钉，避免 systemd 反复重启。
    channel = (cfg.get("im_channel") or "ding").strip()
    if channel != "ding":
        logger.info("当前接入渠道为 %s，钉钉长连接不启动；"
                    "企微消息由后端 /wecom/callback 接收", channel)
        while True:
            time.sleep(3600)

    app_key = cfg.get("bot_app_key") or ""
    app_secret = cfg.get("bot_app_secret") or ""
    if not app_key or not app_secret:
        logger.error("数据库里没有 APP_KEY / APP_SECRET，请在管理后台填写后重启")
        raise SystemExit(1)
    logger.info("启动机器人 app_key=%s***", app_key[:8])

    credential = dingtalk_stream.Credential(app_key, app_secret)
    client = dingtalk_stream.DingTalkStreamClient(credential)
    client.register_callback_handler(dingtalk_stream.chatbot.ChatbotMessage.TOPIC,
                                     BotHandler(logger))
    client.start_forever()


if __name__ == "__main__":
    main()
