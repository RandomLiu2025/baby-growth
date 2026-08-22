#!/usr/bin/env bash
# 宝贝成长记 · 本地非 Docker 部署与进程管理
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVER_DIR="$ROOT_DIR/server"
ENV_FILE="$ROOT_DIR/.env"
REQUIREMENTS_FILE="$SERVER_DIR/requirements.txt"

RUNTIME_INPUT="${LOCAL_RUNTIME_DIR:-.local_runtime}"
case "$RUNTIME_INPUT" in
  /*) RUNTIME_DIR="$RUNTIME_INPUT" ;;
  *) RUNTIME_DIR="$ROOT_DIR/$RUNTIME_INPUT" ;;
esac

VENV_DIR="$RUNTIME_DIR/venv"
VENV_PYTHON="$VENV_DIR/bin/python"
UVICORN_BIN="$VENV_DIR/bin/uvicorn"
PID_FILE="$RUNTIME_DIR/baby-growth.pid"
ADDRESS_FILE="$RUNTIME_DIR/baby-growth.address"
LOG_FILE="$RUNTIME_DIR/baby-growth.log"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8030}"
STARTUP_TIMEOUT="${STARTUP_TIMEOUT:-30}"
STOP_TIMEOUT="${STOP_TIMEOUT:-10}"

say() {
  printf '\n== %s ==\n' "$1"
}

info() {
  printf '%s\n' "$1"
}

warn() {
  printf '⚠️  %s\n' "$1" >&2
}

die() {
  printf '❌ %s\n' "$1" >&2
  exit "${2:-1}"
}

usage() {
  cat <<'EOF'
宝贝成长记 · 本地非 Docker 部署

用法：
  ./deploy-local.sh                 首次安装并启动
  ./deploy-local.sh install         创建虚拟环境、安装依赖并生成安全配置
  ./deploy-local.sh start           后台启动服务并等待 readiness
  ./deploy-local.sh stop            停止当前工作区服务
  ./deploy-local.sh restart         重启服务
  ./deploy-local.sh status          查看运行状态
  ./deploy-local.sh logs [--follow] 查看日志，--follow 持续跟随
  ./deploy-local.sh seed [--yes]    停止状态下重置为示例数据
  ./deploy-local.sh help            显示帮助

可选环境变量：
  HOST=127.0.0.1  PORT=8000  LOCAL_RUNTIME_DIR=.local_runtime
  STARTUP_TIMEOUT=30  STOP_TIMEOUT=10
EOF
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "缺少 $1。$2"
}

validate_number() {
  local value="$1" name="$2" min="$3" max="$4"
  [[ "$value" =~ ^[0-9]+$ ]] || die "$name 必须是整数：$value"
  [ "$value" -ge "$min" ] && [ "$value" -le "$max" ] \
    || die "$name 必须在 $min-$max 之间：$value"
}

random_hex() {
  local bytes="$1"
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$bytes"
  else
    head -c "$bytes" /dev/urandom | od -An -tx1 | tr -d ' \n'
  fi
}

env_value() {
  local key="$1" fallback="$2" line=""
  if [ -f "$ENV_FILE" ]; then
    line="$(grep -E "^${key}=" "$ENV_FILE" | tail -n 1 || true)"
  fi
  if [ -n "$line" ]; then
    printf '%s' "${line#*=}"
  else
    printf '%s' "$fallback"
  fi
}

write_env_if_missing() {
  if [ -f "$ENV_FILE" ]; then
    info "保留已有配置：$ENV_FILE"
    return
  fi

  local secret data_encryption_key admin_password old_umask
  secret="$(random_hex 32)"
  data_encryption_key="$(random_hex 32)"
  admin_password="$(random_hex 12)"
  old_umask="$(umask)"
  umask 077
  cat > "$ENV_FILE" <<EOF
APP_ENV=production
SECRET_KEY=${secret}
DATA_ENCRYPTION_KEY=${data_encryption_key}
ADMIN_USERNAME=admin
ADMIN_PASSWORD=${admin_password}
ACCESS_TOKEN_EXPIRE_MINUTES=10080
SESSION_COOKIE_SECURE=false
APP_TIMEZONE=Asia/Shanghai
DATABASE_URL=sqlite:///./data/baby.db
UPLOAD_DIR=./data/uploads
BACKUP_DIR=./data/backups
BACKUP_RETENTION=2
MAX_IMPORT_MB=20
MAX_IMPORT_RECORDS=50000
AUTO_BACKUP_BEFORE_MIGRATION=true
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
EOF
  umask "$old_umask"

  say "已生成安全配置"
  info "管理员账号：admin"
  info "初始密码：${admin_password}"
  info "请妥善保存，并在首次登录后修改密码。"
}

find_python() {
  local python_bin version_ok
  python_bin="$(uv python find 3.12 2>/dev/null || true)"
  [ -n "$python_bin" ] || die "未找到 Python 3.12。请先执行：uv python install 3.12"
  version_ok="$("$python_bin" -c 'import sys; print(int(sys.version_info >= (3, 12)))' 2>/dev/null || true)"
  [ "$version_ok" = "1" ] || die "需要 Python 3.12 或更高版本：$python_bin"
  printf '%s' "$python_bin"
}

install_app() {
  require_command uv "安装方式：https://docs.astral.sh/uv/"
  [ -f "$REQUIREMENTS_FILE" ] || die "找不到依赖文件：$REQUIREMENTS_FILE"

  local python_bin
  python_bin="$(find_python)"
  mkdir -p "$RUNTIME_DIR" "$ROOT_DIR/data/uploads" "$ROOT_DIR/data/backups"

  if [ ! -x "$VENV_PYTHON" ]; then
    say "创建 Python 虚拟环境"
    uv venv --python "$python_bin" "$VENV_DIR"
  fi

  say "安装后端依赖"
  uv pip install --python "$VENV_PYTHON" -r "$REQUIREMENTS_FILE"
  [ -x "$UVICORN_BIN" ] || die "依赖安装完成但未找到 uvicorn：$UVICORN_BIN"

  write_env_if_missing
  if ! command -v ffmpeg >/dev/null 2>&1; then
    warn "未检测到 ffmpeg，视频封面与缩略图生成功能将降级。"
  fi

  say "安装完成"
  info "运行目录：$RUNTIME_DIR"
  info "数据目录：$ROOT_DIR/data"
}

process_alive() {
  local pid="$1" state=""
  kill -0 "$pid" >/dev/null 2>&1 || return 1
  state="$(ps -p "$pid" -o stat= 2>/dev/null | tr -d ' ' || true)"
  [[ "$state" != Z* ]]
}

managed_process() {
  local pid="$1" command_line=""
  process_alive "$pid" || return 1
  command_line="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  [[ "$command_line" == *"app.main:app"* ]]
}

read_pid() {
  local pid=""
  [ -f "$PID_FILE" ] || return 1
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ "$pid" =~ ^[0-9]+$ ]] && managed_process "$pid"; then
    printf '%s' "$pid"
    return 0
  fi
  rm -f "$PID_FILE" "$ADDRESS_FILE"
  return 1
}

ready_host() {
  case "$HOST" in
    0.0.0.0|::|"[::]") printf '127.0.0.1' ;;
    *) printf '%s' "$HOST" ;;
  esac
}

ready() {
  local url="http://$(ready_host):${PORT}/api/ready"
  if command -v curl >/dev/null 2>&1; then
    curl -fsS --max-time 2 "$url" >/dev/null 2>&1
  else
    "$VENV_PYTHON" -c \
      'import sys, urllib.request; urllib.request.urlopen(sys.argv[1], timeout=2).read(1)' \
      "$url" >/dev/null 2>&1
  fi
}

stop_pid() {
  local pid="$1" elapsed=0
  process_alive "$pid" || return 0
  kill "$pid" >/dev/null 2>&1 || true
  while process_alive "$pid" && [ "$elapsed" -lt "$STOP_TIMEOUT" ]; do
    sleep 1
    elapsed=$((elapsed + 1))
  done
  if process_alive "$pid"; then
    warn "进程未在 ${STOP_TIMEOUT} 秒内退出，发送 SIGKILL。"
    kill -9 "$pid" >/dev/null 2>&1 || true
  fi
}

start_app() {
  validate_number "$PORT" PORT 1 65535
  validate_number "$STARTUP_TIMEOUT" STARTUP_TIMEOUT 1 600
  validate_number "$STOP_TIMEOUT" STOP_TIMEOUT 1 120
  [ -x "$VENV_PYTHON" ] && [ -x "$UVICORN_BIN" ] \
    || die "尚未安装，请先执行：./deploy-local.sh install"
  [ -f "$ENV_FILE" ] || die "缺少 $ENV_FILE，请先执行 install"

  local existing_pid="" pid="" elapsed=0 app_env
  if existing_pid="$(read_pid)"; then
    info "服务已在运行（PID ${existing_pid}）：$(cat "$ADDRESS_FILE" 2>/dev/null || printf 'http://%s:%s' "$HOST" "$PORT")"
    return 0
  fi

  mkdir -p "$RUNTIME_DIR"
  app_env="${APP_ENV:-$(env_value APP_ENV production)}"
  if [ "$HOST" = "0.0.0.0" ] || [ "$HOST" = "::" ]; then
    warn "服务将监听所有网络接口；公网使用前请配置 HTTPS 和防火墙。"
  fi

  printf '\n[%s] 启动 HOST=%s PORT=%s APP_ENV=%s\n' \
    "$(date '+%Y-%m-%d %H:%M:%S')" "$HOST" "$PORT" "$app_env" >> "$LOG_FILE"
  (
    cd "$ROOT_DIR"
    APP_ENV="$app_env" PYTHONUNBUFFERED=1 nohup "$UVICORN_BIN" app.main:app \
      --app-dir "$SERVER_DIR" --host "$HOST" --port "$PORT" \
      >> "$LOG_FILE" 2>&1 </dev/null &
    printf '%s\n' "$!" > "$PID_FILE.tmp"
    printf 'http://%s:%s\n' "$HOST" "$PORT" > "$ADDRESS_FILE.tmp"
    mv "$PID_FILE.tmp" "$PID_FILE"
    mv "$ADDRESS_FILE.tmp" "$ADDRESS_FILE"
  )
  pid="$(cat "$PID_FILE")"

  while [ "$elapsed" -lt "$STARTUP_TIMEOUT" ]; do
    if ! managed_process "$pid"; then
      rm -f "$PID_FILE" "$ADDRESS_FILE"
      warn "启动失败，进程已退出。最近日志："
      tail -n 30 "$LOG_FILE" >&2 || true
      return 1
    fi
    if ready; then
      say "启动成功"
      info "访问地址：http://${HOST}:${PORT}"
      info "日志文件：$LOG_FILE"
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done

  warn "启动失败：${STARTUP_TIMEOUT} 秒内 readiness 未就绪。最近日志："
  stop_pid "$pid"
  rm -f "$PID_FILE" "$ADDRESS_FILE"
  tail -n 30 "$LOG_FILE" >&2 || true
  return 1
}

stop_app() {
  validate_number "$STOP_TIMEOUT" STOP_TIMEOUT 1 120
  local pid=""
  if ! pid="$(read_pid)"; then
    info "服务未运行。"
    return 0
  fi
  stop_pid "$pid"
  rm -f "$PID_FILE" "$ADDRESS_FILE"
  say "已停止"
  info "PID ${pid} 已结束。"
}

status_app() {
  local pid=""
  if pid="$(read_pid)"; then
    info "服务正在运行（PID ${pid}）：$(cat "$ADDRESS_FILE" 2>/dev/null || printf 'http://%s:%s' "$HOST" "$PORT")"
    return 0
  fi
  info "服务未运行。"
  return 1
}

show_logs() {
  local mode="${1:-}"
  [ -f "$LOG_FILE" ] || die "日志文件尚不存在：$LOG_FILE"
  case "$mode" in
    "") tail -n 100 "$LOG_FILE" ;;
    --follow|-f) tail -n 100 -f "$LOG_FILE" ;;
    *) die "logs 仅支持 --follow" 2 ;;
  esac
}

seed_app() {
  local assume_yes="${1:-}"
  [ -x "$VENV_PYTHON" ] || die "尚未安装，请先执行 install"
  [ "$assume_yes" = "" ] || [ "$assume_yes" = "--yes" ] || die "seed 仅支持 --yes" 2
  if read_pid >/dev/null 2>&1; then
    die "服务正在运行。请先执行 stop，再重置示例数据。"
  fi
  if [ "$assume_yes" != "--yes" ]; then
    printf '此操作会备份后重置业务数据，确认继续？ [y/N] '
    read -r answer || true
    case "${answer:-N}" in
      y|Y) ;;
      *) info "已取消。"; return 0 ;;
    esac
  fi
  say "填充示例数据"
  (cd "$ROOT_DIR" && "$VENV_PYTHON" "$SERVER_DIR/seed.py")
}

command_name="${1:-deploy}"
case "$command_name" in
  deploy)
    install_app
    start_app
    ;;
  install) install_app ;;
  start) start_app ;;
  stop) stop_app ;;
  restart)
    stop_app
    start_app
    ;;
  status) status_app ;;
  logs) show_logs "${2:-}" ;;
  seed) seed_app "${2:-}" ;;
  help|-h|--help) usage ;;
  *)
    usage >&2
    die "未知命令：$command_name" 2
    ;;
esac
