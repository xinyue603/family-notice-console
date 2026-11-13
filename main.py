#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
家庭通知中控台 - 后端
- 看板数据接口（公开）：/api/board、/api/message/list
- 机器人推送接口：/api/message/add
- 管理后台接口（需登录）：标签 / 配置 / 消息 / 备份恢复 / 机器人重启
运行：venv/bin/python main.py  （uvicorn 0.0.0.0:8002）
"""
import os
import io
import re
import time
import json
import hmac
import shutil
import base64
import struct
import sqlite3
import secrets
import hashlib
import tempfile
import subprocess
import urllib.request
import urllib.parse
import urllib.error
from contextlib import contextmanager
from datetime import datetime

from fastapi import (FastAPI, Request, Response, HTTPException, Depends,
                     UploadFile, File, Body, Query, BackgroundTasks)
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from media import save_image_bytes

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 数据目录可经环境变量覆盖，便于 Docker 挂载持久卷（默认与代码同目录）
DATA_DIR = os.environ.get("NOTIFY_DATA_DIR") or BASE_DIR
DB_PATH = os.path.join(DATA_DIR, "notify.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
MAX_UPLOAD = 50 * 1024 * 1024

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)

app = FastAPI(title="家庭通知中控台", docs_url=None, redoc_url=None)

# ============================================================
# 数据库
# ============================================================
MESSAGE_EXTRA_COLS = {
    "sender_name": "TEXT",
    "sender_id": "TEXT",
    "conversation_title": "TEXT",
    "image": "TEXT",
    "pinned": "INTEGER DEFAULT 0",
    "pinned_at": "INTEGER",
}

DEFAULT_TAGS = [
    ("紧急通知", "🚨", "#ef4444", 1, 1),
    ("作业",     "📚", "#3b82f6", 1, 2),
    ("今日菜单", "🍲", "#10b981", 1, 3),
    ("采购",     "🛒", "#a855f7", 1, 4),
    ("日程",     "📅", "#f59e0b", 1, 5),
    ("普通通知", "💬", "#64748b", 1, 99),   # V3：兜底标签默认也播报（原先为 0，导致无标签消息静音）
]

CONFIG_DEFAULTS = {
    "bot_app_key": "",
    "bot_app_secret": "",
    "dedup_window": "60",
    "tag_max_len": "12",
    "image_max_edge": "1920",
    "board_limit": "20",
    "refresh_sec": "3",
    "theme": "dark",
    "speak_default": "1",
    "speak_rate": "1.05",
    "show_sender": "1",
    "show_group": "0",
    "cols": "auto",
    "autoscroll": "0",
    "autoscroll_sec": "30",
    "pin_limit": "5",
    "retention_days": "0",
    # 机器人首次启动沿用旧值，改为可在后台修改
    "bot_seeded": "0",
    # ---------- V3：消息接入方式 ----------
    "im_channel": "ding",              # ding | wecom
    "wecom_corp_id": "",
    "wecom_agent_id": "",
    "wecom_secret": "",
    "wecom_token": "",
    "wecom_aes_key": "",
    # ---------- V3：Home Assistant ----------
    "ha_base_url": "http://homeassistant.local:8123",  # 示例地址，请改为你的 Home Assistant 实际地址
    "ha_token": "",
    "ha_interval": "30",
    "ha_enabled": "1",                # V6：看板「家庭状态」模块总开关
    "ha_show_offline": "1",            # 看板是否显示外出成员
    "ha_show_zero_power": "1",         # 看板是否显示 0 W 分路
    # ---------- V4：已开启设备三类 --------
    "ha_show_lights": "1",             # 看板是否显示开着的灯（14 盏白名单）
    "ha_show_climates": "1",           # 看板是否显示开着的空调（5 台白名单）
    "ha_show_tv": "1",                 # 看板是否显示电视（开着才显示）
    # 实体映射表（JSON；空串 = 用内置默认）
    "ha_lights_map": "",
    "ha_climates_map": "",
    "ha_tv_map": "",
    # ---------- V7：成员 / 用电 / 温度 三组 sensor 映射 ----------
    # JSON 数组 [{k,n,eid,en}]；空串 = 用 HA_PEOPLE / HA_POWER_* / HA_TEMPS 内置默认
    "ha_sensor_map": "",
    # ---------- V5：看板顶部天气 ----------
    "weather_enabled": "1",            # 顶部那条天气是否显示
    "weather_source": "ha",            # ha = 跟 HA 走；city = 中国天气网城市
    "weather_ha_entity": "",           # 空 = 自动取第一个 weather.*
    "weather_city_name": "",           # 手动城市名（留空则用接口返回的 cityInfo.city）
    "weather_city_code": "",           # 中国天气网城市代码，如 101020100（上海）
    "weather_interval": "600",         # 取数缓存秒数
    "weather_show_range": "1",         # 是否显示今日温度范围
}

# 需要掩码回显、且留空表示不修改的敏感项
SECRET_CONFIG = ("bot_app_secret", "ha_token", "wecom_secret", "wecom_aes_key")

# 旧版硬编码凭证占位（仅用于首次迁移播种示例）。
# 发布版不含任何真实密钥；请在管理后台填写你自己的钉钉 AppKey / AppSecret。
LEGACY_APP_KEY = "YOUR_DINGTALK_APP_KEY"
LEGACY_APP_SECRET = "YOUR_DINGTALK_APP_SECRET"


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
    except Exception:
        pass
    return conn


@contextmanager
def db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def table_cols(conn, table):
    try:
        return {r["name"] for r in conn.execute("PRAGMA table_info(%s)" % table)}
    except Exception:
        return set()


def init_db():
    with db() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL DEFAULT '',
                tag TEXT DEFAULT '普通通知',
                create_time INTEGER,
                is_expired INTEGER DEFAULT 0
            )""")
        cols = table_cols(c, "messages")
        for name, typ in MESSAGE_EXTRA_COLS.items():
            if name not in cols:
                c.execute("ALTER TABLE messages ADD COLUMN %s %s" % (name, typ))

        c.execute("""
            CREATE TABLE IF NOT EXISTS tags (
                name  TEXT PRIMARY KEY,
                emoji TEXT DEFAULT '',
                color TEXT DEFAULT '#64748b',
                speak INTEGER DEFAULT 1,
                sort  INTEGER DEFAULT 0
            )""")

        c.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key   TEXT PRIMARY KEY,
                value TEXT
            )""")

        c.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                token   TEXT PRIMARY KEY,
                created INTEGER,
                expires INTEGER,
                ua      TEXT
            )""")

        # 默认标签（仅首次）
        if c.execute("SELECT COUNT(*) n FROM tags").fetchone()["n"] == 0:
            c.executemany("INSERT INTO tags(name,emoji,color,speak,sort) VALUES (?,?,?,?,?)",
                          DEFAULT_TAGS)

        # 默认配置
        for k, v in CONFIG_DEFAULTS.items():
            c.execute("INSERT OR IGNORE INTO config(key,value) VALUES (?,?)", (k, v))

        # 首次迁移：把旧硬编码凭证写进配置，保证机器人不断线
        row = c.execute("SELECT value FROM config WHERE key='bot_seeded'").fetchone()
        if row and row["value"] != "1":
            c.execute("UPDATE config SET value=? WHERE key='bot_app_key'", (LEGACY_APP_KEY,))
            c.execute("UPDATE config SET value=? WHERE key='bot_app_secret'", (LEGACY_APP_SECRET,))
            c.execute("UPDATE config SET value='1' WHERE key='bot_seeded'")

        # 清理过期会话
        c.execute("DELETE FROM sessions WHERE expires < ?", (int(time.time()),))

        # V3 一次性迁移：兜底标签「普通通知」原先默认静音，导致不带 # 的消息
        # 能进看板但不播报。改为默认播报，之后可在标签列表里随时关掉。
        row = c.execute("SELECT value FROM config WHERE key='speak_migrated'").fetchone()
        if not (row and row["value"] == "1"):
            c.execute("UPDATE tags SET speak=1 WHERE name='普通通知' AND speak=0")
            c.execute("INSERT INTO config(key,value) VALUES ('speak_migrated','1') "
                      "ON CONFLICT(key) DO UPDATE SET value='1'")


# ============================================================
# 配置 / 标签
# ============================================================
def get_config():
    with db() as c:
        rows = c.execute("SELECT key,value FROM config").fetchall()
    cfg = dict(CONFIG_DEFAULTS)
    cfg.update({r["key"]: r["value"] for r in rows})
    return cfg


def set_config_items(items: dict):
    with db() as c:
        for k, v in items.items():
            c.execute("INSERT INTO config(key,value) VALUES (?,?) "
                      "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, str(v)))


def public_config(cfg=None):
    cfg = cfg or get_config()
    def i(k, d=0):
        try:
            return int(cfg.get(k, d))
        except Exception:
            return d
    def f(k, d=1.0):
        try:
            return float(cfg.get(k, d))
        except Exception:
            return d
    cols = str(cfg.get("cols", "auto"))
    return {
        "board_limit": i("board_limit", 20),
        "refresh_sec": max(1, i("refresh_sec", 3)),
        "theme": cfg.get("theme", "dark"),
        "speak_default": i("speak_default", 1),
        "speak_rate": f("speak_rate", 1.05),
        "show_sender": i("show_sender", 1),
        "show_group": i("show_group", 0),
        "cols": cols if cols in ("auto", "1", "2") else "auto",
        "autoscroll": i("autoscroll", 0),
        "autoscroll_sec": max(5, i("autoscroll_sec", 30)),
        "pin_limit": i("pin_limit", 5),
        "tag_max_len": i("tag_max_len", 12),
        "ha_enabled": i("ha_enabled", 1),   # V6：0 = 看板隐藏「家庭状态」卡
    }


def list_tags():
    with db() as c:
        rows = c.execute("SELECT name,emoji,color,speak,sort FROM tags ORDER BY sort, name").fetchall()
    return [dict(r) for r in rows]


def tag_map():
    return {t["name"]: t for t in list_tags()}


# ============================================================
# 鉴权
# ============================================================
PBKDF2_ITER = 200_000
_LOGIN_FAILS = {}


def hash_password(pwd):
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pwd.encode("utf-8"), salt, PBKDF2_ITER)
    return "pbkdf2_sha256$%d$%s$%s" % (PBKDF2_ITER, salt.hex(), dk.hex())


