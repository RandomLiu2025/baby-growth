#!/usr/bin/env bash
#
# 宝贝成长记 · 一键部署（Docker，内置 Caddy 自动 HTTPS，无需在宿主机安装 nginx/certbot）
#
#   本机访问（8030 端口）：   sudo bash deploy.sh
#   绑定域名 + 自动 HTTPS：   sudo bash deploy.sh baby.example.com
#
# 脚本：安装 Docker（如缺失）→ 生成随机密钥 → 构建并启动
#       →（可选）填充示例数据 →（给了域名时）用 Caddy 容器反代并自动签发/续期证书
#
set -euo pipefail
cd "$(dirname "$0")"

DOMAIN="${1:-}"
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
say(){ printf "\n\033[1;35m== %s ==\033[0m\n" "$1"; }
upsert(){ local k="$1" v="$2" f="${3:-.env}"; touch "$f"; if grep -q "^${k}=" "$f"; then sed -i "s|^${k}=.*|${k}=${v}|" "$f"; else echo "${k}=${v}" >> "$f"; fi; }
random_hex(){ local bytes="$1"; openssl rand -hex "$bytes" 2>/dev/null || head -c "$bytes" /dev/urandom | od -An -tx1 | tr -d ' \n'; }

say "宝贝成长记 · 一键部署"

# 1) Docker
if ! command -v docker >/dev/null 2>&1; then
  say "安装 Docker"
  curl -fsSL https://get.docker.com | $SUDO sh
  $SUDO systemctl enable --now docker 2>/dev/null || true
fi
docker compose version >/dev/null 2>&1 || { echo "❌ 需要 docker compose 插件（Docker 20.10+）"; exit 1; }

# 2) .env（首次生成随机密钥和管理员密码，保留已有配置）
if [ ! -f .env ]; then
  say "生成 .env（随机密钥和管理员密码）"
  SECRET="$(random_hex 32)"
  DATA_SECRET="$(random_hex 32)"
  ADMIN_PASS="$(random_hex 12)"
  cat > .env <<EOF
SECRET_KEY=${SECRET}
DATA_ENCRYPTION_KEY=${DATA_SECRET}
ADMIN_USERNAME=admin
ADMIN_PASSWORD=${ADMIN_PASS}
SESSION_COOKIE_SECURE=false
APP_BIND_ADDRESS=127.0.0.1
APP_TIMEZONE=Asia/Shanghai
CORS_ORIGINS=
TRUST_PROXY_HEADERS=false
AI_ALLOW_PRIVATE_BASE_URLS=false
MAX_IMAGE_MB=10
MAX_VIDEO_MB=200
MAX_UPLOAD_FILES=20
CHUNK_TTL_HOURS=24
MIN_UPLOAD_FREE_MB=512
MAX_IMAGE_PIXELS=100000000
MAX_VIDEO_DURATION_SECONDS=3600
MAX_VIDEO_PIXELS=8294400
MAX_VIDEO_FPS=60
MAX_CONCURRENT_UPLOADS=6
MAX_CONCURRENT_MEDIA_JOBS=2
MEDIA_PROBE_TIMEOUT_SECONDS=15
MEDIA_PROCESS_TIMEOUT_SECONDS=1800
BACKUP_RETENTION=2
MAX_IMPORT_MB=20
MAX_IMPORT_RECORDS=50000
AUTO_BACKUP_BEFORE_MIGRATION=true
EOF
  echo "  初始管理员：admin"
  echo "  初始密码：${ADMIN_PASS}"
  echo "  请妥善保存，并在首次登录后修改密码。"
fi
if ! grep -Eq '^DATA_ENCRYPTION_KEY=.{32,}$' .env; then
  say "生成 AI 数据加密密钥"
  upsert DATA_ENCRYPTION_KEY "$(random_hex 32)"
fi

# 3) 构建并启动（有域名则附带 Caddy 反代 + 自动 HTTPS）
PROFILE=""
if [ -n "$DOMAIN" ]; then
  upsert SITE_ADDRESS "$DOMAIN"
  upsert SESSION_COOKIE_SECURE true
  upsert APP_BIND_ADDRESS 127.0.0.1
  upsert TRUST_PROXY_HEADERS true
  PROFILE="--profile proxy"
  say "构建并启动（含 Caddy 自动 HTTPS · ${DOMAIN}）"
else
  upsert APP_BIND_ADDRESS 0.0.0.0
  upsert TRUST_PROXY_HEADERS false
  say "构建并启动"
fi
# shellcheck disable=SC2086
$SUDO docker compose $PROFILE up -d --build

# 4) 可选：填充示例数据
printf "\n是否填充示例数据？（首次体验推荐） [y/N] "
read -r ANS || true
case "${ANS:-N}" in
  y|Y) say "填充示例数据"; $SUDO docker compose exec -T app python seed.py || true ;;
esac

# 5) 完成提示
if [ -n "$DOMAIN" ]; then
  say "完成！打开 https://${DOMAIN}"
  echo "  Caddy 正在自动申请证书，首次约需 30–60 秒。"
  echo "  请确保：域名已解析到本机公网 IP，且安全组/防火墙已放行 80 与 443。"
else
  IP="$(curl -s -m3 ifconfig.me 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}' || echo localhost)"
  say "完成！打开 http://${IP}:8030"
  echo "  管理员账号：admin（初始密码见 .env，请妥善保管）"
  echo "  绑定域名 + 自动 HTTPS： sudo bash deploy.sh 你的域名"
fi
