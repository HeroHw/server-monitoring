#!/usr/bin/env python3
"""
Linux 服务器监控脚本
每隔 POLL_INTERVAL 秒检测 CPU、内存、磁盘使用率，按三级阈值记录日志，
超过告警阈值时向飞书推送一次消息（指标恢复后重置，可再次推送）。
"""

import logging
import os
import socket
import time
from dataclasses import dataclass
from datetime import datetime
from logging.handlers import RotatingFileHandler

import psutil
import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

@dataclass
class Config:
    poll_interval: float
    cpu_safe: float
    cpu_warning: float
    cpu_alert: float
    mem_safe: float
    mem_warning: float
    mem_alert: float
    disk_safe: float
    disk_warning: float
    disk_alert: float
    feishu_webhook_url: str
    log_file: str
    server_name: str
    cpu_sustained: int
    mem_sustained: int
    disk_sustained: int


def _get_float(key: str, default: float) -> float:
    val = os.environ.get(key)
    if val is None:
        return default
    try:
        return float(val)
    except ValueError:
        raise ValueError(f"配置项 {key} 的值 '{val}' 不是有效的数字")


def load_config() -> Config:
    load_dotenv(override=True)

    cfg = Config(
        poll_interval=_get_float("POLL_INTERVAL", 5),
        cpu_safe=_get_float("CPU_SAFE", 50),
        cpu_warning=_get_float("CPU_WARNING", 75),
        cpu_alert=_get_float("CPU_ALERT", 90),
        mem_safe=_get_float("MEM_SAFE", 60),
        mem_warning=_get_float("MEM_WARNING", 80),
        mem_alert=_get_float("MEM_ALERT", 95),
        disk_safe=_get_float("DISK_SAFE", 70),
        disk_warning=_get_float("DISK_WARNING", 85),
        disk_alert=_get_float("DISK_ALERT", 95),
        feishu_webhook_url=os.environ.get("FEISHU_WEBHOOK_URL", "").strip(),
        log_file=os.environ.get("LOG_FILE", "monitor.log").strip(),
        server_name=os.environ.get("SERVER_NAME", socket.gethostname()).strip(),
        cpu_sustained=int(os.environ.get("CPU_SUSTAINED", 6)),
        mem_sustained=int(os.environ.get("MEM_SUSTAINED", 6)),
        disk_sustained=int(os.environ.get("DISK_SUSTAINED", 1)),
    )

    # 校验阈值顺序
    for prefix, label in [("cpu", "CPU"), ("mem", "内存"), ("disk", "磁盘")]:
        safe = getattr(cfg, f"{prefix}_safe")
        warning = getattr(cfg, f"{prefix}_warning")
        alert = getattr(cfg, f"{prefix}_alert")
        if not (safe < warning < alert):
            raise ValueError(
                f"{label} 阈值顺序不合法：safe={safe} warning={warning} alert={alert}，"
                f"必须满足 safe < warning < alert"
            )

    return cfg


# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------

def setup_logging(log_file: str) -> None:
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # 控制台
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    # 滚动文件（最大 5 MB，保留 3 个备份）
    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)


# ---------------------------------------------------------------------------
# 指标采集
# ---------------------------------------------------------------------------

@dataclass
class Metrics:
    cpu: float
    memory: float
    disk: float


def collect_metrics() -> Metrics:
    # cpu_percent(interval=1) 阻塞 1 秒以获得准确值
    return Metrics(
        cpu=psutil.cpu_percent(interval=1),
        memory=psutil.virtual_memory().percent,
        disk=psutil.disk_usage("/").percent,
    )


# ---------------------------------------------------------------------------
# 阈值分类
# ---------------------------------------------------------------------------

LEVEL_NONE = None
LEVEL_INFO = "INFO"
LEVEL_WARNING = "WARNING"
LEVEL_CRITICAL = "CRITICAL"


def classify(value: float, safe: float, warning: float, alert: float) -> str | None:
    if value <= safe:
        return LEVEL_NONE
    if value <= warning:
        return LEVEL_INFO
    if value <= alert:
        return LEVEL_WARNING
    return LEVEL_CRITICAL


# ---------------------------------------------------------------------------
# 日志输出
# ---------------------------------------------------------------------------

_METRIC_NAMES = {
    "cpu": "CPU 使用率",
    "memory": "内存使用率",
    "disk": "磁盘使用率（/）",
}

_ALERT_LABELS = {
    "cpu": ("安全", "预警", "告警"),
    "memory": ("安全", "预警", "告警"),
    "disk": ("安全", "预警", "告警"),
}


