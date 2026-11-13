#!/usr/bin/env bash
# 快捷运行：采集今日热点并写入飞书
set -e
cd "$(dirname "$0")"
python3 trend_collector.py
