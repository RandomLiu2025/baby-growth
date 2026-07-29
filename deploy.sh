#!/usr/bin/env bash
#
# 宝贝成长记 · 一键部署（Docker，内置 Caddy 自动 HTTPS，无需在宿主机安装 nginx/certbot）
#
#   本机访问（8000 端口）：   sudo bash deploy.sh
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

say "宝贝成长记 · 一键部署"

# 1) Docker
if ! command -v docker >/dev/null 2>&1; then
  say "安装 Docker"
  curl -fsSL https://get.docker.com | $SUDO sh
  $SUDO systemctl enable --now docker 2>/dev/null || true
fi
docker compose version >/dev/null 2>&1 || { echo "❌ 需要 docker compose 插件（Docker 20.10+）"; exit 1; }

# 2) .env（首次生成随机密钥，保留已有配置）
if [ ! -f .env ]; then
  say "生成 .env（随机密钥）"
  SECRET="$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  cat > .env <<EOF
SECRET_KEY=${SECRET}
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin123
MAX_IMAGE_MB=10
MAX_VIDEO_MB=200
EOF
  echo "  默认管理员 admin / admin123，登录后请尽快在「个人资料」修改密码。"
fi

# 3) 构建并启动（有域名则附带 Caddy 反代 + 自动 HTTPS）
PROFILE=""
if [ -n "$DOMAIN" ]; then
  upsert SITE_ADDRESS "$DOMAIN"
  PROFILE="--profile proxy"
  say "构建并启动（含 Caddy 自动 HTTPS · ${DOMAIN}）"
else
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
  say "完成！打开 http://${IP}:8000"
  echo "  默认管理员：admin / admin123（请尽快修改）"
  echo "  绑定域名 + 自动 HTTPS： sudo bash deploy.sh 你的域名"
fi