def verify_password(pwd, stored):
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", pwd.encode("utf-8"),
                                 bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def has_password(cfg=None):
    cfg = cfg or get_config()
    return bool(cfg.get("admin_pwd"))


def new_session(ua, days):
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    ttl = days * 86400 if days else 86400
    with db() as c:
        c.execute("DELETE FROM sessions WHERE expires < ?", (now,))
        c.execute("INSERT INTO sessions(token,created,expires,ua) VALUES (?,?,?,?)",
                  (token, now, now + ttl, (ua or "")[:200]))
    return token


def current_admin(request: Request):
    token = request.cookies.get("sid")
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    with db() as c:
        row = c.execute("SELECT token,expires FROM sessions WHERE token=?", (token,)).fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="未登录")
        if int(row["expires"]) < int(time.time()):
            c.execute("DELETE FROM sessions WHERE token=?", (token,))
            raise HTTPException(status_code=401, detail="登录已过期")
    return token


def client_ip(request: Request):
    try:
        return request.client.host or "?"
    except Exception:
        return "?"


# ============================================================
# 数据模型
# ============================================================
class MsgIn(BaseModel):
    content: str = ""
    tag: str = "普通通知"
    sender: str | None = None
    sender_id: str | None = None
    group: str | None = None
    image: str | None = None
    ts: int | None = None


class LoginIn(BaseModel):
    password: str
    remember: bool = True


class PwdIn(BaseModel):
    old: str = ""
    new: str


class TagIn(BaseModel):
    name: str
    emoji: str = ""
    color: str = "#64748b"
    speak: bool = True
    sort: int = 0


class PinIn(BaseModel):
    pinned: bool


class IdsIn(BaseModel):
    ids: list[int] = []


class CleanupIn(BaseModel):
    days: int = 30


class PwdChangeIn(BaseModel):
    old: str
    new: str


# ============================================================
# 公开接口
# ============================================================
def _row_to_msg(r, tags):
    t = tags.get(r["tag"] or "普通通知") or tags.get("普通通知") or {}
    return {
        "id": r["id"],
        "content": r["content"] or "",
        "tag": r["tag"] or "普通通知",
        "ts": r["create_time"] or 0,
        "sender": (r["sender_name"] if "sender_name" in r.keys() else None) or "",
        "sender_id": (r["sender_id"] if "sender_id" in r.keys() else None) or "",
        "group": (r["conversation_title"] if "conversation_title" in r.keys() else None) or "",
        "image": (r["image"] if "image" in r.keys() else None) or "",
        "pinned": int((r["pinned"] if "pinned" in r.keys() else 0) or 0),
        "pinned_at": int((r["pinned_at"] if "pinned_at" in r.keys() else 0) or 0),
        "color": t.get("color", "#64748b"),
    }


SELECT_COLS = ("id,content,tag,create_time,sender_name,sender_id,conversation_title,"
               "image,pinned,pinned_at")


@app.get("/api/board")
def api_board():
    cfg = get_config()
    pc = public_config(cfg)
    tags = list_tags()
    tmap = {t["name"]: t for t in tags}
    limit = int(pc["board_limit"])
    with db() as c:
        rows = c.execute("SELECT %s FROM messages WHERE COALESCE(pinned,0)=0 "
                         "AND (COALESCE(content,'')<>'' OR COALESCE(image,'')<>'') "
                         "ORDER BY create_time DESC, id DESC LIMIT ?" % SELECT_COLS,
                         (limit,)).fetchall()
        pinned = c.execute("SELECT %s FROM messages WHERE COALESCE(pinned,0)=1 "
                           "AND (COALESCE(content,'')<>'' OR COALESCE(image,'')<>'') "
                           "ORDER BY pinned_at DESC, id DESC LIMIT 20" % SELECT_COLS).fetchall()
    return {
        "code": 200,
        "server_time": int(time.time()),
        "config": pc,
        "tags": tags,
        "weather": weather_public(),
        "data": [_row_to_msg(r, tmap) for r in rows],
        "pinned": [_row_to_msg(r, tmap) for r in pinned],
    }


@app.get("/api/message/list")
def api_message_list(limit: int = 20):
    """兼容旧接口"""
    cfg = get_config()
    limit = max(1, min(200, limit))
    tags = tag_map()
    with db() as c:
        rows = c.execute("SELECT %s FROM messages ORDER BY id DESC LIMIT ?" % SELECT_COLS,
                         (limit,)).fetchall()
    return {"code": 200, "data": [_row_to_msg(r, tags) for r in rows],
            "config": public_config(cfg), "tags": list_tags()}


@app.post("/api/message/add")
def api_message_add(item: MsgIn):
    content = (item.content or "").strip()
    image = (item.image or "").strip()
    if not content and not image:
        return {"code": 400, "msg": "content 与 image 不能同时为空"}

    cfg = get_config()
    max_len = 0
    try:
        max_len = int(cfg.get("tag_max_len", 12))
    except Exception:
        max_len = 12
    tag = (item.tag or "").strip() or "普通通知"
    if max_len and len(tag) > max_len:
        tag = "普通通知"

    now = int(item.ts or time.time())
    with db() as c:
        cur = c.execute(
            "INSERT INTO messages(content,tag,create_time,is_expired,sender_name,sender_id,"
            "conversation_title,image,pinned) VALUES (?,?,?,0,?,?,?,?,0)",
            (content, tag, now, (item.sender or "")[:64],
             (item.sender_id or "")[:64], (item.group or "")[:128], image))
        new_id = cur.lastrowid
    return {"code": 200, "msg": "ok", "id": new_id}


@app.get("/api/health")
def api_health():
    return {"code": 200, "ok": True, "ts": int(time.time())}


# ============================================================
# Home Assistant 代理
# 看板不直接连 HA，由后端统一取数并缓存：
#   1. 令牌只存在服务端，不下发前端
#   2. 多块看板共享一次拉取，避免 N 倍放大 HA 负载
# ============================================================
# 成员在线状态示例（内置默认）。实际部署请在后台「成员与传感器映射」中
# 替换为你自己的 Home Assistant 实体；以下均为通用示例，不含任何真实信息。
HA_PEOPLE = [
    ("成员1",  "sensor.example_person_1_online"),
    ("成员2",  "sensor.example_person_2_online"),
    ("成员3",  "sensor.example_person_3_online"),
    ("成员4",  "sensor.example_person_4_online"),
    ("成员5",  "sensor.example_person_5_online"),
    ("成员6",  "sensor.example_person_6_online"),
]

HA_POWER_TOTAL = "sensor.example_power_total"
HA_POWER_ITEMS = [
    ("分路1",  "sensor.example_power_1"),
    ("分路2",  "sensor.example_power_2"),
    ("分路3",  "sensor.example_power_3"),
    ("分路4",  "sensor.example_power_4"),
    ("分路5",  "sensor.example_power_5"),
    ("分路6",  "sensor.example_power_6"),
    ("分路7",  "sensor.example_power_7"),
    ("分路8",  "sensor.example_power_8"),
]

HA_TEMPS = [
    ("房间1",  "sensor.example_temp_1"),
    ("房间2",  "sensor.example_temp_2"),
    ("房间3",  "sensor.example_temp_3"),
    ("房间4",  "sensor.example_temp_4"),
    ("房间5",  "sensor.example_temp_5"),
    ("房间6",  "sensor.example_temp_6"),
    ("房间7",  "sensor.example_temp_7"),
]

# ── V7：上面三组只是「内置默认」────────────────────────────────────────
# 实际用哪张表由 ha_sensor_map 配置决定，后台「成员与传感器映射」面板可改；
# 配置为空串才回落到这里，所以老部署不改代码也能直接拿到原来的 22 行。
HA_SENSOR_KINDS = ("people", "total", "power", "temp")
HA_SENSOR_TOTAL_NAME = "示例总电表"
HA_SENSOR_MAP_KEY = "ha_sensor_map"

# ── V4：开着的灯 / 空调 / 电视，按名字白名单取 ──────────────────────────
# 注意：这 14 盏灯里 10 盏的真实开关是米家墙壁开关的继电器
# （switch.*_on_p_2_1），light.*_indicator_light 只是面板上的指示灯，
# 与灯本身不同步，不能拿来判断「灯开着没有」。
HA_LIGHTS = [
    ("示例灯1",   "switch.example_light_1"),
    ("示例灯2",   "switch.example_light_2"),
    ("示例灯3",   "switch.example_light_3"),
    ("示例灯4",   "switch.example_light_4"),
    ("示例灯5",   "light.example_light_5"),
    ("示例灯6",   "light.example_light_6"),
    ("示例灯7",   "switch.example_light_7"),
    ("示例灯8",   "switch.example_light_8"),
    ("示例灯9",   "switch.example_light_9"),
    ("示例灯10",  "light.example_light_10"),
    ("示例灯11",  "switch.example_light_11"),
    ("示例灯12",  "switch.example_light_12"),
    ("示例灯13",  "switch.example_light_13"),
    ("示例灯14",  "switch.example_light_14"),
]

