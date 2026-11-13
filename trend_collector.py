#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
平台热点捕捉系统 - 每日热点采集脚本
核心逻辑：找当天爆火的低粉爆款，不是历史高赞内容
支持：抖音、小红书、B站、视频号、公众号、YouTube
"""

import os
import sys
import json
import time
import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import requests
import yaml

# ====================================
# 配置加载
# ====================================
BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.yaml"

def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

CONFIG = load_config()

# ====================================
# 日志配置
# ====================================
logging.basicConfig(
    level=getattr(logging, CONFIG["log"]["level"]),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(BASE_DIR / CONFIG["log"]["file"], encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ====================================
# TikHub API 客户端
# ====================================
class TikHubClient:
    def __init__(self):
        self.api_key = CONFIG["tikhub"]["api_key"]
        self.base_url = CONFIG["tikhub"]["base_url"]
        self.enabled = CONFIG["tikhub"]["enabled"]
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}"
        })

    def get(self, path, params=None):
        if not self.enabled:
            logger.info(f"TikHub API 已关闭，跳过 {path}")
            return None
        url = f"{self.base_url}{path}"
        try:
            resp = self.session.get(url, params=params, timeout=30)
            data = resp.json()
            if data.get("code") == 200:
                return data.get("data")
            else:
                logger.error(f"API错误 {path}: {data.get('detail', data)}")
                return None
        except Exception as e:
            logger.error(f"请求失败 {path}: {e}")
            return None


# ====================================
# 爆款指数计算器
# ====================================
class ViralScoreCalculator:
    """
    计算爆款指数
    核心逻辑：
    1. 时效性加权：发布时间越近，权重越高
    2. 低粉加权：粉丝少但点赞高 = 低粉爆款，额外加分
    3. 互动质量：赞藏比、评论率
    """

    @staticmethod
    def calculate(item, platform):
        """
        计算爆款得分（0-100分）
        权重分配：互动规模50% > 低粉爆款30% > 时效性20%
        核心理念：内容本身的热度最重要，新鲜度只是加分项
        """
        now = datetime.now().timestamp()
        publish_time = item.get("timestamp", now)
        hours_ago = (now - publish_time) / 3600

        likes = item.get("likes", 0)
        comments = item.get("comments", 0)
        collects = item.get("collects", 0)
        shares = item.get("shares", 0)
        fans = item.get("fans", 0)

        # ===== 1. 互动规模得分（50分）=====
        # 这是最核心的指标：内容到底火不火
        if platform == "小红书":
            if likes >= 10000:
                interaction_score = 50
            elif likes >= 5000:
                interaction_score = 42
            elif likes >= 2000:
                interaction_score = 35
            elif likes >= 1000:
                interaction_score = 28
            elif likes >= 500:
                interaction_score = 20
            elif likes >= 100:
                interaction_score = 12
            else:
                interaction_score = 5
        elif platform == "抖音":
            if likes >= 50000:
                interaction_score = 50
            elif likes >= 20000:
                interaction_score = 42
            elif likes >= 10000:
                interaction_score = 35
            elif likes >= 5000:
                interaction_score = 28
            elif likes >= 1000:
                interaction_score = 15
            else:
                interaction_score = 5
        else:
            interaction_score = min(50, likes / 200)

        # ===== 2. 低粉爆款加分（30分）=====
        # 粉丝少但点赞高 = 纯靠内容爆的，最有参考价值
        if fans > 0:
            like_fan_ratio = likes / fans
            if like_fan_ratio >= 1.0:
                fan_score = 30
            elif like_fan_ratio >= 0.5:
                fan_score = 22
            elif like_fan_ratio >= 0.2:
                fan_score = 15
            elif like_fan_ratio >= 0.1:
                fan_score = 8
            else:
                fan_score = 3
        else:
            # 不知道粉丝数，给中等分
            fan_score = 10

        # ===== 3. 时效性得分（20分）=====
        # 发布越近越好，但只是锦上添花
        if hours_ago <= 12:
            time_score = 20
        elif hours_ago <= 24:
            time_score = 16
        elif hours_ago <= 48:
            time_score = 12
        elif hours_ago <= 72:
            time_score = 8
        elif hours_ago <= 7*24:
            time_score = 4
        else:
            time_score = 0

        total = interaction_score + fan_score + time_score

        if total >= 75:
            level = "S级爆款"
        elif total >= 55:
            level = "A级潜力"
        elif total >= 35:
            level = "B级观察"
        else:
            level = "C级普通"

        return {
            "score": round(total, 1),
            "level": level,
            "hours_ago": round(hours_ago, 1),
            "time_score": time_score,
            "interaction_score": round(interaction_score, 1),
            "fan_score": fan_score
        }


# ====================================
# 免费热榜采集器（不需要付费API）
# ====================================
class FreeHotListCollector:
    """免费热榜聚合采集器"""

    @staticmethod
    def fetch_baidu_hot(count=20):
        """百度热搜（免费）"""
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15'}
            resp = requests.get('https://top.baidu.com/api/board?platform=wise&tab=realtime', headers=headers, timeout=10)
            data = resp.json()
            cards = data['data']['cards']
            hot_list = cards[0]['content'][0]['content']

            items = []
            for i, item in enumerate(hot_list[:count]):
                items.append({
                    "title": item.get("word", ""),
                    "hot_value": item.get("hot_score", 0),
                    "position": i + 1,
                    "url": item.get("url", ""),
                    "platform": "百度",
                    "source": "免费热榜"
                })
            logger.info(f"百度热搜采集到 {len(items)} 条")
            return items
        except Exception as e:
            logger.error(f"百度热搜采集失败: {e}")
            return []

    @staticmethod
    def fetch_bilibili_popular(count=20):
        """B站热门（免费）"""
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
            resp = requests.get(f'https://api.bilibili.com/x/web-interface/popular?ps={count}&pn=1', headers=headers, timeout=10)
            data = resp.json()
            items_raw = data.get('data', {}).get('list', [])

            items = []
            for i, item in enumerate(items_raw[:count]):
                items.append({
                    "title": item.get("title", ""),
                    "hot_value": item.get("stat", {}).get("view", 0),
                    "position": i + 1,
                    "url": item.get("short_link_v2", item.get("url", "")),
                    "platform": "B站",
                    "source": "免费热榜"
                })
            logger.info(f"B站热门采集到 {len(items)} 条")
            return items
        except Exception as e:
            logger.error(f"B站热门采集失败: {e}")
            return []

    @staticmethod
    def fetch_toutiao_hot(count=20):
        """今日头条热榜（免费）"""
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
            resp = requests.get('https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc', headers=headers, timeout=10)
            data = resp.json()
            items_raw = data.get('data', [])

            items = []
            for i, item in enumerate(items_raw[:count]):
                items.append({
                    "title": item.get("Title", ""),
                    "hot_value": item.get("HotValue", 0),
                    "position": i + 1,
                    "url": item.get("Url", ""),
                    "platform": "今日头条",
                    "source": "免费热榜"
                })
            logger.info(f"今日头条热榜采集到 {len(items)} 条")
            return items
        except Exception as e:
            logger.error(f"今日头条热榜采集失败: {e}")
            return []

    @staticmethod
    def fetch_163_hot(count=20):
        """网易新闻热榜（免费）"""
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
            resp = requests.get('https://api.m.mi.com/163/news/hot', headers=headers, timeout=10)
            data = resp.json()
            items_raw = data.get('info', [])

            items = []
            for i, item in enumerate(items_raw[:count]):
                items.append({
                    "title": item.get("title", ""),
                    "hot_value": 0,
                    "position": i + 1,
                    "url": item.get("link", ""),
                    "platform": "网易新闻",
                    "source": "免费热榜"
                })
            logger.info(f"网易新闻热榜采集到 {len(items)} 条")
            return items
        except Exception as e:
            logger.error(f"网易新闻热榜采集失败: {e}")
            return []

    @staticmethod
    def fetch_qq_news_hot(count=20):
        """腾讯新闻热榜（免费）"""
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
            resp = requests.get('https://i.news.qq.com/trpc.qqnews_web.kv_srv.kv_srv_http_proxy/list?sub_srv_id=24hours&srv_id=pc', headers=headers, timeout=10)
            data = resp.json()
            items_raw = data.get('data', {}).get('list', [])

            items = []
            for i, item in enumerate(items_raw[:count]):
                items.append({
                    "title": item.get('title', ''),
                    "hot_value": item.get('read_count', 0),
                    "position": i + 1,
                    "url": item.get('url', ''),
                    "platform": "腾讯新闻",
                    "source": "免费热榜"
                })
            logger.info(f"腾讯新闻热榜采集到 {len(items)} 条")
            return items
        except Exception as e:
            logger.error(f"腾讯新闻热榜采集失败: {e}")
            return []

    @staticmethod
    def fetch_sspai_latest(count=20):
        """少数派最新（免费，科技数码类）"""
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
            resp = requests.get(f'https://sspai.com/api/v1/article/index/page/get/0?limit={count}', headers=headers, timeout=10)
            data = resp.json()
            items_raw = data.get('data', [])

            items = []
            for i, item in enumerate(items_raw[:count]):
                items.append({
                    "title": item.get('title', ''),
                    "hot_value": item.get('like_count', 0),
                    "position": i + 1,
                    "url": f"https://sspai.com/post/{item.get('id', '')}",
                    "platform": "少数派",
                    "source": "免费热榜"
                })
            logger.info(f"少数派最新采集到 {len(items)} 条")
            return items
        except Exception as e:
            logger.error(f"少数派最新采集失败: {e}")
            return []

    @staticmethod
    def fetch_juejin_hot(count=20):
        """掘金热门（免费，技术类）"""
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                       'Content-Type': 'application/json'}
            payload = {"id_type": 2, "client_type": 2608, "sort_type": 200, "cursor": "0", "limit": count}
            resp = requests.post('https://api.juejin.cn/recommend_api/v1/article/recommend_all_feed',
                                headers=headers, json=payload, timeout=10)
            data = resp.json()
            items_raw = data.get('data', [])

            items = []
            for i, item in enumerate(items_raw[:count]):
                article = item.get('article_info', {})
                items.append({
                    "title": article.get('title', ''),
                    "hot_value": article.get('digg_count', 0),
                    "position": i + 1,
                    "url": f"https://juejin.cn/post/{article.get('article_id', '')}",
                    "platform": "掘金",
                    "source": "免费热榜"
                })
            logger.info(f"掘金热门采集到 {len(items)} 条")
            return items
        except Exception as e:
            logger.error(f"掘金热门采集失败: {e}")
            return []

    @staticmethod
    def fetch_ithome_news(count=20):
        """IT之家最新资讯（免费，科技数码类）"""
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
            resp = requests.get('https://api.ithome.com/json/newslist/news?r=0', headers=headers, timeout=10)
            data = resp.json()
            items_raw = data.get('newslist', [])

            items = []
            for i, item in enumerate(items_raw[:count]):
                items.append({
                    "title": item.get('title', ''),
                    "hot_value": item.get('hitcount', 0),
                    "position": i + 1,
                    "url": f"https://www.ithome.com/0/{item.get('newsid', '')}.htm",
                    "platform": "IT之家",
                    "source": "免费热榜"
                })
            logger.info(f"IT之家资讯采集到 {len(items)} 条")
            return items
        except Exception as e:
            logger.error(f"IT之家资讯采集失败: {e}")
            return []

    @staticmethod
    def fetch_github_trending(count=20):
        """GitHub Trending每日热门项目（免费，技术/AI类）"""
        import re
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
            resp = requests.get('https://github.com/trending?since=daily', headers=headers, timeout=15)
            html = resp.text

            # 解析每个项目
            projects = re.findall(r'<article class="Box-row">(.*?)</article>', html, re.DOTALL)

            items = []
            for i, project in enumerate(projects[:count]):
                # 提取仓库名（h2标签里的第一个a标签）
                h2_match = re.search(r'<h2[^>]*>(.*?)</h2>', project, re.DOTALL)
                if not h2_match:
                    continue
                h2_content = h2_match.group(1)
                repo_match = re.search(r'<a[^>]*href="([^"]+)"', h2_content)
                if not repo_match:
                    continue
                repo_path = repo_match.group(1).strip('/')
                repo_name = repo_path.split('/')[-1]

                # 提取描述
                desc_match = re.search(r'<p class="col-9[^"]*"[^>]*>(.*?)</p>', project, re.DOTALL)
                description = desc_match.group(1).strip() if desc_match else ''

                # 提取今日星数
                today_stars_match = re.search(r'(\d[\d,]*)\s*stars today', project)
                today_stars = int(today_stars_match.group(1).replace(',', '')) if today_stars_match else 0

                # 简单关键词翻译（英文->中文）
                keyword_map = {
                    'AI': '人工智能', 'ai': '人工智能',
                    'agent': '智能体', 'Agent': '智能体',
                    'code': '代码', 'Code': '代码',
                    'GPT': '大模型', 'gpt': '大模型',
                    'LLM': '大语言模型', 'llm': '大语言模型',
                    'framework': '框架', 'Framework': '框架',
                    'tool': '工具', 'Tool': '工具',
                    'assistant': '助手', 'Assistant': '助手',
                    'open source': '开源', 'Open Source': '开源',
                    'machine learning': '机器学习', 'Machine Learning': '机器学习',
                    'deep learning': '深度学习', 'Deep Learning': '深度学习',
                    'chatbot': '聊天机器人', 'Chatbot': '聊天机器人',
                    'reverse engineer': '逆向工程', 'Reverse Engineer': '逆向工程',
                    'automation': '自动化', 'Automation': '自动化',
                    'productivity': '效率工具', 'Productivity': '效率工具',
                    'video': '视频', 'Video': '视频',
                    'image': '图像', 'Image': '图像',
                    'language': '语言', 'Language': '语言',
                    'search': '搜索', 'Search': '搜索',
                    'database': '数据库', 'Database': '数据库',
                    'api': 'API接口', 'API': 'API接口',
                }

                # 提取中文关键词
                chinese_tags = []
                for en, zh in keyword_map.items():
                    if en in description:
                        chinese_tags.append(zh)

                # 组合标题：项目名 + 中文标签 + 英文描述前50字
                if chinese_tags:
                    title = f"{repo_name} [{'/'.join(chinese_tags[:3])}]"
                else:
                    title = repo_name

                items.append({
                    "title": title,
                    "hot_value": today_stars,
                    "position": i + 1,
                    "url": f"https://github.com{repo_path}",
                    "platform": "GitHub",
                    "source": "免费热榜"
                })

            logger.info(f"GitHub Trending采集到 {len(items)} 条")
            return items
        except Exception as e:
            logger.error(f"GitHub Trending采集失败: {e}")
            return []

    @staticmethod
    def fetch_newsbing(count_per_source=30, timeout=120, retries=3):
        """NewsBing 多平台热点聚合（免 Key，覆盖小红书/微博/知乎/B站/抖音/X/百度/头条/V2EX/HN）

        接口：https://api.newsbing.app/api/public/hotspots
        说明：无需注册/登录/API Key；平台榜按各自周期更新，AI 总榜每小时更新。
        注意：响应体较大（约 600KB），本机直连 TLS 易中途断开，
        因此用 curl gzip 压缩传输 + 多轮重试 + 截断容错解析。
        额外的 "多平台共振" 标记：聚合总榜里同一事件出现在 ≥2 个平台时，
        会在简要描述中标注共振平台数，便于判断是否全网爆。
        """
        import subprocess
        import json as _json

        url = "https://api.newsbing.app/api/public/hotspots"
        platform_map = {
            "xiaohongshu": "小红书",
            "weibo": "微博",
            "zhihu": "知乎",
            "bilibili": "B站",
            "x": "X",
            "douyin": "抖音",
            "baidu": "百度",
            "toutiao": "今日头条",
            "v2ex": "V2EX",
            "hackernews": "Hacker News",
        }

        best_raw = ""
        accum_items = {}      # id -> 条目（多轮请求累积，互补截断缺口）
        accum_agg = {}        # 聚合总榜条目（按标题去重）

        for attempt in range(1, retries + 1):
            try:
                proc = subprocess.run(
                    ["curl", "-sS", "--http1.1", "--compressed",
                     "-A", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                     "-H", "Accept: application/json",
                     "-H", "Accept-Encoding: gzip",
                     "--max-time", str(timeout), url],
                    capture_output=True, text=True, timeout=timeout + 15
                )
                raw = proc.stdout or ""
                if '"items"' not in raw:
                    logger.warning(f"NewsBing 第{attempt}次请求无有效数据，{proc.stderr.strip()[:80]}")
                    time.sleep(8)
                    continue
                if len(raw) > len(best_raw):
                    best_raw = raw

                data = None
                try:
                    data = _json.loads(raw)
                except Exception:
                    pass

                if isinstance(data, dict):
                    for it in (data.get("items") or []):
                        if isinstance(it, dict):
                            accum_items[it.get("id") or it.get("url") or it.get("title")] = it
                    for it in ((data.get("aggregate") or {}).get("items") or []):
                        if isinstance(it, dict):
                            accum_agg[it.get("title") or it.get("id")] = it
                    complete = True
                    logger.info(f"NewsBing 第{attempt}次请求拿到完整响应")
                    break

                # 截断：流式提取已完成的条目，累积到下一轮
                logger.warning(f"NewsBing 第{attempt}次响应被截断（{len(raw)} 字节），先解析已完成部分")
                decoder = _json.JSONDecoder()
                pos = 0
                while True:
                    start = raw.find('{"id":', pos)
                    if start < 0:
                        break
                    try:
                        obj, end = decoder.raw_decode(raw, start)
                        accum_items[obj.get("id") or obj.get("url") or obj.get("title")] = obj
                        pos = end
                    except Exception:
                        pos = start + 6
                agg_key = raw.find('"aggregate"')
                if agg_key > 0:
                    pos = agg_key
                    while True:
                        start = raw.find('{"title":', pos)
                        if start < 0:
                            break
                        try:
                            obj, end = decoder.raw_decode(raw, start)
                            if isinstance(obj.get("platforms"), list):
                                accum_agg[obj.get("title") or obj.get("id")] = obj
                            pos = end
                        except Exception:
                            pos = start + 9

                if attempt < retries:
                    time.sleep(8)
            except Exception as e:
                logger.warning(f"NewsBing 第{attempt}次请求异常: {e}")
                time.sleep(8)

        raw_items = list(accum_items.values())
        raw_aggregate = list(accum_agg.values())

        if not best_raw and not raw_items:
            logger.error("NewsBing 采集失败: 无数据返回")
            return []

        # 构建 原文链接 -> 全网共振平台数 的映射（来自聚合总榜）
        url_to_platforms = {}
        for agg_item in raw_aggregate:
            plats = agg_item.get("platforms") or []
            if len(plats) < 2:
                continue
            for src in (agg_item.get("sources") or []):
                u = src.get("url") if isinstance(src, dict) else None
                if u:
                    url_to_platforms[u] = max(len(plats), url_to_platforms.get(u, 0))

        # 按榜单来源分组，按榜内排名取前 N 条
        by_source = {}
        for it in raw_items:
            if not isinstance(it, dict):
                continue
            sid = it.get("sourceId") or it.get("platform") or "unknown"
            by_source.setdefault(sid, []).append(it)

        items = []
        seen_titles = set()
        for sid, group in by_source.items():
            group.sort(key=lambda x: x.get("rank") or 999)
            for it in group[:count_per_source]:
                title = (it.get("title") or "").strip()
                if not title or title in seen_titles:
                    continue
                seen_titles.add(title)
                rank = it.get("rank") or 0
                label = it.get("sourceLabel") or ""
                platform = platform_map.get(it.get("platform"), it.get("platform") or "NewsBing")
                item_url = it.get("url", "")
                resonance = url_to_platforms.get(item_url, 0)

                summary = (it.get("summary") or "").strip()
                base = f"{label}第{rank}位" if rank else label
                if resonance >= 2:
                    summary = f"🔥多平台共振({resonance}个平台) | {base}"
                    if it.get("summary"):
                        summary += f" | {it['summary'][:80]}"
                elif not summary:
                    summary = base

                # 保留真实榜内排名，多平台共振作为独立信号（在分级阶段使用）
                position = rank or (len(items) + 1)

                # 平台权重分层：大众平台 / 中文技术社区 / 英文技术社区
                # 英文源（HN、X）对中文账号可执行性低，除非多平台共振，否则只作参考
                if platform in {"Hacker News", "X"}:
                    tier = "niche_en"
                elif platform == "V2EX":
                    tier = "niche_cn"
                else:
                    tier = "core"

                items.append({
                    "title": title,
                    "hot_value": 0,          # 该接口不提供热度值，仅提供榜内排名
                    "position": position,
                    "url": item_url,
                    "platform": platform,
                    "source": "NewsBing",
                    "summary": summary,
                    "resonance": resonance,
                    "tier": tier,
                })

        # ---- 跨平台共振补齐 ----
        # 接口的 aggregate 总榜位于响应末尾，截断时往往拿不到，
        # 因此再用“同题跨平台匹配”作为兜底信号：同一标题出现在 ≥2 个平台即视为共振。
        import re as _re

        def _norm_title(s):
            return _re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", s or "").lower()

        title_platforms = {}
        for it in items:
            key = _norm_title(it["title"])
            if len(key) < 5:
                continue
            title_platforms.setdefault(key, set()).add(it["platform"])

        for it in items:
            key = _norm_title(it["title"])
            n = len(title_platforms.get(key, ()))
            if n >= 2:
                if n > it.get("resonance", 0):
                    it["resonance"] = n
                if "共振" not in it["summary"]:
                    it["summary"] = f"🔥多平台共振({n}个平台) | {it['summary']}"

        platforms = sorted({i["platform"] for i in items})
        reso_count = sum(1 for i in items if i.get("resonance", 0) >= 2)
        logger.info(
            f"NewsBing 采集到 {len(items)} 条 | 平台覆盖: {platforms} | 多平台共振: {reso_count} 条"
        )
        return items

# ====================================
# 各平台采集器
# ====================================
class DouyinCollector:
    """抖音采集器"""
    def __init__(self, client: TikHubClient):
        self.client = client
        self.name = "抖音"

    def fetch_hot_list(self, count=20):
        """获取抖音热榜（每日热点池用）"""
        data = self.client.get("/api/v1/douyin/app/v3/fetch_hot_search_list")
        if not data:
            return []
        items = []
        inner = data.get("data", {})
        word_list = inner.get("word_list", [])
        for i, item in enumerate(word_list[:count]):
            items.append({
                "title": item.get("word", ""),
                "hot_value": item.get("hot_value", 0) or item.get("view_count", 0),
                "position": i + 1,
                "url": f"https://www.douyin.com/search/{item.get('word', '')}",
                "platform": "抖音",
                "source": "热榜"
            })
        logger.info(f"抖音热榜采集到 {len(items)} 条")
        return items


class BilibiliCollector:
    """B站采集器"""
    def __init__(self, client: TikHubClient):
        self.client = client
        self.name = "B站"

    def fetch_hot_list(self, count=20):
        """获取B站热门搜索（每日热点池用）"""
        data = self.client.get("/api/v1/bilibili/web/fetch_hot_search", params={"limit": count})
        if not data:
            return []
        items = []
        inner = data.get("data", {})
        trending = inner.get("trending", {})
        hot_list = trending.get("list", [])
        for i, item in enumerate(hot_list[:count]):
            items.append({
                "title": item.get("keyword", "") or item.get("show_name", ""),
                "hot_value": item.get("heat_score", 0),
                "position": i + 1,
                "url": f"https://search.bilibili.com/all?keyword={item.get('keyword', '')}",
                "platform": "B站",
                "source": "热榜"
            })
        logger.info(f"B站热榜采集到 {len(items)} 条")
        return items


class XiaohongshuCollector:
    """小红书采集器 - 重点：找当天爆火的笔记"""
    def __init__(self, client: TikHubClient):
        self.client = client
        self.name = "小红书"

    def search_trending_notes(self, keyword, count=20, hours_window=48):
        """
        搜索最近爆火的小红书笔记
        hours_window: 只取最近N小时内发布的
        """
        data = self.client.get("/api/v1/xiaohongshu/app_v2/search_notes",
                               params={"keyword": keyword, "page": 1, "page_size": count * 2})
        if not data:
            return []
        items = []
        inner = data.get("data", {})
        note_items = inner.get("items", [])

        now = datetime.now().timestamp()
        cutoff = now - hours_window * 3600

        for item in note_items:
            note = item.get("note", {})
            timestamp = note.get("timestamp", 0)

            if timestamp < cutoff:
                continue

            user = note.get("user", {})
            items.append({
                "title": note.get("title", ""),
                "likes": self._parse_count(note.get("liked_count", 0)),
                "comments": self._parse_count(note.get("comments_count", 0)),
                "collects": self._parse_count(note.get("collected_count", 0)),
                "shares": self._parse_count(note.get("shared_count", 0)),
                "fans": self._parse_count(user.get("fans", 0)),
                "author": user.get("nickname", ""),
                "timestamp": timestamp,
                "url": f"https://www.xiaohongshu.com/explore/{note.get('id', '')}",
                "platform": "小红书"
            })

        items.sort(key=lambda x: x["likes"], reverse=True)
        result = items[:count]

        logger.info(f"小红书搜索[{keyword}] 时间窗口{hours_window}h内: {len(result)} 条 (共扫描{len(note_items)}条)")
        return result

    @staticmethod
    def _parse_count(value):
        if isinstance(value, (int, float)):
            return int(value)
        if not value:
            return 0
        s = str(value).strip()
        try:
            if "万" in s:
                return int(float(s.replace("万", "")) * 10000)
            elif "k" in s.lower():
                return int(float(s.lower().replace("k", "")) * 1000)
            else:
                return int(float(s))
        except:
            return 0


# ====================================
# 数据过滤
# ====================================
class DataFilter:
    """根据关键词过滤相关内容"""
    def __init__(self):
        self.keywords = CONFIG["keywords"]

    def is_relevant(self, title):
        title_lower = title.lower()
        for kw in self.keywords:
            if kw.lower() in title_lower:
                return True
        return False

    def filter_hot_list(self, items):
        relevant = []
        for item in items:
            if self.is_relevant(item["title"]):
                item["category_tags"] = self._match_categories(item["title"])
                relevant.append(item)
        logger.info(f"热榜过滤: {len(items)} -> {len(relevant)} 条相关")
        return relevant

    def _match_categories(self, title):
        tags = []
        tech_kws = ["数码", "手机", "电脑", "芯片", "相机", "无人机", "硬件", "产品", "iPhone", "华为", "小米"]
        ai_kws = ["AI", "人工智能", "大模型", "GPT", "DeepSeek", "Claude", "机器人", "智能", "AIGC"]
        for kw in tech_kws:
            if kw.lower() in title.lower():
                tags.append("数码")
                break
        for kw in ai_kws:
            if kw.lower() in title.lower():
                tags.append("AI/人工智能")
                break
        return list(set(tags)) if tags else ["通用热点"]


# ====================================
# 飞书写入
# ====================================
class FeishuWriter:
    """通过 lark-cli 写入飞书多维表格"""
    def __init__(self):
        self.app_token = CONFIG["feishu"]["app_token"]
        self.hot_pool_table = CONFIG["feishu"]["hot_pool_table_id"]
        self.viral_pool_table = CONFIG["feishu"]["viral_pool_table_id"]

    @staticmethod
    def _title_similarity(title1, title2):
        """计算两个标题的相似度（基于字符集合的Jaccard系数）"""
        # 去掉标点和空格
        t1 = set(c for c in title1 if c.strip())
        t2 = set(c for c in title2 if c.strip())
        if not t1 or not t2:
            return 0
        intersection = len(t1 & t2)
        union = len(t1 | t2)
        return intersection / union if union > 0 else 0

    def get_today_hot_titles(self):
        """查询今天已经写入的热点标题，用于去重

        lark-cli 现在返回 JSON manifest + ndjson 记录文件，
        需要先解析出 record_file 再读 ndjson，按“采集日期”筛出今天的标题。
        """
        today = datetime.now().strftime("%Y-%m-%d")
        existing_titles = []

        try:
            cmd = [
                "lark-cli", "base", "+record-list",
                "--base-token", self.app_token,
                "--table-id", self.hot_pool_table,
                "--limit", "1000",
                "--as", "user"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
            if result.returncode != 0:
                logger.error(f"查询今日热点失败: {result.stderr[:200]}")
                return []

            record_file = None
            try:
                manifest = json.loads(result.stdout)
                if isinstance(manifest, dict):
                    data = manifest.get("data")
                    if isinstance(data, dict):
                        record_file = data.get("record_file")
                    record_file = record_file or manifest.get("record_file")
            except Exception:
                logger.error("解析 lark-cli 输出失败，今日去重将跳过")
                return []

            if not record_file or not os.path.exists(record_file):
                logger.error(f"未拿到有效的 record_file（{record_file}），今日去重将跳过")
                return []

            with open(record_file, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    fields = rec.get("fields", rec)

                    # 判断采集日期是否为今天
                    raw_date = fields.get("采集日期")
                    date_str = ""
                    if isinstance(raw_date, (int, float)):
                        date_str = datetime.fromtimestamp(raw_date / 1000).strftime("%Y-%m-%d")
                    elif isinstance(raw_date, str):
                        date_str = raw_date[:10]
                    if date_str != today:
                        continue

                    title = fields.get("热点标题")
                    if isinstance(title, list):
                        title = "".join(
                            (x.get("text", "") if isinstance(x, dict) else str(x)) for x in title
                        )
                    elif isinstance(title, dict):
                        title = title.get("text", "")
                    if title and str(title).strip():
                        existing_titles.append(str(title).strip())

            logger.info(f"查询到今日已有 {len(existing_titles)} 条热点标题（用于去重）")
        except Exception as e:
            logger.error(f"查询今日热点标题失败: {e}")

        return existing_titles

    def write_hot_pool(self, items):
        if not items:
            logger.info("热点池无数据可写入")
            return 0

        # 先查询今天已有的标题
        existing_titles = self.get_today_hot_titles()

        # 过滤重复的（模糊去重，相似度>0.6就算重复）
        new_items = []
        duplicate_count = 0
        SIMILARITY_THRESHOLD = 0.6

        for item in items:
            title = item["title"]
            is_duplicate = False

            # 和今天已有的标题比较
            for existing_title in existing_titles:
                sim = self._title_similarity(title, existing_title)
                if sim >= SIMILARITY_THRESHOLD:
                    is_duplicate = True
                    logger.debug(f"跳过重复(相似度{sim:.2f}): {title} ~ {existing_title}")
                    break

            # 和同批次已加入的比较
            if not is_duplicate:
                for new_item in new_items:
                    sim = self._title_similarity(title, new_item["title"])
                    if sim >= SIMILARITY_THRESHOLD:
                        is_duplicate = True
                        logger.debug(f"跳过同批次重复(相似度{sim:.2f}): {title} ~ {new_item['title']}")
                        break

            if is_duplicate:
                duplicate_count += 1
            else:
                new_items.append(item)
                existing_titles.append(title)

        if duplicate_count > 0:
            logger.info(f"去重: {len(items)} 条 -> {len(new_items)} 条 (跳过 {duplicate_count} 条重复)")

        records = []
        today = datetime.now().strftime("%Y-%m-%d")
        for item in new_items:
            # 智能生成追热点建议
            hot_value = item.get("hot_value", 0)
            position = item.get("position", 999)  # 排名，默认999（没排名）
            category_tags = item.get("category_tags", ["通用热点"])
            is_core_category = any(tag in ["AI/人工智能", "数码"] for tag in category_tags)
            resonance = item.get("resonance", 0)   # 多平台共振平台数（0=未共振）
            tier = item.get("tier", "core")        # core=大众平台 / niche_cn=中文技术社区 / niche_en=英文技术社区

            # 分级规则（排名 + 品类 + 平台权重 + 多平台共振）
            # 前10名 = 高热，前30名 = 中热
            # 小众社区（V2EX/HN/X）榜内前列不等于大众爆点，降档处理
            # 同一事件在≥2个平台同时上榜 = 全网共振，即使排名靠后也值得跟进
            if is_core_category and position <= 10 and tier == "core":
                suggestion = "强烈推荐"
            elif is_core_category and tier == "niche_en" and resonance < 2:
                suggestion = "可以看看"
            elif is_core_category and (position <= 30 or resonance >= 2):
                suggestion = "推荐跟进"
            elif is_core_category:
                suggestion = "可以看看"
            else:
                suggestion = "观望"

            record = {
                "热点标题": item["title"],
                "采集日期": today,
                "平台": [item["platform"]],
                "品类标签": category_tags,
                "热度值": hot_value,
                "热度趋势": ["上升"],
                "时效窗口": ["24h内"],
                "内容链接": item.get("url", ""),
                "简要描述": item.get("summary") or item["title"],
                "追热点建议": [suggestion],
                "采集来源": [item.get("source", "TikHub API")]
            }
            records.append(record)

        return self._batch_create(self.hot_pool_table, records)

    def write_viral_pool(self, items, scores):
        """写入爆款视频拆解池，只写B级以上的"""
        if not items:
            logger.info("爆款池无数据可写入")
            return 0

        records = []
        today = datetime.now().strftime("%Y-%m-%d")

        for i, item in enumerate(items):
            score = scores[i]
            if score["score"] < 30:
                continue

            record = {
                "视频标题": item["title"],
                "采集日期": today,
                "平台": [item["platform"]],
                "品类标签": ["AI/人工智能"],
                "视频链接": item.get("url", ""),
                "点赞数": item.get("likes", 0),
                "评论数": item.get("comments", 0),
                "转发数": item.get("shares", 0),
                "收藏数": item.get("collects", 0),
                "采集来源": ["TikHub API"]
            }
            records.append(record)

        written = self._batch_create(self.viral_pool_table, records)
        logger.info(f"爆款池: 扫描{len(items)}条, 写入{written}条 (得分≥30)")
        return written

    def _batch_create(self, table_id, records):
        if not records:
            return 0

        total = 0
        for i in range(0, len(records), 100):
            batch = records[i:i+100]
            payload = {"create_records": batch}

            cmd = [
                "lark-cli", "base", "+record-batch-create",
                "--base-token", self.app_token,
                "--table-id", table_id,
                "--json", json.dumps(payload, ensure_ascii=False),
                "--as", "user"
            ]

            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if result.returncode == 0:
                    data = json.loads(result.stdout)
                    if data.get("ok"):
                        count = len(data["data"]["record_id_list"])
                        total += count
                        logger.info(f"写入飞书成功: {count} 条 (表 {table_id[:8]}...)")
                    else:
                        logger.error(f"飞书返回错误: {data}")
                else:
                    logger.error(f"lark-cli 执行失败: {result.stderr}")
            except Exception as e:
                logger.error(f"写入飞书异常: {e}")

            time.sleep(0.5)

        return total


# ====================================
# 主流程
# ====================================
def main():
    logger.info("=" * 60)
    logger.info("开始执行每日热点采集任务")
    logger.info(f"当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    # 初始化
    client = TikHubClient()
    douyin = DouyinCollector(client)
    bilibili = BilibiliCollector(client)
    xhs = XiaohongshuCollector(client)
    free_collector = FreeHotListCollector()
    data_filter = DataFilter()
    score_calc = ViralScoreCalculator()
    writer = FeishuWriter()

    all_hot_items = []
    all_viral_items = []
    all_viral_scores = []

    # ========== 第一部分：每日热点池（热榜） ==========
    logger.info("-" * 30)
    logger.info("【1/2】采集热榜数据...")
    logger.info("-" * 30)

    # 免费热榜：百度热搜
    baidu_count = CONFIG.get("free_hot", {}).get("baidu_count", 20)
    baidu_items = free_collector.fetch_baidu_hot(baidu_count)
    filtered_baidu = data_filter.filter_hot_list(baidu_items)
    all_hot_items.extend(filtered_baidu)

    # 免费热榜：B站热门
    bili_count = CONFIG.get("free_hot", {}).get("bilibili_count", 20)
    bili_items = free_collector.fetch_bilibili_popular(bili_count)
    filtered_bili = data_filter.filter_hot_list(bili_items)
    all_hot_items.extend(filtered_bili)

    # 免费热榜：今日头条
    toutiao_count = CONFIG.get("free_hot", {}).get("toutiao_count", 20)
    toutiao_items = free_collector.fetch_toutiao_hot(toutiao_count)
    filtered_toutiao = data_filter.filter_hot_list(toutiao_items)
    all_hot_items.extend(filtered_toutiao)

    # 免费热榜：网易新闻
    netease_count = CONFIG.get("free_hot", {}).get("netease_count", 20)
    netease_items = free_collector.fetch_163_hot(netease_count)
    filtered_netease = data_filter.filter_hot_list(netease_items)
    all_hot_items.extend(filtered_netease)

    # 免费热榜：腾讯新闻
    qqnews_count = CONFIG.get("free_hot", {}).get("qqnews_count", 20)
    qqnews_items = free_collector.fetch_qq_news_hot(qqnews_count)
    filtered_qqnews = data_filter.filter_hot_list(qqnews_items)
    all_hot_items.extend(filtered_qqnews)

    # 免费热榜：少数派（科技数码类）
    sspai_count = CONFIG.get("free_hot", {}).get("sspai_count", 20)
    sspai_items = free_collector.fetch_sspai_latest(sspai_count)
    filtered_sspai = data_filter.filter_hot_list(sspai_items)
    all_hot_items.extend(filtered_sspai)

    # 免费热榜：掘金（技术类）
    juejin_count = CONFIG.get("free_hot", {}).get("juejin_count", 20)
    juejin_items = free_collector.fetch_juejin_hot(juejin_count)
    filtered_juejin = data_filter.filter_hot_list(juejin_items)
    all_hot_items.extend(filtered_juejin)

    # 免费热榜：IT之家（科技数码类）
    ithome_count = CONFIG.get("free_hot", {}).get("ithome_count", 20)
    ithome_items = free_collector.fetch_ithome_news(ithome_count)
    filtered_ithome = data_filter.filter_hot_list(ithome_items)
    all_hot_items.extend(filtered_ithome)

    # 免费热榜：GitHub Trending（技术/AI类）
    github_count = CONFIG.get("free_hot", {}).get("github_count", 20)
    github_items = free_collector.fetch_github_trending(github_count)
    filtered_github = data_filter.filter_hot_list(github_items)
    all_hot_items.extend(filtered_github)

    # 免费热榜：NewsBing 多平台聚合（小红书/微博/知乎/B站/X，免 Key）
    if CONFIG.get("newsbing", {}).get("enabled", True):
        nb_cfg = CONFIG.get("newsbing", {})
        nb_count = nb_cfg.get("count_per_source", 30)
        newsbing_items = free_collector.fetch_newsbing(
            count_per_source=nb_count,
            timeout=nb_cfg.get("timeout", 120),
            retries=nb_cfg.get("retries", 3),
        )
        filtered_newsbing = data_filter.filter_hot_list(newsbing_items)
        all_hot_items.extend(filtered_newsbing)

    # 付费热榜：抖音（TikHub）
    tikhub_on = CONFIG.get("tikhub", {}).get("enabled", False) and CONFIG.get("tikhub", {}).get("api_key")
    if tikhub_on and CONFIG.get("platforms", {}).get("douyin", {}).get("enabled"):
        count = CONFIG["platforms"]["douyin"].get("hot_list_count", 20)
        hot_items = douyin.fetch_hot_list(count)
        filtered = data_filter.filter_hot_list(hot_items)
        all_hot_items.extend(filtered)

    # 付费热榜：B站（TikHub，可选）
    if tikhub_on and CONFIG.get("platforms", {}).get("bilibili", {}).get("enabled"):
        count = CONFIG["platforms"]["bilibili"].get("hot_list_count", 20)
        hot_items = bilibili.fetch_hot_list(count)
        filtered = data_filter.filter_hot_list(hot_items)
        all_hot_items.extend(filtered)

    # ========== 第二部分：爆款视频池（时间窗口筛选） ==========
    logger.info("-" * 30)
    logger.info("【2/2】采集当天爆款内容...")
    logger.info("-" * 30)

    if tikhub_on and CONFIG.get("platforms", {}).get("xiaohongshu", {}).get("enabled"):
        count = CONFIG["platforms"]["xiaohongshu"].get("search_count", 20)
        hours_window = CONFIG.get("viral_window_hours", 48)

        for kw in ["AI", "数码"]:
            notes = xhs.search_trending_notes(kw, count, hours_window)
            for note in notes:
                score = score_calc.calculate(note, "小红书")
                all_viral_items.append(note)
                all_viral_scores.append(score)
            time.sleep(1)

    # ========== 打印爆款评分汇总 ==========
    if all_viral_scores:
        logger.info("=" * 60)
        logger.info("爆款评分汇总 (Top 10):")
        sorted_pairs = sorted(zip(all_viral_scores, all_viral_items), key=lambda x: x[0]["score"], reverse=True)
        for i, (score, item) in enumerate(sorted_pairs[:10]):
            logger.info(f"  {i+1}. [{score['level']} | {score['score']}分] {item['title'][:35]}")
            logger.info(f"     平台:{item['platform']} | 赞:{item['likes']} | 发布:{score['hours_ago']}h前")
        logger.info("=" * 60)

    # ========== 写入飞书 ==========
    logger.info("开始写入飞书多维表格...")
    hot_written = writer.write_hot_pool(all_hot_items)
    viral_written = writer.write_viral_pool(all_viral_items, all_viral_scores)

    # 汇总
    logger.info("=" * 60)
    logger.info("采集完成!")
    logger.info(f"  每日热点池写入: {hot_written} 条")
    logger.info(f"  爆款拆解池写入: {viral_written} 条")
    logger.info("=" * 60)

    return {
        "hot_pool_count": hot_written,
        "viral_pool_count": viral_written
    }


if __name__ == "__main__":
    result = main()
    print(json.dumps(result, ensure_ascii=False))
