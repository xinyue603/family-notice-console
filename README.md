# 家庭通知中控台

一个面向家庭的**消息通知与状态播报中控台**：把钉钉 / 企业微信里的重要消息汇聚到一块「家庭通知看板」，并叠加 Home Assistant 的家庭状态（谁在家、用电、温度、灯光、空调、电视）与天气，支持大屏循环展示与语音播报。

> 适合放在家里的电视 / 平板 / 树莓派上做「家庭信息屏」，也适合想自己掌控消息与数据的人自建。

---

## 功能特性

- **家庭通知看板**
  - 消息以卡片流呈现，支持彩色标签（紧急通知 / 作业 / 今日菜单 / 采购 / 日程 / 普通通知 …）、发送人、群名、图片、置顶。
  - 顶部**天气条**跑马灯：显示位置天气与今日温度范围（数据来自 Home Assistant 或中国天气网城市）。
  - **家庭状态卡**：在家成员（x/y）、用电总功率与分路、各房间温度范围、当前开着的灯 / 空调 / 电视。
  - **自动语音播报**：新消息可调用浏览器 TTS 朗读（可在后台开关）。
  - 深色 / 浅色主题、自动刷新、自适应大屏与竖屏。
- **管理后台**（网页）
  - 系统设置：主题、播报、显示、消息保留天数、图片清理、数据备份 / 恢复。
  - 标签管理：自定义标签的名称、图标、颜色、顺序、是否在看板显示。
  - 消息管理：查看 / 删除 / 置顶，清理无引用图片。
  - 机器人设置：消息接入方式（钉钉 Stream / 企业微信回调）与对应凭证。
  - **HA 智能接入管理**：总开关、家庭数据源（连接测试）、设备映射、成员与传感器映射（均可在后台维护，无需改代码）。
  - 设置天气位置：跟随 HA 或手动指定城市。
- **消息接入**
  - **钉钉**：通过钉钉 Stream 机器人长连接实时接收文本 / 图片 / 富文本。
  - **企业微信**：通过企业微信应用回调接收消息。
- **Home Assistant 集成**：只读聚合家庭状态，支持灯 / 空调 / 电视以及成员在线、用电、温度等传感器，全部可在后台配置映射到看板。
- **天气**：双数据源——Home Assistant 的 `weather.*` 实体，或中国天气网城市接口（免密钥）。
- **数据安全**：消息与图片存于本地 SQLite + 本地目录，完全私有化，不上传任何第三方。

---

## 系统架构

```
                 ┌─────────────┐         ┌──────────────┐
   钉钉消息  ───▶ │ 钉钉 Stream │         │  企业微信回调  │
                 │  机器人      │         │  (公网 HTTPS) │
                 └──────┬──────┘         └──────┬───────┘
                        │  POST /api/message/add      │ POST /wecom/callback
                        └──────────────┬──────────────┘
                                       ▼
                            ┌──────────────────────────┐
                            │   家庭通知中控台 (FastAPI)  │
                            │   main.py  :8002          │
                            │  · 看板 / 后台 静态托管      │
                            │  · 消息 / 标签 / 配置 / HA   │
                            │  · 天气双源                 │
                            └───────┬──────────┬────────┘
                                    │          │ REST API
                          SQLite     │          │ (只读聚合)
                       notify.db ◀───┘          ▼
                                       Home Assistant
                                       (家庭状态 / 天气)

   浏览器 ──▶ / (看板)   /admin (后台)   ◀── 家庭成员在电视 / 平板上查看
```

- **主服务** `main.py`：提供看板、后台与全部接口，并托管前端静态文件，监听 `0.0.0.0:8002`。
- **钉钉机器人** `ding_stream_bot.py`：独立进程，维持钉钉长连接，把消息推给主服务。可与原服务同机运行，也可用 Docker Compose 的第二个服务。
- **企业微信**：由主服务的 `/wecom/callback` 接收，无需独立进程（需公网回调地址）。

---

## 目录结构

```
家庭通知中控台/
├── README.md                 # 本文件
├── LICENSE                   # MIT 许可证
├── requirements.txt          # Python 依赖
├── Dockerfile                # Docker 镜像构建
├── docker-compose.yml        # Docker Compose（主服务 + 钉钉机器人）
├── config.example.json       # 配置项参考（实际配置存数据库，后台填写）
├── .gitignore
├── main.py                   # 后端主服务（FastAPI）
├── ding_stream_bot.py        # 钉钉 Stream 机器人
├── media.py                  # 图片压缩与落盘
├── index.html                # 看板前端（已构建，自包含）
├── admin.html                # 管理后台前端（已构建，自包含）
├── admin_body.html           # 后台 HTML 源
├── admin.js                  # 后台交互逻辑
├── board.js                  # 看板交互逻辑
├── build_admin.py            # 由源重建 admin.html
├── build_index.py            # 由源重建 index.html
├── prototype/                # 前端 CSS 源（dashboard.html / admin.html）
├── deploy/                   # systemd 单元示例（直接部署用）
│   ├── notify.service
│   └── ding-stream-bot.service
└── demo/
    └── 家庭通知中控台-demo.html  # 离线可开的完整演示（含示例数据，无需后端）
```

> 前端默认已构建好（`index.html` / `admin.html` 自包含，可直接部署）。若要修改界面，改 `admin_body.html` / `admin.js` / `board.js` / `prototype/` 后重跑 `build_admin.py` / `build_index.py` 重新生成。

---

## 快速开始

### 方式一：直接部署（Python 源码，适合长期驻留的家庭服务器）

适合已有 Linux 主机（如家庭 NAS、迷你主机、树莓派）并希望像系统服务一样常驻的场景。

