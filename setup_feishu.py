#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键初始化飞书多维表格

做三件事：
1. 在你的飞书云空间创建 Base「平台热点捕捉系统」
2. 创建两张表：每日热点池（11 个字段）、爆款拆解池（16 个字段），字段选项全部预设好
3. 把生成的 app_token / table_id 写进 config.yaml

用法：
    python3 setup_feishu.py

前置条件：
    - 已安装 lark-cli，并已登录（lark-cli auth login）
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.yaml"

BASE_NAME = "平台热点捕捉系统"
HOT_TABLE_NAME = "每日热点池"
VIRAL_TABLE_NAME = "爆款拆解池"

# ====================================
# 表结构定义
# ====================================
HOT_POOL_FIELDS = [
    {"name": "热点标题", "type": "text"},
    {"name": "采集日期", "type": "datetime"},
    {"name": "平台", "type": "select", "multiple": False, "options": [
        {"name": "抖音"}, {"name": "小红书"}, {"name": "B站"}, {"name": "视频号"},
        {"name": "公众号"}, {"name": "YouTube"}, {"name": "百度"}, {"name": "微博"},
        {"name": "今日头条"}, {"name": "网易新闻"}, {"name": "腾讯新闻"}, {"name": "少数派"},
        {"name": "掘金"}, {"name": "IT之家"}, {"name": "GitHub"}, {"name": "知乎"},
        {"name": "X"}, {"name": "V2EX"}, {"name": "Hacker News"},
    ]},
    {"name": "品类标签", "type": "select", "multiple": True, "options": [
        {"name": "数码"}, {"name": "AI/人工智能"}, {"name": "通用热点"},
    ]},
    {"name": "热度值", "type": "number"},
    {"name": "热度趋势", "type": "select", "multiple": False, "options": [
        {"name": "上升"}, {"name": "平稳"}, {"name": "下降"},
    ]},
    {"name": "时效窗口", "type": "select", "multiple": False, "options": [
        {"name": "24h内"}, {"name": "48h内"}, {"name": "7天内"},
    ]},
    {"name": "内容链接", "type": "text"},
    {"name": "简要描述", "type": "text"},
    {"name": "追热点建议", "type": "select", "multiple": False, "options": [
        {"name": "强烈推荐"}, {"name": "推荐跟进"}, {"name": "可以看看"}, {"name": "观望"},
    ]},
    {"name": "采集来源", "type": "select", "multiple": False, "options": [
        {"name": "TrendRadar"}, {"name": "TikHub API"}, {"name": "手动录入"},
        {"name": "NewsBing"}, {"name": "免费热榜"},
    ]},
]

VIRAL_POOL_FIELDS = [
    {"name": "视频标题", "type": "text"},
    {"name": "采集日期", "type": "datetime"},
    {"name": "平台", "type": "select", "multiple": False, "options": [
        {"name": "抖音"}, {"name": "小红书"}, {"name": "B站"}, {"name": "视频号"}, {"name": "YouTube"},
    ]},
    {"name": "品类标签", "type": "select", "multiple": True, "options": [
        {"name": "数码"}, {"name": "AI/人工智能"},
    ]},
    {"name": "视频链接", "type": "text"},
    {"name": "点赞数", "type": "number"},
    {"name": "评论数", "type": "number"},
    {"name": "转发数", "type": "number"},
    {"name": "收藏数", "type": "number"},
    {"name": "拆解评分", "type": "number"},
    {"name": "选题钩子", "type": "text"},
    {"name": "冲突/反差", "type": "text"},
    {"name": "套路公式", "type": "text"},
    {"name": "可复制点", "type": "text"},
    {"name": "AI拆解摘要", "type": "text"},
    {"name": "采集来源", "type": "select", "multiple": False, "options": [
        {"name": "TikHub API"}, {"name": "手动录入"},
    ]},
]


def run_cli(args, timeout=120):
    """调用 lark-cli 并返回解析后的 JSON"""
    try:
        proc = subprocess.run(["lark-cli"] + args, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        sys.exit("❌ 未找到 lark-cli。请先安装飞书 CLI 并完成登录。")
    except subprocess.TimeoutExpired:
        sys.exit("❌ lark-cli 执行超时，请检查网络或登录状态。")

    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip()[:400]
        raise RuntimeError(f"lark-cli 执行失败：{msg}")

    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"lark-cli 返回的不是 JSON：{proc.stdout[:300]}")