def log_metric(metric: str, value: float, level: str | None,
               safe: float, warning: float, alert: float) -> None:
    if level is None:
        return

    name = _METRIC_NAMES[metric]
    if level == LEVEL_INFO:
        msg = f"{name} {value:.1f}%  [超安全阈值 {safe}%]"
        logging.info(msg)
    elif level == LEVEL_WARNING:
        msg = f"{name} {value:.1f}%  [超预警阈值 {warning}%]"
        logging.warning(msg)
    elif level == LEVEL_CRITICAL:
        msg = f"{name} {value:.1f}%  [超告警阈值 {alert}%] ⚠"
        logging.critical(msg)


# ---------------------------------------------------------------------------
# 飞书推送
# ---------------------------------------------------------------------------

def push_feishu(webhook_url: str, metric: str, value: float,
                alert_threshold: float, hostname: str) -> None:
    if not webhook_url:
        return

    name = _METRIC_NAMES[metric]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    payload = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"🚨 服务器告警 | {hostname}"},
                "template": "red",
            },
            "elements": [
                {
                    "tag": "div",
                    "fields": [
                        {
                            "is_short": True,
                            "text": {"tag": "lark_md", "content": f"**监控项**\n{name}"},
                        },
                        {
                            "is_short": True,
                            "text": {"tag": "lark_md", "content": f"**当前值**\n{value:.1f}%"},
                        },
                        {
                            "is_short": True,
                            "text": {"tag": "lark_md", "content": f"**告警阈值**\n{alert_threshold}%"},
                        },
                        {
                            "is_short": True,
                            "text": {"tag": "lark_md", "content": f"**告警时间**\n{now}"},
                        },
                    ],
                },
                {"tag": "hr"},
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": "指标恢复正常前不再重复推送此告警。",
                        }
                    ],
                },
            ],
        },
    }

    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        logging.info(f"飞书告警推送成功（{name} {value:.1f}%）")
    except requests.RequestException as e:
        logging.warning(f"飞书告警推送失败：{e}")


# ---------------------------------------------------------------------------
# 主循环
# ---------------------------------------------------------------------------

def main() -> None:
    cfg = load_config()
    setup_logging(cfg.log_file)

    hostname = cfg.server_name
    logging.info(f"监控启动 | 主机：{hostname} | 轮询间隔：{cfg.poll_interval}s | 日志：{cfg.log_file}")

    # 告警去重状态：False = 正常，True = 告警中（已推送，等待恢复）
    alert_state: dict[str, bool] = {"cpu": False, "memory": False, "disk": False}

    # 持续超阈值计数器（次数从 .env 读取，次数 × 轮询间隔 = 持续秒数）
    alert_counter: dict[str, int] = {"cpu": 0, "memory": 0, "disk": 0}
    SUSTAINED_THRESHOLD = {"cpu": cfg.cpu_sustained, "memory": cfg.mem_sustained, "disk": cfg.disk_sustained}

    # 每个指标的阈值配置
    thresholds = {
        "cpu":    (cfg.cpu_safe,  cfg.cpu_warning,  cfg.cpu_alert),
        "memory": (cfg.mem_safe,  cfg.mem_warning,  cfg.mem_alert),
        "disk":   (cfg.disk_safe, cfg.disk_warning, cfg.disk_alert),
    }

    try:
        while True:
            # collect_metrics 内部 cpu_percent(interval=1) 已阻塞 1 秒
            metrics = collect_metrics()
            values = {"cpu": metrics.cpu, "memory": metrics.memory, "disk": metrics.disk}

            for metric, (safe, warning, alert) in thresholds.items():
                value = values[metric]
                level = classify(value, safe, warning, alert)

                # 写日志
                log_metric(metric, value, level, safe, warning, alert)

                # 告警状态机
                is_critical = level == LEVEL_CRITICAL
                if is_critical:
                    if not alert_state[metric]:
                        alert_counter[metric] += 1
                        if alert_counter[metric] >= SUSTAINED_THRESHOLD[metric]:
                            # 持续超阈值达标，推送飞书
                            alert_state[metric] = True
                            alert_counter[metric] = 0
                            push_feishu(cfg.feishu_webhook_url, metric, value, alert, hostname)
                else:
                    # 指标恢复，重置计数器和状态
                    if alert_counter[metric] > 0:
                        alert_counter[metric] = 0
                    if alert_state[metric]:
                        alert_state[metric] = False
                        logging.info(f"{_METRIC_NAMES[metric]} 已恢复至告警阈值以下（当前 {value:.1f}%）")

            # 补偿 cpu_percent 已耗用的 1 秒
            remaining = cfg.poll_interval - 1
            if remaining > 0:
                time.sleep(remaining)

    except KeyboardInterrupt:
        logging.info("收到终止信号，监控退出。")
    except Exception as e:
        logging.critical(f"监控异常退出：{e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