```bash
# 1. 准备 Python 3.11+
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. 启动主服务（看板 + 后台 + 消息接口）
python main.py
#   默认监听 http://0.0.0.0:8002

# 3.（可选）另开一个终端启动钉钉机器人（仅用钉钉推送时需要）
python ding_stream_bot.py
```

打开 `http://<本机IP>:8002` 查看看板，`http://<本机IP>:8002/admin` 进入管理后台完成初始化。

生产环境建议用 `deploy/` 下的 systemd 单元把两个进程注册为系统服务，并前置 Nginx 做 HTTPS 反代（见下文「生产环境建议」）。

### 方式二：Docker / Docker Compose（适合快速体验与迁移）

```bash
# 仅启动主服务（看板 + 后台；如需钉钉推送再单独起机器人或改用 compose）
docker build -t family-notice-console .
docker run -d --name fnc -p 8002:8002 \
  -v fnc-data:/app/data \
  family-notice-console
```

使用 Compose（含钉钉机器人，**两个服务共享同一份数据卷**）：

```bash
docker compose up -d
```

- 主服务：`http://<宿主机IP>:8002`
- 数据（SQLite 与上传图片）持久化在命名卷 `fnc-data` 中，容器重建不丢数据。
- 不使用钉钉推送时，可只启动主服务：`docker compose up -d notify`。

---

## 初始配置（管理后台）

首次打开 `/admin` 后，按需填写：

1. **机器人设置**：选择接入方式（钉钉 / 企业微信），填入对应的 AppKey / AppSecret 等凭证（Secret 类字段**只在后台填写，不要写入任何文件或提交到仓库**）。
2. **HA 智能接入管理**：填入 Home Assistant 的地址与长期访问令牌，点「测试连接」；可按需在「设备映射」「成员与传感器映射」里把 HA 实体映射到看板（不填则用内置示例）。
3. **设置天气位置**：选择跟随 HA 或手动指定城市（城市代码可用中国天气网地址栏的 `101xxxxxx`）。
4. 其余（标签、主题、播报、消息保留天数等）均可在后台随时调整。

> 配置项完整清单见 `config.example.json`（仅作参考，实际配置存于数据库）。

---

## 消息接入

### 钉钉
- 在钉钉开放平台创建**企业内部应用**，开启「机器人」能力，拿到 **AppKey / AppSecret**。
- 在后台「机器人设置」填好并保存，重启钉钉机器人进程（`ding_stream_bot.py` 或 Docker 的 `bot` 服务）。
- 机器人以 **Stream 模式**长连接接收文本、图片、富文本；携带发送人昵称、员工 ID、群名。
- 标签语法：`#标签:内容`（冒号或空格均可），无标签消息按「普通通知」处理；开头 `@机器人` 会被自动剥离。

### 企业微信
- 在企业微信创建自建应用，拿到 **CorpId / AgentId / Secret / Token / EncodingAESKey**。
- 在后台「机器人设置」选择企业微信并填写，将应用的「接收消息」回调地址配置为 `https://<你的公网域名>/wecom/callback`。
- 企业微信需要公网可达的 HTTPS 回调地址（家庭内网需端口映射 / 内网穿透）。

---

## Home Assistant 集成

- 在 HA 中创建**长期访问令牌**（Settings → 人员 → 底部「长期访问令牌」）。
- 后台填入 HA 地址（如 `http://homeassistant.local:8123`）与令牌，点「测试连接」验证。
- 看板「家庭状态」卡通过**只读聚合** HA 的 `states` 生成：
  - 灯（light / switch）、空调（climate）、电视（media_player）按名称白名单显示「开着的」设备；
  - 成员在线、用电（总表 + 分路）、房间温度可在后台「成员与传感器映射」中按 `sensor.*` 实体维护，无需改代码、无需重启。
- 若关闭 HA 总开关，看板隐藏「家庭状态」卡；天气会自动退回手动城市取数（未配置城市时后台会提示填写）。

---

## 天气配置

- **跟随 HA**：使用 HA 中的 `weather.*` 实体（met.no 等），位置取自 HA 的 `location_name`。
- **手动城市**：关闭 HA 或单独指定时，按中国天气网城市代码（如 `101020100` 上海）取数，免密钥。
- 顶部天气条每 `weather_interval`（默认 600 秒）刷新并带缓存与失败冷却，不会频繁打外网。

---

## 生产环境建议（直接部署）

- **systemd**：参考 `deploy/notify.service` 与 `deploy/ding-stream-bot.service`，把两个进程注册为系统服务，开机自启、崩溃自动重启。
- **反向代理 + HTTPS**：用 Nginx / Caddy 将 `/admin` 与 `/wecom/callback` 暴露到公网（HTTPS），看板可仅限内网。
- **凭证**：所有 Secret 仅在后台填写，存于数据库；`.gitignore` 已排除 `notify.db`、上传目录、`.env`、`config.json` 等，切勿提交。
- **备份**：后台「数据管理」可导出 / 导入数据库；上传图片在 `uploads/` 目录，建议一并定期备份。

---

## 安全须知

- 本软件默认**无任何鉴权**即可查看看板；管理后台（`/admin`）的登录口令请在首次部署时设置（后端基于 SQLite 存哈希）。
- **不要**将 `notify.db`、`.env`、`config.json`、`uploads/` 提交到任何公开仓库。
- 钉钉 / 企业微信 / Home Assistant 的 **AppKey、AppSecret、Token、AESKey、HA 令牌**属于敏感凭证，仅在管理后台填写，绝不要写进代码或文档。
- 对外暴露前请务必配置 HTTPS 与管理员口令，并尽量把看板限制在可信网络内。

---

## 许可证

本项目以 **MIT 许可证** 开源，详见 [LICENSE](./LICENSE)。