HA_CLIMATES = [
    ("示例空调1",  "climate.example_ac_1"),
    ("示例空调2",  "climate.example_ac_2"),
    ("示例空调3",  "climate.example_ac_3"),
    ("示例空调4",  "climate.example_ac_4"),
    ("示例空调5",  "climate.example_ac_5"),
]

HA_TV = ("示例电视", "media_player.example_tv")

# 这些状态一律视为「没开」，不进看板
HA_OFF_STATES = {"off", "standby", "unavailable", "unknown", "", "none"}

# 「设备映射」下拉里能选的域
HA_DOMAINS = {"light": "灯", "switch": "开关", "climate": "空调", "media_player": "播放器"}

# 上面三张表只是「内置默认」。实际用哪张表由配置决定，后台「设备映射」
# 面板可以改，存成 JSON；配置里没配过（空串）才回落到这里。
HA_MAP_KEYS = {
    "lights": "ha_lights_map",
    "climates": "ha_climates_map",
    "tv": "ha_tv_map",
}


def _parse_pairs(raw, default, with_en=False):
    """把配置里的 JSON 解析成 [(名字, 实体)]；解析不了就回落到默认

    V6：with_en=True 时每项多带一个「是否启用」，旧数据里没这个字段一律视为启用。
    """
    if not raw or not str(raw).strip():
        return [(n, e, True) if with_en else (n, e) for n, e in default]
    try:
        arr = json.loads(raw)
    except Exception:
        return [(n, e, True) if with_en else (n, e) for n, e in default]
    if not isinstance(arr, list):
        return [(n, e, True) if with_en else (n, e) for n, e in default]
    out, seen = [], set()
    for it in arr:
        if not isinstance(it, dict):
            continue
        n = str(it.get("n") or "").strip()
        e = str(it.get("eid") or "").strip()
        if n and e and e not in seen:
            seen.add(e)
            en = it.get("en", True)
            if isinstance(en, str):
                en = en.strip().lower() not in ("0", "false", "off", "no", "")
            else:
                en = bool(en)
            out.append((n, e, en) if with_en else (n, e))
    return out          # 允许存成空数组：那就是「一盏都不要」


def ha_maps(cfg=None, with_en=False):
    """读当前生效的三张映射表 → (lights, climates, tv)

    tv 为空时返回 None，看板就不显示电视那一项。
    """
    cfg = cfg if cfg is not None else get_config()
    lights = _parse_pairs(cfg.get(HA_MAP_KEYS["lights"]), HA_LIGHTS, with_en)
    climates = _parse_pairs(cfg.get(HA_MAP_KEYS["climates"]), HA_CLIMATES, with_en)
    tv_list = _parse_pairs(cfg.get(HA_MAP_KEYS["tv"]), [HA_TV], with_en)
    return lights, climates, (tv_list[0] if tv_list else None)

HVAC_MODE_CN = {"cool": "制冷", "heat": "制热", "dry": "除湿",
                "fan_only": "送风", "auto": "自动", "off": "关闭"}

_HA_CACHE = {"ts": 0.0, "states": None}


def _ha_num(state):
    """把 HA 的 state 转成 float；unavailable/unknown/空 一律返回 None"""
    if state is None:
        return None
    s = str(state).strip()
    if not s or s.lower() in ("unavailable", "unknown", "none"):
        return None
    try:
        return float(s)
    except Exception:
        return None


# ============================================================
# V7：成员 / 用电 / 温度 映射表（后台可维护）
# ============================================================
def ha_sensor_defaults():
    """把三组内置常量摊平成统一的映射行（22 行）"""
    rows = [{"k": "people", "n": n, "eid": e, "en": True} for n, e in HA_PEOPLE]
    rows.append({"k": "total", "n": HA_SENSOR_TOTAL_NAME,
                 "eid": HA_POWER_TOTAL, "en": True})
    rows += [{"k": "power", "n": n, "eid": e, "en": True} for n, e in HA_POWER_ITEMS]
    rows += [{"k": "temp", "n": n, "eid": e, "en": True} for n, e in HA_TEMPS]
    return rows


def ha_sensor_rows(cfg=None):
    """读当前生效的 sensor 映射 → [{k,n,eid,en}]

    空串 / 坏 JSON → 内置默认；[] 是合法的「一组都不要」。
    后端兜底：总表只留第一条、entity_id 去重、不认识的类型丢掉。
    """
    cfg = cfg if cfg is not None else get_config()
    raw = str(cfg.get(HA_SENSOR_MAP_KEY) or "").strip()
    if not raw:
        return ha_sensor_defaults()
    try:
        arr = json.loads(raw)
    except Exception:
        return ha_sensor_defaults()
    if not isinstance(arr, list):
        return ha_sensor_defaults()
    out, seen, has_total = [], set(), False
    for it in arr:
        if not isinstance(it, dict):
            continue
        k = str(it.get("k") or "").strip()
        n = str(it.get("n") or "").strip()
        e = str(it.get("eid") or "").strip()
        if k not in HA_SENSOR_KINDS or not n or not e or e in seen:
            continue
        if k == "total":
            if has_total:
                continue
            has_total = True
        en = it.get("en", True)
        if isinstance(en, str):
            en = en.strip().lower() not in ("0", "false", "off", "no", "")
        else:
            en = bool(en)
        seen.add(e)
        out.append({"k": k, "n": n, "eid": e, "en": en})
    return out


def _sensor_guess_kind(state, unit, eid=""):
    """给 sensor 猜个类型，只用于实体搜索下拉的展示，不参与取数"""
    u, s = str(unit or "").strip().lower(), str(state or "")
    if "online_status" in eid or "在线" in s or "离线" in s:
        return "people"
    if "°" in u or u in ("c", "ºc"):
        return "temp"
    if u in ("w", "kw"):
        return "power"
    return "other"


def _sensor_view(k, state, unit=""):
    """把 HA 的 state 翻成后台表格「当前值」那一列"""
    s = "" if state is None else str(state).strip()
    u = str(unit or "").strip().replace("°C", "℃")
    if k == "people":
        if "在线" in s:
            return "在线"
        if "离线" in s:
            return "离线"
        return s or "—"
    if not s or s.lower() in ("unavailable", "unknown", "none"):
        return "—"
    n = _ha_num(s)
    if n is None:
        return s
    txt = "%.1f" % n
    if k == "temp":
        return txt + (u or "℃")
    if k in ("power", "total"):
        return txt + " " + (u or "W")
    return txt + ((" " + u) if u else "")


def ha_sensor_mapping(rows, states=None):
    """映射行 + 实时状态，给后台表格用；HA 取不到数时仍返回配置行（值 —）"""
    idx = {}
    for s in (states or []):
        eid = s.get("entity_id")
        if eid:
            idx[eid] = s
    out = []
    for r in rows:
        e = idx.get(r["eid"]) or {}
        a = e.get("attributes") or {}
        st = e.get("state") or ""
        out.append({
            "k": r["k"], "n": r["n"], "eid": r["eid"], "en": r["en"],
            "nm": a.get("friendly_name") or r["n"],
            "s": st, "v": _sensor_view(r["k"], st, a.get("unit_of_measurement")),
        })
    return out


def _ha_states(base, token, timeout=10):
    url = base.rstrip("/") + "/api/states"
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def ha_aggregate(states, show_offline=True, show_zero=True,
                 show_lights=True, show_climates=True, show_tv=True,
                 maps=None, sensor_rows=None):
    """把 HA 全量 states 聚合成看板需要的结构

    maps 不传就读配置；传 (lights, climates, tv) 可以直接指定。
    V7：sensor_rows 不传就读 ha_sensor_map 配置，传了就用指定的映射行。
    """
    if maps is None:
        maps = ha_maps()
    if sensor_rows is None:
        sensor_rows = ha_sensor_rows()
    lights_map, climates_map, tv_map = maps

    idx = {}
    for s in states:
        eid = s.get("entity_id")
        if eid:
            idx[eid] = s

    def st_of(eid):
        return ((idx.get(eid) or {}).get("state") or "")

    # V7：在家 / 用电 / 温度一律从映射行取，停用的行不参与统计也不进分母
    people = []
    people_total = 0
    for r in sensor_rows:
        if r["k"] != "people" or not r["en"]:
            continue
        people_total += 1
        home = "在线" in st_of(r["eid"])
        if home or show_offline:
            people.append({"name": r["n"], "home": home})
    home_count = sum(1 for p in people if p["home"])

    # 用电：总表只允许一条，取第一条启用的
    total = None
    for r in sensor_rows:
        if r["k"] == "total" and r["en"]:
            total = _ha_num((idx.get(r["eid"]) or {}).get("state"))
            break
    items = []
    for r in sensor_rows:
        if r["k"] != "power" or not r["en"]:
            continue
        w = _ha_num(st_of(r["eid"]))
        if w is None:
            continue                      # 无数据 → 不显示
        if w == 0 and not show_zero:
            continue                      # 0 W 且用户选择隐藏
        items.append({"name": r["n"], "w": round(w, 1)})
    items.sort(key=lambda x: -x["w"])

    # 温度
    temps = []
    for r in sensor_rows:
        if r["k"] != "temp" or not r["en"]:
            continue
        t = _ha_num(st_of(r["eid"]))
        if t is not None:
            temps.append({"room": r["n"], "t": round(t, 1)})

    # 灯 / 空调 / 电视：按白名单逐个取，「没开」的一律不进看板。
    # mapping 是给后台「设备映射」表核对用的全量状态，与显示偏好无关。
    lights, climates, tv, mapping = [], [], None, []

    # V6：en=false 的设备仍留在 mapping 里（后台要能看见、改回去），
    # 但不参与看板统计。元组兼容 2 元素（旧测试/调用方）与 3 元素。
    for item in lights_map:
        name, eid = item[0], item[1]
        en = item[2] if len(item) > 2 else True
        st = st_of(eid)
        on = (st == "on")
        mapping.append({"n": name, "eid": eid, "k": "灯", "on": on,
                        "en": en, "s": st or "—"})
        if not en:
            continue
        if on and show_lights:
            lights.append({"name": name, "eid": eid})

    for item in climates_map:
        name, eid = item[0], item[1]
        en = item[2] if len(item) > 2 else True
        st = st_of(eid)
        on = st not in HA_OFF_STATES
        mapping.append({"n": name, "eid": eid, "k": "空调", "on": on,
                        "en": en, "s": st or "—"})
        if not en or not on:
            continue
        a = (idx.get(eid) or {}).get("attributes") or {}
        cur = a.get("current_temperature")
        if show_climates:
            climates.append({
                "name": name,
                "eid": eid,
                "mode": HVAC_MODE_CN.get(st, st),
                "cur": round(float(cur), 1) if isinstance(cur, (int, float)) else None,
            })

    if tv_map:
        tv_name, tv_eid = tv_map[0], tv_map[1]
        tv_en = tv_map[2] if len(tv_map) > 2 else True
        tv_st = st_of(tv_eid)
        tv_on = tv_st not in HA_OFF_STATES
        mapping.append({"n": tv_name, "eid": tv_eid, "k": "电视", "on": tv_on,
                        "en": tv_en, "s": tv_st or "—"})
        if tv_en and tv_on and show_tv:
            # 只要「开着/没开」，不取片源和 app（用电视自带信号源时 HA 也拿不到）
            tv = {"name": tv_name, "on": True}

    return {
        "people": people,
        "home_count": home_count,
        "people_total": people_total,
        "power": {"total": round(total, 1) if total is not None else None, "items": items},
        "temps": temps,
        "lights": lights,
        "climates": climates,
        "tv": tv,
        "mapping": mapping,                       # V4/V6 设备映射（不动）
        "sensor_mapping": ha_sensor_mapping(sensor_rows, states),   # V7 三组 sensor
    }