def check_login():
    """检查飞书登录状态"""
    print("→ 检查飞书登录状态...")
    try:
        result = run_cli(["auth", "status", "--as", "user"])
        ok = result.get("ok", True)
        if not ok:
            sys.exit("❌ 飞书未登录。请先执行：lark-cli auth login")
        print("  ✓ 已登录")
    except RuntimeError as e:
        print("  ⚠️ 无法确认登录状态，继续尝试（若失败请先执行 lark-cli auth login）")


def create_base():
    """创建 Base 和每日热点池表，返回 base_token"""
    print(f"→ 创建 Base「{BASE_NAME}」和「{HOT_TABLE_NAME}」表...")
    result = run_cli([
        "base", "+base-create",
        "--name", BASE_NAME,
        "--table-name", HOT_TABLE_NAME,
        "--time-zone", "Asia/Shanghai",
        "--fields", json.dumps(HOT_POOL_FIELDS, ensure_ascii=False),
        "--as", "user",
    ])
    data = result.get("data", {})
    base = data.get("base") or {}
    base_token = base.get("base_token") or data.get("base_token") or data.get("app_token")
    if not base_token:
        raise RuntimeError(f"未能从返回结果中拿到 base_token：{json.dumps(result, ensure_ascii=False)[:300]}")
    print(f"  ✓ Base 已创建：{base_token}")
    url = base.get("url") or ""
    if url:
        print(f"  ✓ 链接：{url}")
    return base_token, url


def create_viral_table(base_token):
    """创建爆款拆解池表"""
    print(f"→ 创建「{VIRAL_TABLE_NAME}」表...")
    run_cli([
        "base", "+table-create",
        "--base-token", base_token,
        "--name", VIRAL_TABLE_NAME,
        "--fields", json.dumps(VIRAL_POOL_FIELDS, ensure_ascii=False),
        "--as", "user",
    ])
    print("  ✓ 已创建")


def get_table_ids(base_token):
    """列出表，按名称取 table_id"""
    print("→ 获取 table_id...")
    result = run_cli(["base", "+table-list", "--base-token", base_token, "--as", "user"])
    tables = result.get("data", {}).get("tables") or []
    name_to_id = {t.get("name"): t.get("id") for t in tables}

    hot_id = name_to_id.get(HOT_TABLE_NAME)
    viral_id = name_to_id.get(VIRAL_TABLE_NAME)
    if not hot_id:
        raise RuntimeError(f"未找到「{HOT_TABLE_NAME}」表，现有表：{list(name_to_id.keys())}")
    print(f"  ✓ {HOT_TABLE_NAME}: {hot_id}")
    print(f"  ✓ {VIRAL_TABLE_NAME}: {viral_id}")
    return hot_id, viral_id


def write_config(base_token, hot_table_id, viral_table_id):
    """生成 config.yaml"""
    template = BASE_DIR / "config.example.yaml"
    if not template.exists():
        sys.exit("❌ 缺少 config.example.yaml，无法生成配置")

    content = template.read_text(encoding="utf-8")
    content = content.replace("__APP_TOKEN__", base_token)
    content = content.replace("__HOT_POOL_TABLE_ID__", hot_table_id)
    content = content.replace("__VIRAL_POOL_TABLE_ID__", viral_table_id or "")

    old = CONFIG_PATH.read_text(encoding="utf-8") if CONFIG_PATH.exists() else ""
    if CONFIG_PATH.exists():
        backup = CONFIG_PATH.with_suffix(".yaml.bak")
        backup.write_text(old, encoding="utf-8")
        print(f"→ 已备份原 config.yaml 为 {backup.name}")

    CONFIG_PATH.write_text(content, encoding="utf-8")
    print(f"  ✓ 已写入 {CONFIG_PATH.name}")


def main():
    print("=" * 56)
    print("飞书多维表格一键初始化")
    print("=" * 56)

    if not shutil.which("lark-cli"):
        sys.exit("❌ 未找到 lark-cli，请先安装并登录飞书 CLI。")

    check_login()

    base_token, base_url = create_base()
    try:
        create_viral_table(base_token)
    except RuntimeError as e:
        print(f"  ⚠️ 爆款拆解池创建失败（不影响主流程）：{e}")

    hot_id, viral_id = get_table_ids(base_token)
    write_config(base_token, hot_id, viral_id)

    print()
    print("=" * 56)
    print("✅ 初始化完成！")
    print(f"   飞书表格：{base_url or 'https://feishu.cn/base/' + base_token}")
    print()
    print("下一步：")
    print("   python3 trend_collector.py")
    print()
    print("需要付费数据（抖音/小红书）时，再编辑 config.yaml 填 TikHub API Key。")
    print("=" * 56)


if __name__ == "__main__":
    main()
