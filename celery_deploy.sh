#!/bin/bash

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
WORKSPACE_ROOT="$(dirname "$PROJECT_ROOT")"

CELERY_APP="celery_scheduler.celery_worker:celery"
CELERY_WORKER_CONCURRENCY=4
CELERY_WORKER_QUEUES="default"
CELERY_BEAT_SCHEDULER="redbeat.schedulers:RedBeatScheduler"
CELERY_LOG_DIR="${PROJECT_ROOT}/output/logs/celery"
mkdir -p "$CELERY_LOG_DIR"
CELERY_WORKER_LOG="${CELERY_LOG_DIR}/celery_worker.log"
CELERY_BEAT_LOG="${CELERY_LOG_DIR}/celery_beat.log"
CELERY_WORKER_PID="${PROJECT_ROOT}/celery_worker.pid"
CELERY_BEAT_PID="${PROJECT_ROOT}/celery_beat.pid"

# 优先使用 backend/.venv 中的 celery
if [ -x "${PROJECT_ROOT}/.venv/bin/celery" ]; then
    CELERY_BIN="${PROJECT_ROOT}/.venv/bin/celery"
elif command -v celery >/dev/null 2>&1; then
    CELERY_BIN="$(command -v celery)"
else
    echo "[ERROR] 未找到 celery 命令，请先安装依赖: cd backend && uv sync"
    exit 1
fi

# macOS 上 prefork 易触发多进程问题，使用 solo 池
CELERY_POOL_ARGS=()
if [ "$(uname -s)" = "Darwin" ]; then
    CELERY_POOL_ARGS=(--pool=solo)
    CELERY_WORKER_CONCURRENCY=1
fi

export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH}"

print_info() { echo -e "\033[32m[INFO]\033[0m $1"; }
print_warn() { echo -e "\033[33m[WARN]\033[0m $1"; }
print_error() { echo -e "\033[31m[ERROR]\033[0m $1"; }

print_log_tail() {
    local log_file=$1
    if [ -f "$log_file" ] && [ -s "$log_file" ]; then
        print_error "最近日志:"
        tail -n 20 "$log_file"
    fi
}

is_running() {
    local pid_file=$1
    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if ps -p "$pid" > /dev/null 2>&1; then
            return 0
        else
            rm -f "$pid_file"
        fi
    fi
    return 1
}

stop_process() {
    local pid_file=$1
    local process_name=$2
    if ! is_running "$pid_file"; then
        print_info "${process_name} 未运行(跳过)"
        return 1
    fi
    local pid=$(cat "$pid_file")
    print_info "停止 ${process_name}(PID: $pid)..."
    kill -TERM "$pid" 2>/dev/null
    local count=0
    while ps -p "$pid" > /dev/null 2>&1 && [ $count -lt 10 ]; do
        sleep 1
        count=$((count + 1))
    done
    if ps -p "$pid" > /dev/null 2>&1; then
        print_warn "${process_name} 未正常退出, 强制终止..."
        kill -9 "$pid" 2>/dev/null
    fi
    rm -f "$pid_file"
    print_info "${process_name} 已停止"
    return 0
}

start_celery_worker() {
    if is_running "$CELERY_WORKER_PID"; then
        print_warn "Celery Worker 已在运行(PID: $(cat "$CELERY_WORKER_PID"))"
        return 1
    fi
    : > "$CELERY_WORKER_LOG"
    print_info "启动 Celery Worker (并发: ${CELERY_WORKER_CONCURRENCY}, 队列: ${CELERY_WORKER_QUEUES})..."
    print_info "使用: $CELERY_BIN"
    cd "$PROJECT_ROOT" || exit 1
    "$CELERY_BIN" -A "$CELERY_APP" worker \
        --loglevel=info \
        --concurrency=${CELERY_WORKER_CONCURRENCY} \
        --queues=${CELERY_WORKER_QUEUES} \
        --logfile="$CELERY_WORKER_LOG" \
        --pidfile="$CELERY_WORKER_PID" \
        "${CELERY_POOL_ARGS[@]}" \
        --detach
    sleep 3
    if is_running "$CELERY_WORKER_PID"; then
        print_info "Celery Worker 启动成功(PID: $(cat "$CELERY_WORKER_PID"))"
        print_info "日志: $CELERY_WORKER_LOG"
        return 0
    fi
    print_error "Celery Worker 启动失败, 请查看日志: $CELERY_WORKER_LOG"
    print_log_tail "$CELERY_WORKER_LOG"
    return 1
}