def _ha_fetch(cfg, force=False):
    """取 HA states（走缓存）→ (states, cached, err, ttl)"""
    global _HA_CACHE
    base = (cfg.get("ha_base_url") or "").strip()
    token = (cfg.get("ha_token") or "").strip()
    try:
        ttl = max(10, int(cfg.get("ha_interval", 30) or 30))
    except Exception:
        ttl = 30
    if not base or not token:
        return None, False, "未配置 HA 地址或令牌", ttl

    now = time.time()
    if (not force) and _HA_CACHE.get("states") is not None \
            and now - _HA_CACHE["ts"] < ttl:
        return _HA_CACHE["states"], True, "", ttl
    try:
        states = _ha_states(base, token)
    except urllib.error.HTTPError as e:
        return None, False, "HA 返回 %s（令牌可能已失效）" % e.code, ttl
    except urllib.error.URLError as e:
        return None, False, "连不上 HA：%s" % (e.reason,), ttl
    except Exception as e:
        return None, False, "取数失败：%s" % e, ttl
    _HA_CACHE = {"ts": now, "states": states}
    return states, False, "", ttl


def ha_board(force=False):
    """带缓存的取数。

    缓存的是 HA 原始 states，聚合每次按当前显示偏好和映射表实时算 ——
    否则后台刚改完，看板最多要等一个 ha_interval 才生效。
    """
    cfg = get_config()
    rows = ha_sensor_rows(cfg)
    states, cached, err, ttl = _ha_fetch(cfg, force)

    if err:
        enabled = bool((cfg.get("ha_base_url") or "").strip()
                       and (cfg.get("ha_token") or "").strip())
        # V7：HA 连不上也要把配置里的映射行回给后台，否则连改都改不了
        return {"enabled": enabled, "error": err, "ts": int(time.time()),
                "cached": False, "interval": ttl,
                "people": [], "home_count": 0,
                "people_total": sum(1 for r in rows if r["k"] == "people" and r["en"]),
                "power": {"total": None, "items": []}, "temps": [],
                "lights": [], "climates": [], "tv": None, "mapping": [],
                "sensor_mapping": ha_sensor_mapping(rows, None)}

    data = ha_aggregate(
        states,
        str(cfg.get("ha_show_offline", "1")) == "1",
        str(cfg.get("ha_show_zero_power", "1")) == "1",
        str(cfg.get("ha_show_lights", "1")) == "1",
        str(cfg.get("ha_show_climates", "1")) == "1",
        str(cfg.get("ha_show_tv", "1")) == "1",
        maps=ha_maps(cfg, with_en=True),
        sensor_rows=rows,
    )
    data.update({"enabled": True, "error": "",
                 "ts": int(_HA_CACHE["ts"]), "cached": bool(cached),
                 "interval": ttl})
    return data


@app.get("/api/ha/board")
def api_ha_board():
    return {"code": 200, "data": ha_board()}


@app.get("/api/admin/ha/entities")
def api_ha_entities(admin=Depends(current_admin)):
    """给「设备映射」下拉用：把 HA 里可选的实体按域分组返回

    只回 light / switch / climate / media_player 四个域，一次拿完前端自己筛，
    不用来回请求。指示灯（*_indicator_light）排在最后并打标，避免选错。
    """
    cfg = get_config()
    states, cached, err, _ = _ha_fetch(cfg)
    if err:
        return {"code": 200, "ok": False, "msg": err, "data": {}}

    groups = {d: [] for d in HA_DOMAINS}
    for s in states:
        eid = s.get("entity_id") or ""
        dom = eid.split(".", 1)[0]
        if dom not in groups:
            continue
        a = s.get("attributes") or {}
        groups[dom].append({
            "eid": eid,
            "name": a.get("friendly_name") or eid,
            "state": s.get("state") or "",
            "ind": "indicator_light" in eid,
        })
    for d in groups:
        groups[d].sort(key=lambda x: (x["ind"], x["name"]))
    return {"code": 200, "ok": True, "msg": "", "cached": cached, "data": groups}


@app.get("/api/admin/ha/sensor_entities")
def api_ha_sensor_entities(admin=Depends(current_admin)):
    """V7「成员与传感器映射」搜索框用：只回 sensor.* 实体，一次拿完前端本地筛

    与 /api/admin/ha/entities 分开，避免把上千个 sensor 混进 V6 设备映射的下拉。
    """
    cfg = get_config()
    states, cached, err, _ = _ha_fetch(cfg)
    if err:
        return {"code": 200, "ok": False, "msg": err, "data": [], "total": 0}
    out = []
    for s in states:
        eid = s.get("entity_id") or ""
        if not eid.startswith("sensor."):
            continue
        a = s.get("attributes") or {}
        st, unit = s.get("state") or "", a.get("unit_of_measurement") or ""
        k = _sensor_guess_kind(st, unit, eid)
        out.append({
            "eid": eid,
            "name": a.get("friendly_name") or eid,
            "state": st,
            "unit": unit,
            "kind": k,
            "v": _sensor_view(k, st, unit),
        })
    out.sort(key=lambda x: x["name"])
    return {"code": 200, "ok": True, "msg": "", "cached": cached,
            "data": out, "total": len(out)}


# ============================================================
# V5：看板顶部天气（位置来自「设置家庭位置」）
# ============================================================
# HA 的 weather 实体状态是这套英文枚举，翻成中文 + 一个表情
HA_COND = {
    "clear-night": ("晴", "🌙"), "cloudy": ("多云", "☁️"), "exceptional": ("异常", "⚠️"),
    "fog": ("雾", "🌫️"), "hail": ("冰雹", "🌨️"), "lightning": ("雷电", "⛈️"),
    "lightning-rainy": ("雷阵雨", "⛈️"), "partlycloudy": ("晴间多云", "⛅"),
    "pouring": ("大雨", "🌧️"), "rainy": ("雨", "🌦️"), "snowy": ("雪", "🌨️"),
    "snowy-rainy": ("雨夹雪", "🌨️"), "sunny": ("晴", "☀️"),
    "windy": ("大风", "💨"), "windy-variant": ("大风", "💨"),
}
# 中国天气网返回的是中文，用关键词猜图标
CITY_ICON = (("雷", "⛈️"), ("雪", "🌨️"), ("雨", "🌧️"), ("雾", "🌫️"), ("霾", "🌫️"),
             ("沙", "🌪️"), ("尘", "🌪️"), ("风", "💨"), ("阴", "☁️"), ("云", "⛅"), ("晴", "☀️"))

_WX_CACHE = {"ts": 0.0, "data": None, "err": "", "fails": 0}


def _wx_num(v):
    """「15℃」/15/「-3℃」→ float；取不到返回 None"""
    if v is None:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", str(v))
    return float(m.group()) if m else None


def _wx_fmt(v):
    if v is None:
        return "?"
    return ("%d" % v) if abs(v - round(v)) < 0.05 else ("%.1f" % v)


def _wx_city_icon(text):
    for k, ico in CITY_ICON:
        if k in (text or ""):
            return ico
    return "🌤️"


