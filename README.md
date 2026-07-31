# 宝贝成长记 · Baby Growth 🍼

一个可自行部署的**全栈**宝贝成长记录网站：记录成长历程、展示照片、标记里程碑、追踪身高体重与日常喂养，并带有一个支持**语音**和**大模型**的智能助手。

- 后端：**Python + FastAPI + SQLAlchemy + SQLite**，使用 HttpOnly Cookie 会话鉴权
- 前端：**Vue 3 + ECharts（固定版本、本站托管、无需构建）**，由后端直接提供静态资源
- 部署：一条 `docker compose up` 即可，数据以单个 SQLite 文件 + uploads 目录持久化，备份只需复制 `data/`

> 想先看效果？仓库内 `standalone/index.html` 是一个纯前端单文件版本（数据存浏览器本地），双击即可在浏览器打开体验全部界面，无需后端。

---

## ✨ 功能一览

**前台（登录后浏览）**
- 首页：动画背景 Hero + 照片轮播 + 最近里程碑（轮播仅加载当前图片，并尊重系统“减少动态效果”偏好）
- 成长时间线：竖向时间线 + 滚动动画 + 年份筛选
- 照片画廊：相册总览 → 相册详情 → 灯箱预览（相册 / 里程碑 / 日记均支持**图片与视频**，灯箱内可播放，服务端支持 Range 断点续传，可拖动进度）。上传图片会清除常见元数据，HEIC 自动转换为 JPEG，并生成 `_thumb` 缩略图；**列表/网格用缩略图 + 懒加载**加速，原图仅在灯箱/详情按需加载（缩略图缺失时自动回退原图）；没有封面的视频先显示零请求占位，打开预览后才加载视频
- 成长视频：独立视频专区（缩略图网格 + 播放详情页）。上传支持断点恢复和阶段进度，合并校验后由后台生成封面并按浏览器兼容性处理：MOV、MKV 等兼容编码无损封装为 MP4，HEVC、MPEG-4 Part 2 等转为 MP4/H.264/AAC，已兼容的 MP4/WebM 保持原样
- 成长曲线：ECharts 身高体重趋势图 + 数据表格
- 日常记录：喂奶/换尿布/粑粑统计 + 预计奶量进度条 + 距上次喂奶时间 + 时间线
- 成长日记：图文日记
- 留言墙：访客留言（**审核后**展示）
- 关于：宝贝 & 家庭简介

**管理端（管理员登录后）**
- 里程碑、相册（批量上传照片）、身高体重、宝贝信息、日记、日常记录 的增删改；相册、日常和日记历史按 50 条分页加载
- 留言审核（通过 / 删除）
- 成员管理支持禁用、启用、删除和重置家庭成员密码；重置后该成员全部旧会话立即失效
- 显示设置：主题配色、背景装饰开关与透明度、功能模块开关、首页区块开关、默认喂奶参数、预计每日奶量、AI 配置、恢复示例数据
- 登录页支持记住用户名；登录令牌保存在 HttpOnly Cookie，不暴露给页面 JavaScript

**AI 智能助手（每页右下角悬浮窗）**
- 语音输入 + 朗读（浏览器 Web Speech API，Chrome / Edge 效果最佳）
- 内置指令模式：查询年龄/身高体重/喂奶统计/最近里程碑等；登录后可语音「记录一次喂奶 150」直接写库
- 可选大模型：在管理端填入 OpenAI 兼容的 API Key / Base URL / 模型后，升级为自然语言对话，并可通过工具调用记录数据（写操作需管理员登录）

**登录与权限**
- **全站需登录才能查看**：未登录只能看到登录/注册页，所有数据接口都要求认证。
- **仅凭管理员邀请码注册**：新用户注册时必须填写管理员生成的邀请码；一码一用，用后作废。
- **两种角色**：管理员（admin，可管理全部内容 + 生成/撤销邀请码）与家庭成员（member，可查看 + 留言）。管理员账号由 `.env` 的 `ADMIN_USERNAME/ADMIN_PASSWORD` 初始化。
- 管理端「🎟️ 邀请码管理」可生成、查看、撤销邀请码。
- 用户在「个人资料」修改密码后，当前设备会自动续签登录态，其他设备上的旧会话立即失效。
- 家庭成员忘记密码时，管理员可在「成员管理」重置；管理员自身仍需在「个人资料」验证当前密码后修改。