start_celery_beat() {
    if is_running "$CELERY_BEAT_PID"; then
        print_warn "Celery Beat 已在运行(PID: $(cat "$CELERY_BEAT_PID"))"
        return 1
    fi
    : > "$CELERY_BEAT_LOG"
    print_info "启动 Celery Beat (调度器: ${CELERY_BEAT_SCHEDULER})..."
    cd "$PROJECT_ROOT" || exit 1
    "$CELERY_BIN" -A "$CELERY_APP" beat \
        --loglevel=info \
        --scheduler="$CELERY_BEAT_SCHEDULER" \
        --logfile="$CELERY_BEAT_LOG" \
        --pidfile="$CELERY_BEAT_PID" \
        --detach
    sleep 3
    if is_running "$CELERY_BEAT_PID"; then
        print_info "Celery Beat 启动成功(PID: $(cat "$CELERY_BEAT_PID"))"
        print_info "日志: $CELERY_BEAT_LOG"
        return 0
    fi
    print_error "Celery Beat 启动失败, 请查看日志: $CELERY_BEAT_LOG"
    print_log_tail "$CELERY_BEAT_LOG"
    return 1
}

celery_status() {
    echo "========== Celery 进程状态 =========="
    if is_running "$CELERY_WORKER_PID"; then
        echo "[✓] Celery Worker: 运行中(PID: $(cat "$CELERY_WORKER_PID"))"
    else
        echo "[×] Celery Worker: 未运行"
    fi
    if is_running "$CELERY_BEAT_PID"; then
        echo "[✓] Celery Beat: 运行中(PID: $(cat "$CELERY_BEAT_PID"))"
    else
        echo "[×] Celery Beat: 未运行"
    fi
    echo "日志: Worker=$CELERY_WORKER_LOG Beat=$CELERY_BEAT_LOG"
}

case "${1:-}" in
    start)
        start_celery_worker
        CELERY_BIN="$CELERY_BIN" bash "$PROJECT_ROOT/deploy/knowledge_workers.sh" start
        start_celery_beat
        ;;
    stop)
        CELERY_BIN="$CELERY_BIN" bash "$PROJECT_ROOT/deploy/knowledge_workers.sh" stop
        stop_process "$CELERY_WORKER_PID" "Celery Worker"
        stop_process "$CELERY_BEAT_PID" "Celery Beat"
        ;;
    restart)
        CELERY_BIN="$CELERY_BIN" bash "$PROJECT_ROOT/deploy/knowledge_workers.sh" stop
        stop_process "$CELERY_WORKER_PID" "Celery Worker"
        stop_process "$CELERY_BEAT_PID" "Celery Beat"
        sleep 2
        if [ -n "$2" ]; then CELERY_WORKER_CONCURRENCY=$2; fi
        start_celery_worker
        CELERY_BIN="$CELERY_BIN" bash "$PROJECT_ROOT/deploy/knowledge_workers.sh" start
        start_celery_beat
        ;;
    status) celery_status; CELERY_BIN="$CELERY_BIN" bash "$PROJECT_ROOT/deploy/knowledge_workers.sh" status ;;
    start-worker)
        if [ -n "$2" ]; then CELERY_WORKER_CONCURRENCY=$2; fi
        start_celery_worker
        ;;
    stop-worker) stop_process "$CELERY_WORKER_PID" "Celery Worker" ;;
    start-beat) start_celery_beat ;;
    stop-beat) stop_process "$CELERY_BEAT_PID" "Celery Beat" ;;
    *)
        echo "用法: $0 {start|stop|restart|status|start-worker|stop-worker|start-beat|stop-beat} [并发数]"
        exit 1
        ;;
esac