def _ha_get_json(base, token, path, timeout=10):
    req = urllib.request.Request(base.rstrip("/") + path, headers={
        "Authorization": "Bearer " + token, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _ha_post_json(base, token, path, body, timeout=15):
    req = urllib.request.Request(
        base.rstrip("/") + path, data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _weather_from_ha(cfg):
    """跟 HA 走：位置名取 HA 配置里的家，今日温度范围取 daily 预报"""
    base = (cfg.get("ha_base_url") or "").strip()
    token = (cfg.get("ha_token") or "").strip()
    if not base or not token:
        raise RuntimeError("未配置 HA 地址或令牌")

    eid = (cfg.get("weather_ha_entity") or "").strip()
    name = ""
    if not eid:
        states = _ha_states(base, token)
        cand = [s for s in states if str(s.get("entity_id", "")).startswith("weather.")]
        if not cand:
            raise RuntimeError("HA 里没有 weather 实体")
        eid = cand[0]["entity_id"]

    try:
        conf = _ha_get_json(base, token, "/api/config") or {}
        name = (conf.get("location_name") or "").strip()
    except Exception:
        pass

    cond, hi, lo = "", None, None
    try:
        r = _ha_post_json(base, token,
                          "/api/services/weather/get_forecasts?return_response",
                          {"entity_id": eid, "type": "daily"})
        fc = ((r.get("service_response") or {}).get(eid) or {}).get("forecast") or []
        if fc:
            cond = str(fc[0].get("condition") or "")
            hi = _wx_num(fc[0].get("temperature"))
            lo = _wx_num(fc[0].get("templow"))
    except Exception:
        pass

    if not cond or hi is None:
        # 预报拿不到就退回实体当前状态（没有温度范围）
        st = _ha_get_json(base, token, "/api/states/" + eid) or {}
        cond = cond or str(st.get("state") or "")
        a = st.get("attributes") or {}
        if hi is None:
            hi = _wx_num(a.get("temperature"))
        name = name or str(a.get("friendly_name") or "")

    cn, ico = HA_COND.get(cond, (cond or "未知", "🌤️"))
    return {"name": name or "家", "cond": cn, "ico": ico,
            "tmin": lo, "tmax": hi, "src": "ha", "entity": eid}


def _weather_from_city(cfg):
    """手动城市：中国天气网城市代码（免 key）"""
    code = (cfg.get("weather_city_code") or "").strip()
    if not code:
        raise RuntimeError("没填城市代码")
    url = "http://t.weather.itboy.net/api/weather/city/" + urllib.parse.quote(code)
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
    with urllib.request.urlopen(req, timeout=12) as r:
        j = json.loads(r.read().decode("utf-8", "replace"))
    if str(j.get("status")) != "200":
        raise RuntimeError("天气接口返回 %s" % j.get("status"))
    data = j.get("data") or {}
    fc = (data.get("forecast") or [{}])[0]
    typ = str(fc.get("type") or "")
    name = (cfg.get("weather_city_name") or "").strip() \
        or ((j.get("cityInfo") or {}).get("city") or "")
    return {"name": name or "未知", "cond": typ or "未知", "ico": _wx_city_icon(typ),
            "tmin": _wx_num(fc.get("low")), "tmax": _wx_num(fc.get("high")),
            "src": "city", "entity": ""}


def _wx_text(d, show_range):
    t = "%s · %s" % (d.get("name") or "", d.get("cond") or "")
    if show_range and d.get("tmax") is not None:
        lo = d["tmin"] if d.get("tmin") is not None else d["tmax"]
        t += " · 今日 %s~%s℃" % (_wx_fmt(lo), _wx_fmt(d["tmax"]))
    return t


def _wx_effective_cfg(cfg):
    """V6 兜底：HA 接入已停用时，天气不能再用「跟随 HA」，一律走手动城市。

    正常情况配置保存时就把 weather_source 落库成 city 了，这里防的是旧配置、
    直接调 weather_probe，或有人在 HA 停用期间又传了 weather_source=ha。
    """
    c = dict(cfg or {})
    if str(c.get("ha_enabled", "1")) != "1" \
            and (c.get("weather_source") or "ha").strip() == "ha":
        c["weather_source"] = "city"
    return c


def weather_probe(cfg):
    """取一次，不写缓存（给后台「测试取数」用）"""
    cfg = _wx_effective_cfg(cfg)
    src = (cfg.get("weather_source") or "ha").strip()
    d = _weather_from_city(cfg) if src == "city" else _weather_from_ha(cfg)
    d["text"] = _wx_text(d, str(cfg.get("weather_show_range", "1")) == "1")
    d["ok"] = True
    return d


def weather_get(force=False, cfg=None):
    """带缓存 + 失败回落：连续失败 3 次才认输（看板据此隐藏那条）"""
    cfg = _wx_effective_cfg(cfg or get_config())
    try:
        ttl = max(60, int(cfg.get("weather_interval", 600) or 600))
    except Exception:
        ttl = 600
    if str(cfg.get("weather_enabled", "1")) != "1":
        return {"enabled": False, "ok": False, "text": "", "interval": ttl}

    c = _WX_CACHE
    now = time.time()
    if (not force) and c["data"] and now - c["ts"] < ttl:
        return dict(c["data"], cached=True, interval=ttl, ok=True)

    # 刚失败过就先别重试：/api/board 每几秒拉一次，不能每次都去打外网
    cool = 60 if not c.get("data") else min(ttl, 120)
    if (not force) and c.get("try_ts") and now - c["try_ts"] < cool:
        if c.get("data"):
            return dict(c["data"], cached=True, interval=ttl,
                        ok=True, stale=True, error=c.get("err", ""))
        return {"enabled": True, "ok": False, "text": "", "interval": ttl,
                "error": c.get("err", ""), "fails": c.get("fails", 0), "ts": int(now)}

    c["try_ts"] = now
    src = (cfg.get("weather_source") or "ha").strip()
    try:
        d = _weather_from_city(cfg) if src == "city" else _weather_from_ha(cfg)
    except Exception as e:
        c["fails"] = int(c.get("fails") or 0) + 1
        c["err"] = str(e)[:200]
        if c["data"] and c["fails"] < 3:
            # 还留着上次的结果，先继续显示，别让顶部突然空一块
            return dict(c["data"], cached=True, interval=ttl,
                        ok=True, stale=True, error=c["err"])
        # 认输：连着 3 次都取不到，把旧数据也清了，免得冷却分支又把它放出来
        c["data"] = None
        return {"enabled": True, "ok": False, "text": "", "error": c["err"],
                "interval": ttl, "fails": c["fails"], "ts": int(now)}

    d["enabled"] = True
    d["ok"] = True
    d["text"] = _wx_text(d, str(cfg.get("weather_show_range", "1")) == "1")
    d["ts"] = int(now)
    c.update({"ts": now, "data": d, "err": "", "fails": 0})
    return dict(d, cached=False, interval=ttl)


def weather_public():
    """塞进 /api/board 的那一小块"""
    d = weather_get()
    keys = ("enabled", "ok", "text", "ico", "name", "cond", "tmin", "tmax",
            "src", "ts", "interval", "error", "stale")
    return {k: d.get(k) for k in keys if k in d}


@app.get("/api/weather")
def api_weather():
    return {"code": 200, "data": weather_public()}


@app.get("/api/admin/weather/loc")
def api_weather_loc(admin=Depends(current_admin)):
    """给「设置家庭位置」用：HA 里读到的位置 + 可选天气实体"""
    cfg = get_config()
    out = {"ok": True, "ha": {"name": "", "lat": None, "lon": None, "tz": "",
                              "error": "", "entities": []}}
    base = (cfg.get("ha_base_url") or "").strip()
    token = (cfg.get("ha_token") or "").strip()
    if not base or not token:
        out["ha"]["error"] = "未配置 HA 地址或令牌"
        return {"code": 200, "data": out}
    try:
        conf = _ha_get_json(base, token, "/api/config") or {}
        out["ha"].update({"name": conf.get("location_name") or "",
                          "lat": conf.get("latitude"), "lon": conf.get("longitude"),
                          "tz": conf.get("time_zone") or ""})
    except Exception as e:
        out["ha"]["error"] = "读 HA 配置失败：%s" % str(e)[:120]
    try:
        states = _ha_states(base, token)
        out["ha"]["entities"] = [
            {"eid": s.get("entity_id"),
             "name": (s.get("attributes") or {}).get("friendly_name") or s.get("entity_id"),
             "state": s.get("state") or ""}
            for s in states if str(s.get("entity_id", "")).startswith("weather.")]
    except Exception as e:
        out["ha"]["error"] = (out["ha"]["error"] or "") + " 实体列表失败：%s" % str(e)[:80]
    return {"code": 200, "data": out}


@app.post("/api/admin/weather/test")
def api_weather_test(payload: dict = Body(default=None), admin=Depends(current_admin)):
    """按当前表单（或已保存配置）实际取一次，不写缓存"""
    payload = payload or {}
    cfg = get_config()
    for k in ("weather_source", "weather_ha_entity", "weather_city_name",
              "weather_city_code", "weather_show_range"):
        if k in payload and payload[k] is not None:
            cfg[k] = str(payload[k])
    cfg = _wx_effective_cfg(cfg)
    try:
        d = weather_probe(cfg)
        return {"code": 200, "ok": True, "data": d}
    except Exception as e:
        return {"code": 200, "ok": False, "msg": str(e)[:200]}


@app.post("/api/admin/ha/test")
def api_ha_test(payload: dict = Body(default=None), admin=Depends(current_admin)):
    """测试连接。payload 里可带临时 base/token（未保存时先试）"""
    payload = payload or {}
    cfg = get_config()
    base = (payload.get("base") or cfg.get("ha_base_url") or "").strip()
    token = (payload.get("token") or "").strip()
    if not token or "•" in token:
        token = (cfg.get("ha_token") or "").strip()
    if not base or not token:
        return {"code": 400, "ok": False, "msg": "地址或令牌为空"}
    try:
        states = _ha_states(base, token, timeout=8)
        data = ha_aggregate(states)
        return {"code": 200, "ok": True, "msg": "连接成功",
                "entities": len(states),
                "sample": {
                    "people": len(data["people"]),
                    "temps": len(data["temps"]),
                    "power_total": data["power"]["total"],
                    "lights_on": len(data["lights"]),
                    "climates_on": len(data["climates"]),
                    "tv_on": bool(data["tv"]),
                }}
    except urllib.error.HTTPError as e:
        msg = "认证失败（%s），请检查令牌" % e.code if e.code in (401, 403) else "HA 返回 %s" % e.code
        return {"code": 200, "ok": False, "msg": msg}
    except Exception as e:
        return {"code": 200, "ok": False, "msg": "连接失败：%s" % e}


# ============================================================
# 登录 / 口令
# ============================================================
@app.get("/api/admin/state")
def api_admin_state(request: Request):
    cfg = get_config()
    need_setup = not has_password(cfg)
    authed = False
    token = request.cookies.get("sid")
    if token:
        with db() as c:
            row = c.execute("SELECT expires FROM sessions WHERE token=?", (token,)).fetchone()
            authed = bool(row and int(row["expires"]) >= int(time.time()))
    return {"code": 200, "need_setup": need_setup, "authed": authed}


@app.post("/api/admin/setup")
def api_admin_setup(item: LoginIn, request: Request, response: Response):
    cfg = get_config()
    if has_password(cfg):
        raise HTTPException(status_code=400, detail="口令已设置")
    pwd = (item.password or "").strip()
    if len(pwd) < 6:
        raise HTTPException(status_code=400, detail="口令至少 6 位")
    set_config_items({"admin_pwd": hash_password(pwd)})
    token = new_session(request.headers.get("user-agent", ""), 30 if item.remember else 1)
    response.set_cookie("sid", token, max_age=30 * 86400 if item.remember else None,
                        httponly=True, samesite="lax", path="/")
    return {"code": 200, "msg": "口令已设置"}


@app.post("/api/admin/login")
def api_admin_login(item: LoginIn, request: Request, response: Response):
    ip = client_ip(request)
    now = time.time()
    fails = [t for t in _LOGIN_FAILS.get(ip, []) if now - t < 300]
    if len(fails) >= 5:
        raise HTTPException(status_code=429, detail="失败次数过多，请 5 分钟后再试")

    cfg = get_config()
    stored = cfg.get("admin_pwd", "")
    if not stored:
        raise HTTPException(status_code=400, detail="尚未设置口令")
    if not verify_password((item.password or "").strip(), stored):
        fails.append(now)
        _LOGIN_FAILS[ip] = fails
        left = max(0, 5 - len(fails))
        raise HTTPException(status_code=401, detail="口令错误，还可尝试 %d 次" % left)

    _LOGIN_FAILS.pop(ip, None)
    token = new_session(request.headers.get("user-agent", ""), 30 if item.remember else 1)
    response.set_cookie("sid", token, max_age=30 * 86400 if item.remember else None,
                        httponly=True, samesite="lax", path="/")
    return {"code": 200, "msg": "ok"}


@app.post("/api/admin/logout")
def api_admin_logout(request: Request, response: Response):
    token = request.cookies.get("sid")
    if token:
        with db() as c:
            c.execute("DELETE FROM sessions WHERE token=?", (token,))
    response.delete_cookie("sid", path="/")
    return {"code": 200}


@app.post("/api/admin/password")
def api_admin_password(item: PwdChangeIn, admin=Depends(current_admin)):
    cfg = get_config()
    if not verify_password((item.old or "").strip(), cfg.get("admin_pwd", "")):
        raise HTTPException(status_code=400, detail="当前口令不正确")
    pwd = (item.new or "").strip()
    if len(pwd) < 6:
        raise HTTPException(status_code=400, detail="新口令至少 6 位")
    set_config_items({"admin_pwd": hash_password(pwd)})
    with db() as c:
        c.execute("DELETE FROM sessions")   # 全部设备重新登录
    return {"code": 200, "msg": "口令已修改，请重新登录"}


# ============================================================
# 标签管理
# ============================================================
@app.get("/api/admin/tags")
def api_tags(admin=Depends(current_admin)):
    return {"code": 200, "data": list_tags()}


@app.post("/api/admin/tags")
def api_tag_save(item: TagIn, admin=Depends(current_admin)):
    name = (item.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="标签名不能为空")
    if len(name) > 12:
        raise HTTPException(status_code=400, detail="标签名最长 12 个字符")
    if any(ch in name for ch in " #:："):
        raise HTTPException(status_code=400, detail="标签名不能包含空格、# 或冒号")
    with db() as c:
        c.execute("INSERT INTO tags(name,emoji,color,speak,sort) VALUES (?,?,?,?,?) "
                  "ON CONFLICT(name) DO UPDATE SET emoji=excluded.emoji, color=excluded.color,"
                  "speak=excluded.speak, sort=excluded.sort",
                  (name, item.emoji or "", item.color or "#64748b", 1 if item.speak else 0, item.sort))
    return {"code": 200, "msg": "ok"}


@app.delete("/api/admin/tags/{name}")
def api_tag_delete(name: str, admin=Depends(current_admin)):
    if name == "普通通知":
        raise HTTPException(status_code=400, detail="「普通通知」是兜底标签，不能删除")
    with db() as c:
        c.execute("DELETE FROM tags WHERE name=?", (name,))
    return {"code": 200, "msg": "ok"}


# ============================================================
# 配置
# ============================================================
EDITABLE_CONFIG = {
    "bot_app_key", "bot_app_secret", "dedup_window", "tag_max_len", "image_max_edge",
    "board_limit", "refresh_sec", "theme", "speak_default", "speak_rate", "show_sender",
    "show_group", "cols", "autoscroll", "autoscroll_sec", "pin_limit", "retention_days",
    # V3 消息接入方式
    "im_channel", "wecom_corp_id", "wecom_agent_id", "wecom_secret",
    "wecom_token", "wecom_aes_key",
    # V3 Home Assistant
    "ha_base_url", "ha_token", "ha_interval", "ha_enabled",
    "ha_show_offline", "ha_show_zero_power",
    "ha_show_lights", "ha_show_climates", "ha_show_tv",
    "ha_lights_map", "ha_climates_map", "ha_tv_map",
    # V7 三组 sensor 映射
    "ha_sensor_map",
    # V5 顶部天气
    "weather_enabled", "weather_source", "weather_ha_entity",
    "weather_city_name", "weather_city_code", "weather_interval", "weather_show_range",
}


@app.get("/api/admin/config")
def api_config(admin=Depends(current_admin)):
    cfg = get_config()
    # 敏感项一律不下发明文，只给掩码和「是否已设置」
    safe = {k: cfg.get(k, "") for k in EDITABLE_CONFIG if k not in SECRET_CONFIG}
    for k in SECRET_CONFIG:
        v = cfg.get(k, "") or ""
        safe[k + "_masked"] = ("•" * 8 + v[-4:]) if v else ""
        safe["has_" + k] = bool(v)
    safe["has_secret"] = bool(cfg.get("bot_app_secret"))   # 兼容旧前端字段
    safe["has_password"] = has_password(cfg)
    return {"code": 200, "data": safe}


@app.post("/api/admin/config")
def api_config_save(payload: dict = Body(...), admin=Depends(current_admin)):
    items = {}
    for k, v in payload.items():
        if k not in EDITABLE_CONFIG:
            continue
        # 敏感项：前端回传掩码或空串时不动原值（留空即保持不变）
        if k in SECRET_CONFIG and isinstance(v, str) and ("•" in v or not v.strip()):
            continue
        items[k] = v
    if items:
        # V6-1：关闭「家庭状态接入」→ 天气位置自动改为手动指定城市。
        # 联动写进同一批 items，一次落库，避免前端再发一次请求。
        hv = items.get("ha_enabled")
        if hv is not None and str(hv).strip().lower() in ("0", "false", "off", "no"):
            items["weather_source"] = "city"
        old = get_config()
        wx_changed = any(k.startswith("weather_") and str(v) != str(old.get(k, ""))
                         for k, v in items.items())
        set_config_items(items)
        if wx_changed:
            # 来源/参数变了就别再拿旧缓存糊弄看板，下一轮立刻用新配置取
            _WX_CACHE.update({"ts": 0.0, "try_ts": 0.0, "data": None,
                              "err": "", "fails": 0})
    return {"code": 200, "msg": "已保存", "saved": sorted(items.keys())}


# ============================================================
# 消息管理
# ============================================================
@app.get("/api/admin/messages")
def api_admin_messages(limit: int = 50, offset: int = 0, tag: str = "", q: str = "",
                       admin=Depends(current_admin)):
    limit = max(1, min(500, limit))
    where, args = [], []
    if tag:
        where.append("tag=?")
        args.append(tag)
    if q:
        where.append("(content LIKE ? OR COALESCE(sender_name,'') LIKE ?)")
        args += ["%" + q + "%", "%" + q + "%"]
    w = (" WHERE " + " AND ".join(where)) if where else ""
    tags = tag_map()
    with db() as c:
        total = c.execute("SELECT COUNT(*) n FROM messages" + w, args).fetchone()["n"]
        rows = c.execute("SELECT %s FROM messages%s ORDER BY create_time DESC, id DESC LIMIT ? OFFSET ?"
                         % (SELECT_COLS, w), args + [limit, offset]).fetchall()
    return {"code": 200, "total": total,
            "data": [_row_to_msg(r, tags) for r in rows],
            "tags": list_tags()}


@app.delete("/api/admin/messages/{mid}")
def api_message_delete(mid: int, admin=Depends(current_admin)):
    with db() as c:
        c.execute("DELETE FROM messages WHERE id=?", (mid,))
    return {"code": 200, "msg": "ok"}


@app.post("/api/admin/messages/delete")
def api_message_delete_batch(item: IdsIn, admin=Depends(current_admin)):
    if not item.ids:
        return {"code": 200, "deleted": 0}
    qs = ",".join("?" * len(item.ids))
    with db() as c:
        cur = c.execute("DELETE FROM messages WHERE id IN (%s)" % qs, item.ids)
        n = cur.rowcount
    return {"code": 200, "deleted": n}


@app.post("/api/admin/messages/cleanup")
def api_message_cleanup(item: CleanupIn, admin=Depends(current_admin)):
    days = max(1, min(3650, item.days))
    cutoff = int(time.time()) - days * 86400
    with db() as c:
        cur = c.execute("DELETE FROM messages WHERE COALESCE(pinned,0)=0 AND create_time < ?",
                        (cutoff,))
        n = cur.rowcount
    return {"code": 200, "deleted": n}


@app.post("/api/admin/messages/{mid}/pin")
def api_message_pin(mid: int, item: PinIn, admin=Depends(current_admin)):
    cfg = get_config()
    limit = int(cfg.get("pin_limit", 5) or 5)
    with db() as c:
        if item.pinned:
            n = c.execute("SELECT COUNT(*) n FROM messages WHERE COALESCE(pinned,0)=1").fetchone()["n"]
            row = c.execute("SELECT pinned FROM messages WHERE id=?", (mid,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="消息不存在")
            if not row["pinned"] and n >= limit:
                raise HTTPException(status_code=400, detail="常驻消息最多 %d 条" % limit)
            c.execute("UPDATE messages SET pinned=1, pinned_at=? WHERE id=?",
                      (int(time.time()), mid))
        else:
            c.execute("UPDATE messages SET pinned=0, pinned_at=NULL WHERE id=?", (mid,))
    return {"code": 200, "msg": "ok"}


# ============================================================
# 备份 / 恢复
# ============================================================
def _backup_to(path):
    src = connect()
    dst = sqlite3.connect(path)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()


@app.get("/api/admin/backup")
def api_backup(admin=Depends(current_admin)):
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = "notify-%s.db" % ts
    path = os.path.join(BACKUP_DIR, name)
    _backup_to(path)
    # 只保留最近 10 份自动备份
    files = sorted([f for f in os.listdir(BACKUP_DIR) if f.startswith("notify-")])
    for f in files[:-10]:
        try:
            os.remove(os.path.join(BACKUP_DIR, f))
        except Exception:
            pass
    return FileResponse(path, filename=name, media_type="application/octet-stream")


@app.get("/api/admin/backup/info")
def api_backup_info(admin=Depends(current_admin)):
    size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
    with db() as c:
        n_msg = c.execute("SELECT COUNT(*) n FROM messages").fetchone()["n"]
        n_img = c.execute("SELECT COUNT(*) n FROM messages WHERE COALESCE(image,'')<>''").fetchone()["n"]
        n_tag = c.execute("SELECT COUNT(*) n FROM tags").fetchone()["n"]
    imgs = 0
    for root, _, files in os.walk(UPLOAD_DIR):
        imgs += len([f for f in files if not f.startswith(".")])
    backups = sorted([f for f in os.listdir(BACKUP_DIR) if f.startswith("notify-")]) if os.path.isdir(BACKUP_DIR) else []
    return {"code": 200, "data": {
        "db_size": size, "messages": n_msg, "images": n_img, "image_msgs": n_img,
        "upload_files": imgs, "tags": n_tag,
        "last_backup": backups[-1] if backups else "",
    }}


@app.post("/api/admin/restore")
async def api_restore(file: UploadFile = File(...), admin=Depends(current_admin)):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(data) > MAX_UPLOAD:
        raise HTTPException(status_code=400, detail="文件超过 50 MB")
    if not data.startswith(b"SQLite format 3\x00"):
        raise HTTPException(status_code=400, detail="不是有效的 SQLite 数据库")

    tmp = os.path.join(BASE_DIR, "_restore_%d.db" % int(time.time()))
    with open(tmp, "wb") as f:
        f.write(data)

    try:
        chk = sqlite3.connect(tmp)
        ok = chk.execute("PRAGMA integrity_check").fetchone()[0]
        tables = {r[0] for r in chk.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        chk.close()
        if ok != "ok":
            raise HTTPException(status_code=400, detail="数据库校验失败：%s" % ok)
        if "messages" not in tables:
            raise HTTPException(status_code=400, detail="缺少 messages 表，不像是本系统的备份")
        if "config" not in tables:
            raise HTTPException(status_code=400, detail="缺少 config 表，不像是本系统的备份")

        # 先给现库留一份
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_path = os.path.join(BACKUP_DIR, "notify-%s.db" % ts)
        try:
            _backup_to(safe_path)
        except Exception:
            pass

        # 用 backup API 反向灌入，避免直接换文件踩 WAL
        src = sqlite3.connect(tmp)
        dst = sqlite3.connect(DB_PATH)
        with dst:
            src.backup(dst)
        dst.close()
        src.close()
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass

    init_db()
    with db() as c:
        c.execute("DELETE FROM sessions")   # 恢复后强制重新登录
    return {"code": 200, "msg": "恢复完成，请重新登录", "backup": os.path.basename(safe_path)}


# ============================================================
# 图片清理
# ============================================================
def _upload_files():
    """遍历 uploads/，返回 [(相对 BASE_DIR 的路径, 绝对路径, 字节数)]"""
    out = []
    if not os.path.isdir(UPLOAD_DIR):
        return out
    for root, _, files in os.walk(UPLOAD_DIR):
        for f in files:
            if f.startswith("."):
                continue
            full = os.path.join(root, f)
            rel = os.path.relpath(full, BASE_DIR).replace("\\", "/")
            try:
                out.append((rel, full, os.path.getsize(full)))
            except OSError:
                pass
    return out


def _scan_orphans():
    """无引用 = 文件名不在 messages.image 里

    两种比对：先按相对路径（uploads/202611/xx.jpg），再退回按纯文件名。
    退回是为了防止历史数据里存了裸文件名或 /uploads/ 前缀，误判成孤儿。
    """
    with db() as c:
        rows = c.execute("SELECT DISTINCT image FROM messages "
                         "WHERE COALESCE(image,'')<>''").fetchall()
    used = {(r["image"] or "").strip().lstrip("/") for r in rows}
    used.discard("")
    used_base = {os.path.basename(x) for x in used if x}
    files = _upload_files()
    orphans = [x for x in files
               if x[0] not in used and os.path.basename(x[0]) not in used_base]
    return files, orphans


@app.get("/api/admin/images/scan")
def api_images_scan(admin=Depends(current_admin)):
    files, orphans = _scan_orphans()
    return {"code": 200, "data": {
        "total": len(files),
        "orphan": len(orphans),
        "orphan_bytes": sum(x[2] for x in orphans),
        "kept": len(files) - len(orphans),
        "sample": [{"path": x[0], "size": x[2]} for x in orphans[:20]],
    }}


@app.post("/api/admin/images/clean")
def api_images_clean(admin=Depends(current_admin)):
    files, orphans = _scan_orphans()
    if not orphans:
        return {"code": 200, "deleted": 0, "freed": 0, "msg": "没有无引用图片"}
    # 删之前先留一份数据库快照，万一比对逻辑有漏还能追溯
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        _backup_to(os.path.join(BACKUP_DIR, "notify-before-imgclean-%s.db" % ts))
    except Exception:
        pass
    deleted, freed, failed = 0, 0, []
    for rel, full, size in orphans:
        try:
            os.remove(full)
            deleted += 1
            freed += size
        except Exception as e:
            failed.append({"path": rel, "err": str(e)})
    return {"code": 200, "deleted": deleted, "freed": freed,
            "failed": failed[:10], "msg": "已清理 %d 个文件" % deleted}


# ============================================================
# 企业微信 WeComBot
#   接收：企微服务器回调 → 验签 → AES 解密 → 解析 XML → 入库
#   图片：用 media_id 调 media/get 下载后落盘
# ============================================================
WECOM_API = "https://qyapi.weixin.qq.com"
_WECOM_TOKEN = {"token": "", "expires": 0.0}

AT_RE = re.compile(r"^\s*@[^\s@]{1,40}\s*")


def _strip_at(text):
    """去掉开头的 @机器人 提及（企微群里的 @ 同样会进正文）"""
    s = text or ""
    for _ in range(4):
        m = AT_RE.match(s)
        if not m:
            break
        s = s[m.end():]
    return s.lstrip()


def _parse_tag(text, max_len=12):
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


def _aes_cbc(data, key, iv, mode):
    try:
        from Crypto.Cipher import AES
        c = AES.new(key, AES.MODE_CBC, iv)
        return c.decrypt(data) if mode == "d" else c.encrypt(data)
    except ImportError:
        pass
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    ctx = Cipher(algorithms.AES(key), modes.CBC(iv))
    op = ctx.decryptor() if mode == "d" else ctx.encryptor()
    return op.update(data) + op.finalize()


def _pkcs7_unpad(b):
    p = b[-1] if b else 0
    return b[:-p] if 1 <= p <= 32 else b


def _pkcs7_pad(b):
    n = 32 - (len(b) % 32)
    return b + bytes([n]) * n


class WeComCrypto:
    """企业微信回调消息加解密（AES-256-CBC）"""

    def __init__(self, token, aes_key, corp_id):
        self.token = token or ""
        self.corp_id = corp_id or ""
        if not aes_key or len(aes_key) != 43:
            raise ValueError("EncodingAESKey 必须是 43 位")
        self.key = base64.b64decode(aes_key + "=")

    def signature(self, timestamp, nonce, encrypt):
        parts = sorted([self.token, str(timestamp), str(nonce), encrypt])
        return hashlib.sha1("".join(parts).encode()).hexdigest()

    def verify(self, msg_signature, timestamp, nonce, encrypt):
        return hmac.compare_digest(self.signature(timestamp, nonce, encrypt),
                                   msg_signature or "")

    def decrypt(self, encrypt):
        raw = base64.b64decode(encrypt)
        plain = _pkcs7_unpad(_aes_cbc(raw, self.key, self.key[:16], "d"))
        # 结构：16 字节随机串 + 4 字节网络序长度 + 消息体 + receiveid
        msg_len = struct.unpack(">I", plain[16:20])[0]
        msg = plain[20:20 + msg_len].decode("utf-8")
        recv = plain[20 + msg_len:].decode("utf-8")
        return msg, recv

    def encrypt(self, text):
        body = (secrets.token_bytes(16)
                + struct.pack(">I", len(text.encode("utf-8")))
                + text.encode("utf-8")
                + self.corp_id.encode("utf-8"))
        return base64.b64encode(
            _aes_cbc(_pkcs7_pad(body), self.key, self.key[:16], "e")).decode()


def _crypto_from_cfg(cfg):
    return WeComCrypto(cfg.get("wecom_token", ""), cfg.get("wecom_aes_key", ""),
                       cfg.get("wecom_corp_id", ""))


def _xml_field(xml_text, name):
    m = re.search(r"<%s>\s*<!\[CDATA\[(.*?)\]\]>\s*</%s>" % (name, name), xml_text, re.S)
    if m:
        return m.group(1).strip()
    m = re.search(r"<%s>(.*?)</%s>" % (name, name), xml_text, re.S)
    return m.group(1).strip() if m else ""


def wecom_access_token(cfg=None, force=False):
    cfg = cfg or get_config()
    now = time.time()
    if not force and _WECOM_TOKEN["token"] and now < _WECOM_TOKEN["expires"]:
        return _WECOM_TOKEN["token"]
    cid = (cfg.get("wecom_corp_id") or "").strip()
    sec = (cfg.get("wecom_secret") or "").strip()
    if not cid or not sec:
        raise RuntimeError("企业微信 CorpID 或 Secret 未配置")
    url = "%s/cgi-bin/gettoken?corpid=%s&corpsecret=%s" % (
        WECOM_API, urllib.parse.quote(cid), urllib.parse.quote(sec))
    with urllib.request.urlopen(url, timeout=10) as r:
        d = json.loads(r.read().decode("utf-8"))
    if d.get("errcode"):
        raise RuntimeError("gettoken 失败：%s %s" % (d.get("errcode"), d.get("errmsg")))
    _WECOM_TOKEN["token"] = d["access_token"]
    _WECOM_TOKEN["expires"] = now + max(600, int(d.get("expires_in", 7200)) - 300)
    return _WECOM_TOKEN["token"]


def wecom_download(media_id, cfg=None):
    at = wecom_access_token(cfg)
    url = "%s/cgi-bin/media/get?access_token=%s&media_id=%s" % (
        WECOM_API, urllib.parse.quote(at), urllib.parse.quote(media_id))
    with urllib.request.urlopen(url, timeout=25) as r:
        ctype = r.headers.get("Content-Type", "")
        raw = r.read()
    if "json" in ctype or "text/plain" in ctype:
        raise RuntimeError("下载媒体失败：%s" % raw[:200])
    return raw, ctype


def wecom_user_name(userid):
    """取企微成员姓名，拿不到就退回 userid（需要通讯录读取权限）"""
    try:
        at = wecom_access_token()
        url = "%s/cgi-bin/user/get?access_token=%s&userid=%s" % (
            WECOM_API, urllib.parse.quote(at), urllib.parse.quote(userid))
        with urllib.request.urlopen(url, timeout=6) as r:
            d = json.loads(r.read().decode("utf-8"))
        return d.get("name") or userid
    except Exception:
        return userid


def wecom_handle(xml_text):
    """后台任务：解析解密后的消息 XML 并入库"""
    try:
        msg_type = _xml_field(xml_text, "MsgType").lower()
        userid = _xml_field(xml_text, "FromUserName")
        create = _xml_field(xml_text, "CreateTime")
        chat = _xml_field(xml_text, "ChatId") or _xml_field(xml_text, "ToUserName")
        cfg = get_config()
        try:
            max_len = int(cfg.get("tag_max_len", 12))
        except Exception:
            max_len = 12
        try:
            max_edge = int(cfg.get("image_max_edge", 1920))
        except Exception:
            max_edge = 1920

        sender = wecom_user_name(userid) if userid else ""
        try:
            ts = int(create) if create else int(time.time())
        except Exception:
            ts = int(time.time())

        image = ""
        if msg_type in ("image", "file", "voice", "video"):
            media_id = _xml_field(xml_text, "MediaId")
            if media_id:
                raw, ctype = wecom_download(media_id, cfg)
                image = save_image_bytes(raw, max_edge, ctype)

        content = ""
        if msg_type == "text":
            content = _strip_at(_xml_field(xml_text, "Content"))
        elif msg_type == "mixed":
            # 图文混排：企微用 MsgItems 列表，取第一段文本
            m = re.search(r"<Content>\s*<!\[CDATA\[(.*?)\]\]>", xml_text, re.S)
            if m:
                content = _strip_at(m.group(1))

        if not content and not image:
            return

        tag, body = _parse_tag(content, max_len) if content else ("普通通知", "")
        with db() as c:
            c.execute(
                "INSERT INTO messages(content,tag,create_time,is_expired,sender_name,sender_id,"
                "conversation_title,image,pinned) VALUES (?,?,?,0,?,?,?,?,0)",
                (body, tag, ts, (sender or "")[:64], (userid or "")[:64],
                 (chat or "")[:128], image))
        print("[wecom] 入库 %s | %s | %s" % (tag, sender, (body or image)[:40]), flush=True)
    except Exception as e:
        print("[wecom] 处理失败：%s" % e, flush=True)


@app.get("/wecom/callback")
def wecom_verify(msg_signature: str = "", timestamp: str = "", nonce: str = "",
                 echostr: str = ""):
    """配置回调 URL 时企微发起的校验，需原样返回解密后的 echostr"""
    cfg = get_config()
    try:
        wc = _crypto_from_cfg(cfg)
    except Exception as e:
        return Response("配置不完整：%s" % e, status_code=400, media_type="text/plain")
    if not wc.verify(msg_signature, timestamp, nonce, echostr):
        return Response("签名校验失败", status_code=403, media_type="text/plain")
    try:
        msg, _ = wc.decrypt(echostr)
    except Exception as e:
        return Response("解密失败：%s" % e, status_code=400, media_type="text/plain")
    return Response(msg, media_type="text/plain")


@app.post("/wecom/callback")
async def wecom_callback(request: Request, background: BackgroundTasks,
                         msg_signature: str = "", timestamp: str = "",
                         nonce: str = ""):
    """收消息。企微要求 5 秒内响应，所以先回 success 再后台处理"""
    cfg = get_config()
    body = (await request.body()).decode("utf-8", "replace")
    encrypt = _xml_field(body, "Encrypt")
    if not encrypt:
        return Response("success", media_type="text/plain")
    try:
        wc = _crypto_from_cfg(cfg)
        if not wc.verify(msg_signature, timestamp, nonce, encrypt):
            return Response("签名校验失败", status_code=403, media_type="text/plain")
        msg, _ = wc.decrypt(encrypt)
    except Exception as e:
        print("[wecom] 验签/解密失败：%s" % e, flush=True)
        return Response("success", media_type="text/plain")
    background.add_task(wecom_handle, msg)
    return Response("success", media_type="text/plain")


# ============================================================
# 机器人控制
# ============================================================
@app.get("/api/admin/bot/status")
def api_bot_status(admin=Depends(current_admin)):
    active = "unknown"
    try:
        active = subprocess.run(["systemctl", "is-active", "ding-stream-bot"],
                                capture_output=True, text=True, timeout=8).stdout.strip()
    except Exception as e:
        active = "error: %s" % e
    last = ""
    try:
        last = subprocess.run(["journalctl", "-u", "ding-stream-bot", "-n", "1",
                               "--no-pager", "-o", "cat"],
                              capture_output=True, text=True, timeout=8).stdout.strip()
    except Exception:
        pass
    cfg = get_config()
    return {"code": 200, "data": {
        "active": active,
        "last_log": last,
        "app_key": cfg.get("bot_app_key", ""),
        "channel": cfg.get("im_channel", "ding"),
        "wecom_configured": bool(cfg.get("wecom_corp_id") and cfg.get("wecom_secret")
                                 and cfg.get("wecom_token") and cfg.get("wecom_aes_key")),
        "ha_configured": bool(cfg.get("ha_token")),
        "ha_base_url": cfg.get("ha_base_url", ""),
    }}


@app.post("/api/admin/bot/restart")
def api_bot_restart(admin=Depends(current_admin)):
    try:
        r = subprocess.run(["systemctl", "restart", "ding-stream-bot"],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            raise HTTPException(status_code=500, detail=r.stderr.strip() or "重启失败")
        time.sleep(2)
        active = subprocess.run(["systemctl", "is-active", "ding-stream-bot"],
                                capture_output=True, text=True, timeout=8).stdout.strip()
        return {"code": 200, "active": active}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 静态页面
# ============================================================
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


def _page(name):
    p = os.path.join(BASE_DIR, name)
    if not os.path.exists(p):
        return JSONResponse({"code": 404, "msg": "%s 不存在" % name}, status_code=404)
    # 每次都要回源校验，避免挂墙设备刷新后仍命中旧页面缓存
    return FileResponse(p, media_type="text/html; charset=utf-8",
                        headers={"Cache-Control": "no-cache, must-revalidate"})


@app.api_route("/", methods=["GET", "HEAD"])
def page_index():
    return _page("index.html")


@app.api_route("/admin", methods=["GET", "HEAD"])
@app.api_route("/admin.html", methods=["GET", "HEAD"])
def page_admin():
    return _page("admin.html")


init_db()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8002, reload=False)