**数据备份**
- 管理端「显示设置 → 文件与数据」支持创建和下载**完整备份**，同时包含 SQLite 一致性快照和上传文件，自动保留最近 **2** 份。
- JSON 导入先执行结构预检，确认后自动创建完整备份，再在单个事务中覆盖业务数据。
- 完整恢复必须停止应用后通过 CLI 执行，避免运行中的数据库连接指向旧文件。
- 可选 restic 加密异地备份与无损恢复演练，覆盖主机或整个数据卷丢失场景。

---

## 🧱 目录结构

```
baby-growth/
├─ server/                 # 后端（FastAPI）
│  ├─ app/
│  │  ├─ main.py           # 应用入口、业务路由与静态托管
│  │  ├─ routers/          # 认证、系统等领域 Router
│  │  ├─ models.py         # SQLAlchemy 数据模型
│  │  ├─ auth.py           # Cookie / Bearer 兼容、密码哈希与鉴权依赖
│  │  ├─ schemas.py        # 写接口 Pydantic 请求模型
│  │  ├─ media_storage.py  # 媒体引用扫描与安全清理
│  │  ├─ backup.py         # 完整备份、校验和恢复演练
│  │  ├─ ai.py             # AI 助手（内置指令 + 大模型代理）
│  │  ├─ sampledata.py     # 示例数据
│  │  ├─ defaults.py       # 默认设置
│  │  ├─ config.py / db.py # 配置与数据库
│  ├─ seed.py              # 初始化 + 填充示例数据
│  ├─ requirements.txt
│  └─ .env.example
├─ client/                 # 免构建前端、业务模块与固定版本依赖
│  ├─ index.html           # 静态入口
│  ├─ app.js               # 页面与业务编排
│  ├─ api.js               # API 客户端
│  ├─ defaults.js          # 前端默认配置
│  ├─ upload-utils.js      # 上传校验和并发工具
│  └─ components.js        # 可复用基础组件
├─ standalone/
│  └─ index.html           # 纯前端离线版（数据存浏览器，双击即用）
├─ deploy-local.sh         # 本地非 Docker 安装与进程管理
├─ Dockerfile
├─ docker-compose.yml
└─ README.md
```

---

## 🚀 快速开始（本地开发）

