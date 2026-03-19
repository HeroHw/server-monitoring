#!/bin/bash
# 每秒检测 new-api-3002 容器的 TIME_WAIT 连接数，超过阈值时推送飞书告警。
# 用法：
#   chmod +x monitor_timewait.sh
#   FEISHU_WEBHOOK_URL=https://open.feishu.cn/... ./monitor_timewait.sh
#   或在同目录放置 .env 文件，脚本会自动加载。

set -euo pipefail

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 加载同目录下的 .env（若存在）
if [[ -f "$SCRIPT_DIR/.env" ]]; then
    # 只导出非注释、非空行的 KEY=VALUE 对
    set -o allexport
    # shellcheck disable=SC1091
    source <(grep -E '^[A-Za-z_][A-Za-z0-9_]*=' "$SCRIPT_DIR/.env")
    set +o allexport
fi

CONTAINER="${CONTAINER:-new-api-3002}"
THRESHOLD="${TIMEWAIT_THRESHOLD:-27000}"
WEBHOOK_URL="${FEISHU_WEBHOOK_URL:-}"
SERVER_NAME="${SERVER_NAME:-$(hostname)}"
POLL_INTERVAL="${TIMEWAIT_POLL_INTERVAL:-1}"

# ---------------------------------------------------------------------------
# 验证
# ---------------------------------------------------------------------------
if [[ -z "$WEBHOOK_URL" ]]; then
    echo "[WARN] FEISHU_WEBHOOK_URL 未配置，告警将只打印到控制台不推送飞书。" >&2
fi

# ---------------------------------------------------------------------------
# 推送飞书
# ---------------------------------------------------------------------------
push_feishu() {
    local count="$1"
    local now
    now=$(TZ='Asia/Shanghai' date '+%Y-%m-%d %H:%M:%S')

    local payload
    payload=$(cat <<EOF
{
  "msg_type": "interactive",
  "card": {
    "config": {"wide_screen_mode": true},
    "header": {
      "title": {"tag": "plain_text", "content": "🚨 TIME_WAIT 告警 | ${SERVER_NAME}"},
      "template": "red"
    },
    "elements": [
      {
        "tag": "div",
        "fields": [
          {"is_short": true, "text": {"tag": "lark_md", "content": "**容器**\n${CONTAINER}"}},
          {"is_short": true, "text": {"tag": "lark_md", "content": "**监控项**\nTIME_WAIT 连接数"}},
          {"is_short": true, "text": {"tag": "lark_md", "content": "**当前值**\n${count}"}},
          {"is_short": true, "text": {"tag": "lark_md", "content": "**告警阈值**\n${THRESHOLD}"}},
          {"is_short": false, "text": {"tag": "lark_md", "content": "**告警时间**\n${now}"}}
        ]
      },
      {"tag": "hr"},
      {
        "tag": "note",
        "elements": [{"tag": "plain_text", "content": "指标恢复正常前不再重复推送此告警。"}]
      }
    ]
  }
}
EOF
)

    if [[ -n "$WEBHOOK_URL" ]]; then
        curl -s -o /dev/null -w "%{http_code}" \
            -H 'Content-Type: application/json' \
            -d "$payload" \
            "$WEBHOOK_URL" | grep -q '^2' \
            && echo "[$(TZ='Asia/Shanghai' date '+%H:%M:%S')] 飞书告警推送成功（TIME_WAIT=${count}）" \
            || echo "[$(TZ='Asia/Shanghai' date '+%H:%M:%S')] [WARN] 飞书推送失败" >&2
    else
        echo "[$(TZ='Asia/Shanghai' date '+%H:%M:%S')] [告警] TIME_WAIT=${count} 超过阈值 ${THRESHOLD}（飞书未配置，仅打印）"
    fi
}

# ---------------------------------------------------------------------------
# 主循环
# ---------------------------------------------------------------------------
echo "[$(TZ='Asia/Shanghai' date '+%H:%M:%S')] 启动 TIME_WAIT 监控 | 容器=${CONTAINER} | 阈值=${THRESHOLD} | 轮询=${POLL_INTERVAL}s"

alert_active=0   # 0=正常  1=告警中（已推送，等待恢复）

while true; do
    # 获取 TIME_WAIT 数量；命令失败时跳过本轮
    if ! count=$(docker exec "$CONTAINER" sh -c "ss -tan state time-wait | wc -l" 2>/dev/null); then
        echo "[$(TZ='Asia/Shanghai' date '+%H:%M:%S')] [WARN] docker exec 失败，容器可能未运行，跳过本轮" >&2
        sleep "$POLL_INTERVAL"
        continue
    fi

    # wc -l 输出含首行表头，实际连接数 = count - 1（最小取 0）
    count=$(( count > 0 ? count - 1 : 0 ))

    ts=$(TZ='Asia/Shanghai' date '+%H:%M:%S')
    echo "[${ts}] TIME_WAIT=${count}"

    if (( count > THRESHOLD )); then
        if (( alert_active == 0 )); then
            alert_active=1
            push_feishu "$count"
        fi
    else
        if (( alert_active == 1 )); then
            alert_active=0
            echo "[$(TZ='Asia/Shanghai' date '+%H:%M:%S')] TIME_WAIT 已恢复正常（${count} <= ${THRESHOLD}）"
        fi
    fi

    sleep "$POLL_INTERVAL"
done
