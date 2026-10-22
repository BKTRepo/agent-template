#!/bin/bash
# 解析和删除必须为两个不同 Worker；线程池允许解析任务创建可回收子进程。
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="${CELERY_BIN:-$ROOT/.venv/bin/celery}"
DIR="$ROOT/output/logs/celery"
mkdir -p "$DIR"
cd "$ROOT"
start_one() {
  local name="$1" queue="$2" concurrency="$3"
  if [ -f "$DIR/$name.pid" ] && kill -0 "$(cat "$DIR/$name.pid")" 2>/dev/null; then
    echo "$name already running"; return
  fi
  "$BIN" -A celery_scheduler.celery_worker:celery worker --pool=threads --concurrency="$concurrency" \
    --queues="$queue" --hostname="$name@%h" --pidfile="$DIR/$name.pid" \
    --logfile="$DIR/$name.log" --loglevel=INFO --detach
}
stop_one() {
  local name="$1" file="$DIR/$1.pid"
  if [ -f "$file" ]; then
    local pid="$(cat "$file")"
    # 避免陈旧 PID 文件终止无关服务。
    if ps -p "$pid" -o args= | grep -F -- "--hostname=$name@" >/dev/null; then kill -TERM "$pid"; fi
  fi
}
case "${1:-}" in
 start) start_one knowledge-parse knowledge_parse 1; start_one knowledge-delete knowledge_delete 2 ;;
 stop) stop_one knowledge-parse; stop_one knowledge-delete ;;
 status) "$BIN" -A celery_scheduler.celery_worker:celery inspect active_queues ;;
 *) echo "Usage: bash deploy/knowledge_workers.sh {start|stop|status}"; exit 1 ;;
esac