需要 Python 3.10+（推荐 3.12）和 [uv](https://docs.astral.sh/uv/)。

```bash
cd server
uv venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
uv pip install -r requirements.txt

cp .env.example .env             # 按需修改密钥与管理员账号
python seed.py                   # 可选：填充示例数据（会重置内容）

uvicorn app.main:app --reload --port 8000
```

打开 http://localhost:8000 即可访问。开发环境默认账号为 **admin / admin123**；生产环境会拒绝默认密钥和默认密码。

FastAPI 自动接口文档：http://localhost:8000/docs

---

## 💻 本地非 Docker 部署

适用于 macOS、Linux 和 WSL，需要 [uv](https://docs.astral.sh/uv/) 以及 Python 3.12。首次执行会创建 `.local_runtime/venv`、安装依赖、生成随机密钥和管理员密码，并在后台启动服务：

```bash
./deploy-local.sh
```

常用管理命令：

```bash
./deploy-local.sh install          # 仅安装/更新依赖，保留已有 .env
./deploy-local.sh start            # 后台启动并等待 /api/ready
./deploy-local.sh status           # 查看 PID 和访问地址
./deploy-local.sh logs --follow    # 持续查看日志
./deploy-local.sh restart
./deploy-local.sh stop
./deploy-local.sh seed --yes       # 停止服务后，备份并重置示例数据
```

默认仅监听 `127.0.0.1:8000`。可通过命令环境变量覆盖：

```bash
HOST=0.0.0.0 PORT=9000 ./deploy-local.sh start
```

- 数据保存在 `./data`，运行文件保存在 `.local_runtime/`，应用配置保存在 `.env`。
- 首次生成的管理员密码只显示一次，请妥善保存并在登录后修改。
- 缺少 ffmpeg 不影响启动，但视频会保留原文件并提示兼容性风险，且无法上传需要转换的 HEIC 图片。
- 监听所有网卡时请配置防火墙；公网部署应增加 HTTPS 反向代理并设置 `SESSION_COOKIE_SECURE=true`。只有应用端口不对不可信网络开放、请求必经可信代理时才设置 `TRUST_PROXY_HEADERS=true`。
- Docker 与本地进程不要同时使用同一个 SQLite 数据目录，切换前先停止另一种部署方式。

---

## 🐳 Docker 部署（推荐）

### 一键脚本

```bash
sudo bash deploy.sh                    # 本机 8000 端口访问
sudo bash deploy.sh baby.example.com   # 绑定域名 + 内置 Caddy 自动 HTTPS
```
自动完成：安装 Docker → 生成随机签名密钥、AI 数据加密密钥和管理员密码（写入 `.env`，密码仅显示一次）→ 构建并启动 →（询问）填充示例数据 →（给了域名时）启动内置 **Caddy 容器**做反向代理并**自动申请/续期 HTTPS**（无需在宿主机安装 Nginx / Certbot）。

> 手动带 HTTPS 也可：先在 `.env` 设置 `SITE_ADDRESS=baby.example.com`、`SESSION_COOKIE_SECURE=true`、`TRUST_PROXY_HEADERS=true`，再执行 `docker compose --profile proxy up -d --build`（需域名已解析、放行 80/443）。

### 手动步骤

```bash
# 在仓库根目录
cp .env.example .env
# 编辑 .env，填写 SECRET_KEY、DATA_ENCRYPTION_KEY 和 ADMIN_PASSWORD
docker compose up -d --build

# 首次如需示例数据：
docker compose exec app python seed.py
```

- Compose 默认只绑定 `127.0.0.1:8000`，本机访问 http://127.0.0.1:8000；需要直接从局域网访问时显式设置 `APP_BIND_ADDRESS=0.0.0.0`
- 数据持久化在宿主机 `./data`（`baby.db` + `uploads/`）；恢复 AI 配置还必须安全保留 `.env` 中的 `DATA_ENCRYPTION_KEY`
- 完整备份保存在 `./data/backups`；数据库升级、JSON 导入和示例数据重置前会自动备份
- Compose 使用 `/api/ready` 检查数据库和数据目录是否可用
- 生产模式缺少安全的 `SECRET_KEY` 或仍使用 `admin123` 时，服务会拒绝启动
- HTTPS 代理部署需设置 `SESSION_COOKIE_SECURE=true` 和 `TRUST_PROXY_HEADERS=true`；`deploy.sh 域名` 会自动设置，直连模式会强制关闭代理头信任

---

## ⚙️ 环境变量

| 变量 | 说明 | 默认 |
|---|---|---|
| `APP_ENV` | 运行环境；Docker 固定为 production | development |
| `SECRET_KEY` | JWT 签名密钥，**生产务必改成随机长字符串** | change-me... |
| `DATA_ENCRYPTION_KEY` | AI API Key 落盘加密密钥，需与数据备份分开安全保存；留空时回退 `SECRET_KEY` | 空 |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 管理员账号（首次启动创建，之后不覆盖） | admin / admin123 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 登录令牌有效期（分钟） | 10080（7天） |
| `SESSION_COOKIE_SECURE` | HTTPS 部署设为 true | false |
| `APP_BIND_ADDRESS` | Compose 宿主机监听地址；直连局域网时才设为 `0.0.0.0` | 127.0.0.1 |
| `APP_TIMEZONE` | 全站业务时区；统一“今日”、日期展示、纪念日、疫苗提醒、AI 与成长小结 | Asia/Shanghai |
| `DATABASE_URL` | 数据库连接串 | sqlite:///./data/baby.db |
| `UPLOAD_DIR` | 上传文件目录 | ./data/uploads |
| `CORS_ORIGINS` | 允许的跨域来源（逗号分隔）；同源部署保持为空 | 空 |
| `TRUST_PROXY_HEADERS` | 是否信任 `X-Forwarded-For` 首个 IP；仅限可信反向代理部署 | false |
| `AI_ALLOW_PRIVATE_BASE_URLS` | 是否允许 AI Base URL 使用 HTTP 或私网地址 | false |
| `MAX_IMAGE_MB` / `MAX_VIDEO_MB` | 图片 / 视频上传大小上限（MB） | 10 / 200 |
| `MAX_UPLOAD_FILES` | 单次上传文件数上限 | 20 |
| `CHUNK_TTL_HOURS` | 未完成分片保留时间 | 24 |
| `MIN_UPLOAD_FREE_MB` | 上传完成后必须保留的最小磁盘空间（MB） | 512 |
| `MAX_IMAGE_PIXELS` | 单张图片最大总像素 | 100000000 |
| `MAX_VIDEO_DURATION_SECONDS` | 单个视频最大时长（秒，需 ffprobe） | 3600 |
| `MAX_VIDEO_PIXELS` / `MAX_VIDEO_FPS` | 视频单帧最大像素 / 最大帧率（需 ffprobe） | 8294400 / 60 |
| `MAX_CONCURRENT_UPLOADS` | 服务端同时处理的上传请求数 | 6 |
| `MAX_CONCURRENT_MEDIA_JOBS` | 同时执行的视频归一化/封面任务数 | 2 |
| `MEDIA_PROBE_TIMEOUT_SECONDS` | ffprobe 资源探测超时（秒） | 15 |
| `MEDIA_PROCESS_TIMEOUT_SECONDS` | 单个视频 remux/转码最长时间（秒） | 1800 |
| `BACKUP_DIR` / `BACKUP_RETENTION` | 完整备份目录 / 保留份数 | ./data/backups / 2 |
| `MAX_IMPORT_MB` | JSON 导入大小上限 | 20 |
| `MAX_IMPORT_RECORDS` | 单次导入记录总数上限 | 50000 |
| `AUTO_BACKUP_BEFORE_MIGRATION` | 数据库迁移前自动备份 | true |
| `RESTIC_REPOSITORY` / `RESTIC_PASSWORD` | 可选 restic 加密异地备份仓库与密码 | 空 |
| `CLIENT_DIR` | 前端静态目录（Docker 内已设置） | ../client |

生成随机密钥：`python -c "import secrets;print(secrets.token_hex(32))"`

---

## 🌐 生产部署建议

**反向代理 + HTTPS（Nginx 示例）**

```nginx
server {
    listen 80;
    server_name baby.example.com;
    client_max_body_size 220m;             # 200MiB 视频加 multipart 开销
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        # 应用信任首个值，因此边界代理必须覆盖而不是追加客户端自带头。
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

应用应只绑定 `127.0.0.1`，并在 `.env` 设置 `TRUST_PROXY_HEADERS=true`；不要在应用端口同时对公网开放，否则客户端可伪造转发头绕过登录限流。之后用 `certbot --nginx -d baby.example.com` 一键签发免费 HTTPS 证书。

**切换到 PostgreSQL**

```bash
pip install "psycopg[binary]"
export DATABASE_URL="postgresql+psycopg://user:password@localhost:5432/baby"
python seed.py
```

---

## 🔌 API 概览

| 方法 & 路径 | 说明 | 权限 |
|---|---|---|
| `POST /api/auth/login` | 登录，设置 HttpOnly Cookie，仅返回用户信息 | 公开 |
| `POST /api/auth/register` | 使用邀请码注册，设置 HttpOnly Cookie，仅返回用户信息 | 公开 |
| `GET /api/bootstrap` | 拉取完整数据，保留给旧客户端和兼容回退 | 登录用户 |
| `GET /api/bootstrap?compact=true` | 首屏轻量数据：相册/日记摘要及最近 200 条日常记录 | 登录用户 |
| `GET/POST /api/{milestones\|growth\|daily\|diary}` | 列表 / 新增 | 登录用户 / 管理员 |
| `GET /api/diary/{id}` | 按需读取完整日记正文和媒体 | 登录用户 |
| `GET /api/admin/history/{albums\|daily\|diary}` | 管理端稳定排序分页，支持 `limit` / `offset` | 管理员 |
| `PUT/DELETE /api/{res}/{id}` | 修改 / 删除 | 管理员 |
| `GET/POST/PUT/DELETE /api/albums[/id]` | 相册列表、单相册详情及管理（完整照片按需加载） | 登录用户 / 管理员 |
| `GET /api/baby` · `PUT /api/baby` | 宝贝信息 | 登录用户 / 管理员 |
| `GET /api/settings` · `PUT /api/settings` | 显示设置（所有响应均不返回 AI 密钥明文） | 登录用户 / 管理员 |
| `POST /api/users/{id}/reset-password` | 重置家庭成员密码并撤销其全部旧会话 | 管理员 |
| `POST /api/messages` | 家庭成员提交留言（待审核） | 登录用户 |
| `POST /api/messages/{id}/approve` · `DELETE` | 审核 / 删除留言 | 管理员 |
| `POST /api/upload` | 上传图片或视频（支持多文件） | 管理员 |
| `GET /api/upload/status/{uploadId}` | 查询已完成分片和视频处理状态，用于刷新恢复与结果回填 | 管理员 |
| `DELETE /api/upload/{uploadId}` | 取消未完成上传并清理分片 | 管理员 |
| `POST /api/upload/complete` | 合并分片并幂等返回结果；视频随后在后台归一化 | 管理员 |
| `POST /api/media/cleanup/preview` | 预览孤儿媒体、缺失引用和临时文件 | 管理员 |
| `POST /api/media/cleanup` | 验证确认令牌、重新扫描、备份后清理 | 管理员 |
| `GET /uploads/{name}` | 读取本地媒体 | 登录用户或对应相册分享 token |
| `GET/POST /api/backups` | 查看 / 创建完整备份 | 管理员 |
| `GET /api/backups/{id}/download` | 下载完整备份 | 管理员 |
| `POST /api/import/validate` | 预检 JSON 导入 | 管理员 |
| `POST /api/import?confirm=true` | 备份后事务导入 | 管理员 |
| `POST /api/ai/chat` | AI 助手对话 | 登录用户（写操作需管理员） |
| `POST /api/admin/seed` | 重置为示例数据 | 管理员 |
| `GET /api/health` · `GET /api/ready` | 进程存活 / 数据库与目录就绪检查 | 公开 |

---

## 🤖 AI 助手配置

1. 登录后进入「管理 → 显示设置 → AI 助手」：勾选「启用大模型」，填入 API Key、Base URL（OpenAI 兼容，如 `https://api.openai.com/v1`）、模型名，保存。
2. 密钥只保存在**服务器端**，所有设置响应只返回“已配置”状态；留空保存会保留原密钥，也可显式清除。
3. Base URL 默认必须是公网 HTTPS，且每次外呼前都会重新校验；局域网自建模型确有需要时才设置 `AI_ALLOW_PRIVATE_BASE_URLS=true`。
4. 未配置时自动使用内置指令助手（免费、离线可用）。
5. 原理：后端 `ai.py` 先用规则解析常见意图；启用大模型后携带实时数据快照与工具定义（记录喂奶/换尿布）调用大模型，模型可发起工具调用由后端执行（写操作校验管理员身份）。

---

## 🔒 安全说明

- 本项目面向**家庭自用**。浏览器使用 HttpOnly、SameSite Cookie 保存登录态；旧版本 localStorage JWT 会在首次启动时迁移并删除。
- 修改密码会递增服务端会话版本，当前设备续签 Cookie，其他旧 Cookie 和 Bearer Token 随即失效。
- 普通媒体要求登录；相册分享链接只允许访问对应相册引用的媒体。
- 服务端根据文件真实内容校验上传类型，并拒绝 SVG 和伪装文件。
- Vue 与 ECharts 固定版本由本站托管；响应启用 CSP、内容类型保护等安全头，HTTPS 代理额外启用 HSTS。
- 应用容器以非 root 用户运行；SQLite 默认启用外键、WAL 和 5 秒忙等待。
- CORS 默认仅允许同源，Compose 默认只监听宿主机回环地址；使用 Caddy 时应用端口不会直接暴露到公网。
- 部署到公网时请使用随机 `SECRET_KEY`、`DATA_ENCRYPTION_KEY` 与管理员密码，启用 HTTPS，并设置 `SESSION_COOKIE_SECURE=true`。
- 留言默认需管理员审核后才展示。

## 🧹 媒体扫描与清理

管理员可在「显示设置 → 文件与数据」先扫描孤儿媒体，再携带短时确认令牌执行清理。默认保护最近 24 小时文件，执行前会重新扫描并创建完整备份；数据库仍引用的文件不会删除。

## ♻️ 数据库升级与完整恢复

应用使用 Alembic 管理数据库版本。旧版 SQLite 首次升级时会先创建 `pre-migration` 完整备份，再将现有结构纳入基线版本，不会重建业务表。

查看和校验备份：

```bash
docker compose run --rm app python -m app.backup_cli list
docker compose run --rm app python -m app.backup_cli verify /app/server/data/backups/backup-xxx.zip
docker compose run --rm app python -m app.backup_cli drill /app/server/data/backups/backup-xxx.zip
```

完整恢复必须先停止应用：

```bash
docker compose stop app
docker compose run --rm app python -m app.backup_cli restore /app/server/data/backups/backup-xxx.zip
docker compose up -d app
```

恢复前会再创建一份 `pre-restore` 救援备份。不要在应用运行时直接替换 `baby.db`。恢复到新机器时需同步恢复原 `DATA_ENCRYPTION_KEY`；旧部署未配置该值时需保留原 `SECRET_KEY`，否则已加密的 AI API Key 无法解密，只能重新填写。

可选的加密异地备份使用 restic。配置 `.env` 中的 `RESTIC_REPOSITORY`、`RESTIC_PASSWORD` 及目标存储凭证后，可手动执行：

```bash
bash scripts/offsite-backup.sh
```

脚本会先创建并验证本地完整备份，再加密上传，保留 7 份日备、4 份周备和 12 份月备，并执行仓库完整性检查。生产环境可通过宿主机 cron 定时调用该脚本。

---

用 ❤️ 记录每一个成长瞬间。
