# 宝贝成长记 · Baby Growth 🍼

一个可自行部署的**全栈**宝贝成长记录网站：记录成长历程、展示照片、标记里程碑、追踪身高体重与日常喂养，并带有一个支持**语音**和**大模型**的智能助手。

- 后端：**Python + FastAPI + SQLAlchemy + SQLite**（可切换 Postgres），JWT 登录鉴权
- 前端：**Vue 3（CDN，无需构建）+ ECharts**，由后端直接托管
- 部署：一条 `docker compose up` 即可，数据以单个 SQLite 文件 + uploads 目录持久化，备份只需复制 `data/`

> 想先看效果？仓库内 `standalone/index.html` 是一个纯前端单文件版本（数据存浏览器本地），双击即可在浏览器打开体验全部界面，无需后端。

---

## ✨ 功能一览

**前台（公开访问）**
- 首页：动画背景 Hero + 照片轮播 + 最近里程碑
- 成长时间线：竖向时间线 + 滚动动画 + 年份筛选
- 照片画廊：相册总览 → 相册详情 → 灯箱预览（相册 / 里程碑 / 日记均支持**图片与视频**，灯箱内可播放，服务端支持 Range 断点续传，可拖动进度）。上传图片时后端用 ffmpeg 额外生成 `_thumb` 缩略图，**列表/网格用缩略图 + 懒加载**加速，原图仅在灯箱/详情按需加载（缩略图缺失时自动回退原图）
- 成长视频：独立视频专区（缩略图网格 + 播放详情页）。上传视频时后端用 **ffmpeg 自动截取一帧作封面**（Docker 镜像已内置 ffmpeg；本地无 ffmpeg 时自动降级为视频首帧）。上传带**进度条**并有大小/类型校验
- 成长曲线：ECharts 身高体重趋势图 + 数据表格
- 日常记录：喂奶/换尿布/粑粑统计 + 预计奶量进度条 + 距上次喂奶时间 + 时间线
- 成长日记：图文日记
- 留言墙：访客留言（**审核后**展示）
- 关于：宝贝 & 家庭简介

**后台（登录后）**
- 里程碑、相册（批量上传照片）、身高体重、宝贝信息、日记、日常记录 的增删改
- 留言审核（通过 / 删除）
- 显示设置：主题配色、背景装饰开关与透明度、功能模块开关、首页区块开关、默认喂奶参数、预计每日奶量、AI 配置、恢复示例数据
- 登录页支持「记住账号/密码」（明文存于该设备浏览器 localStorage，适合家庭常用设备）

**AI 智能助手（每页右下角悬浮窗）**
- 语音输入 + 朗读（浏览器 Web Speech API，Chrome / Edge 效果最佳）
- 内置指令模式：查询年龄/身高体重/喂奶统计/最近里程碑等；登录后可语音「记录一次喂奶 150」直接写库
- 可选大模型：在后台填入 OpenAI 兼容的 API Key / Base URL / 模型后，升级为自然语言对话，并可通过工具调用记录数据（写操作需管理员登录）

**登录与权限**
- **全站需登录才能查看**：未登录只能看到登录/注册页，所有数据接口都要求认证。
- **仅凭管理员邀请码注册**：新用户注册时必须填写管理员生成的邀请码；一码一用，用后作废。
- **两种角色**：管理员（admin，可管理全部内容 + 生成/撤销邀请码）与家庭成员（member，可查看 + 留言）。管理员账号由 `.env` 的 `ADMIN_USERNAME/ADMIN_PASSWORD` 初始化。
- 后台「🎟️ 邀请码管理」可生成、查看、撤销邀请码。

**数据备份**
- 后台「显示设置 → 文件与数据」支持**一键导出全部数据为 JSON** 与**导入恢复**（覆盖当前数据），方便备份与迁移。
- JSON 仅含结构化数据，**不含照片/视频文件**；完整备份请同时保留 `data/uploads` 目录（或整个 `data/`）。

---

## 🧱 目录结构

```
baby-growth/
├─ server/                 # 后端（FastAPI）
│  ├─ app/
│  │  ├─ main.py           # 应用入口 + 全部路由 + 静态托管
│  │  ├─ models.py         # SQLAlchemy 数据模型
│  │  ├─ auth.py           # JWT / 密码哈希 / 鉴权依赖
│  │  ├─ ai.py             # AI 助手（内置指令 + 大模型代理）
│  │  ├─ sampledata.py     # 示例数据
│  │  ├─ defaults.py       # 默认设置
│  │  ├─ config.py / db.py # 配置与数据库
│  ├─ seed.py              # 初始化 + 填充示例数据
│  ├─ requirements.txt
│  └─ .env.example
├─ client/
│  └─ index.html           # 前端（Vue3 CDN，单文件，由后端托管）
├─ standalone/
│  └─ index.html           # 纯前端离线版（数据存浏览器，双击即用）
├─ Dockerfile
├─ docker-compose.yml
└─ README.md
```

---

## 🚀 快速开始（本地开发）

需要 Python 3.10+（推荐 3.12）。

```bash
cd server
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # 按需修改密钥与管理员账号
python seed.py                   # 可选：填充示例数据（会重置内容）

uvicorn app.main:app --reload --port 8000
```

打开 http://localhost:8000 即可访问前台。点击导航栏「🔑 后台」登录，默认账号 **admin / admin123**（在 `.env` 中修改）。

FastAPI 自动接口文档：http://localhost:8000/docs

---

## 🐳 Docker 部署（推荐）

### 一键脚本

```bash
sudo bash deploy.sh                    # 本机 8000 端口访问
sudo bash deploy.sh baby.example.com   # 绑定域名 + 内置 Caddy 自动 HTTPS
```
自动完成：安装 Docker → 生成随机密钥（写入 `.env`）→ 构建并启动 →（询问）填充示例数据 →（给了域名时）启动内置 **Caddy 容器**做反向代理并**自动申请/续期 HTTPS**（无需在宿主机安装 Nginx / Certbot）。

> 手动带 HTTPS 也可：`SITE_ADDRESS=baby.example.com docker compose --profile proxy up -d --build`（需域名已解析、放行 80/443）。

### 手动步骤

```bash
# 在仓库根目录
docker compose up -d --build

# 首次如需示例数据：
docker compose exec app python seed.py
```

- 访问 http://服务器IP:8000
- 数据持久化在宿主机 `./data`（`baby.db` + `uploads/`），**备份只需复制该目录**
- 修改 `docker-compose.yml` 里的 `SECRET_KEY`、`ADMIN_USERNAME`、`ADMIN_PASSWORD` 后重启生效

---

## ⚙️ 环境变量

| 变量 | 说明 | 默认 |
|---|---|---|
| `SECRET_KEY` | JWT 签名密钥，**生产务必改成随机长字符串** | change-me... |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 管理员账号（首次启动创建，之后不覆盖） | admin / admin123 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 登录令牌有效期（分钟） | 10080（7天） |
| `DATABASE_URL` | 数据库连接串 | sqlite:///./data/baby.db |
| `UPLOAD_DIR` | 上传文件目录 | ./data/uploads |
| `CORS_ORIGINS` | 允许的跨域来源（逗号分隔） | * |
| `MAX_IMAGE_MB` / `MAX_VIDEO_MB` | 图片 / 视频上传大小上限（MB） | 10 / 200 |
| `CLIENT_DIR` | 前端静态目录（Docker 内已设置） | ../client |

生成随机密钥：`python -c "import secrets;print(secrets.token_hex(32))"`

---

## 🌐 生产部署建议

**反向代理 + HTTPS（Nginx 示例）**

```nginx
server {
    listen 80;
    server_name baby.example.com;
    client_max_body_size 200m;             # 允许较大照片 / 视频上传
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

之后用 `certbot --nginx -d baby.example.com` 一键签发免费 HTTPS 证书。

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
| `POST /api/auth/login` | 登录，返回 JWT | 公开 |
| `GET /api/bootstrap` | 一次性拉取全部数据（管理员含待审核留言/密钥） | 公开/管理员 |
| `GET/POST /api/{milestones\|growth\|daily\|diary}` | 列表 / 新增 | 读公开，写管理员 |
| `PUT/DELETE /api/{res}/{id}` | 修改 / 删除 | 管理员 |
| `GET/POST/PUT/DELETE /api/albums[/id]` | 相册（含照片数组） | 读公开，写管理员 |
| `GET /api/baby` · `PUT /api/baby` | 宝贝信息 | 读公开，写管理员 |
| `GET /api/settings` · `PUT /api/settings` | 显示设置（公开不返回 AI 密钥） | 读公开，写管理员 |
| `POST /api/messages` | 访客提交留言（待审核） | 公开 |
| `POST /api/messages/{id}/approve` · `DELETE` | 审核 / 删除留言 | 管理员 |
| `POST /api/upload` | 上传图片（支持多文件） | 管理员 |
| `POST /api/ai/chat` | AI 助手对话 | 公开（写操作需管理员） |
| `POST /api/admin/seed` | 重置为示例数据 | 管理员 |

---

## 🤖 AI 助手配置

1. 登录后台 → 显示设置 → AI 助手：勾选「启用大模型」，填入 API Key、Base URL（OpenAI 兼容，如 `https://api.openai.com/v1`）、模型名，保存。
2. 密钥只保存在**服务器端**，公开接口不会返回。
3. 未配置时自动使用内置指令助手（免费、离线可用）。
4. 原理：后端 `ai.py` 先用规则解析常见意图；启用大模型后携带实时数据快照与工具定义（记录喂奶/换尿布）调用大模型，模型可发起工具调用由后端执行（写操作校验管理员身份）。

---

## 🔒 安全说明

- 本项目面向**家庭自用**。「记住账号/密码」按需求以明文存于该设备浏览器 localStorage，请仅在自己的常用设备勾选。
- 部署到公网时请务必：修改 `SECRET_KEY` 与管理员密码、启用 HTTPS。
- 访客留言默认需管理员审核后才公开展示。

---

用 ❤️ 记录每一个成长瞬间。
