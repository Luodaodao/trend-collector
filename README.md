# 平台热点捕捉系统

每天自动采集全网数码 / AI / 电车类热点，按关键词过滤、模糊去重、自动分级，写入你自己的飞书多维表格。

**核心特点：全免费。** 主力数据源 NewsBing 无需注册、无需 API Key、无需登录，一次请求就能拿到微博、知乎、小红书、B站、抖音、百度、今日头条、V2EX、X、Hacker News 共 10 个榜单。

---

## 一、它每天给你什么

一条命令跑完，飞书表里会出现当天的热点清单，每条包含：

| 字段 | 说明 |
|---|---|
| 热点标题 | 热点原文标题 |
| 平台 | 来自哪个平台 |
| 品类标签 | 数码 / AI人工智能 / 通用热点（自动判断） |
| 追热点建议 | 强烈推荐 / 推荐跟进 / 可以看看 / 观望（自动分级） |
| 简要描述 | 榜内排名 + 是否多平台共振 |
| 内容链接 | 原文地址 |
| 采集来源 | NewsBing / 免费热榜 / TikHub API |

**自动分级规则**

- 🔴 强烈推荐：数码/AI 品类 + 大众平台热榜前 10 名
- 🟠 推荐跟进：数码/AI 品类 + 前 30 名，**或**同一事件在 ≥2 个平台同时上榜（全网共振）
- 🟡 可以看看：数码/AI 品类但排名靠后；或英文技术社区（HN / X）
- ⚪ 观望：非数码/AI 品类

---

## 二、开始之前的准备

需要三样东西：

1. **Python 3.8+**
2. **lark-cli**（飞书命令行工具，用来建表和写数据）
3. **一个飞书账号**（免费版即可）

> 如果你用的是豆包工作环境，lark-cli 通常已经内置，可以直接跳到第三步。

检查一下：

```bash
python3 --version
lark-cli --version
```

如果 `lark-cli` 提示 command not found，需要先安装飞书 CLI 并登录：

```bash
lark-cli auth login
```

---

## 三、三步部署

### 第 1 步：下载代码

```bash
git clone https://github.com/Luodaodao/trend-collector.git
cd trend-collector
```

或者直接在 GitHub 页面点「Download ZIP」解压。

### 第 2 步：装依赖 + 一键建飞书表

```bash
pip install -r requirements.txt
python3 setup_feishu.py
```

`setup_feishu.py` 会自动完成这些事：

1. 在你的飞书云空间创建 Base「平台热点捕捉系统」
2. 建好两张表：**每日热点池**（11 个字段）、**爆款拆解池**（16 个字段）
3. 把 19 个平台选项、4 档追热点建议等全部预设好
4. 生成 `config.yaml` 并填好 `app_token` / `table_id`

跑完会打印你的飞书表格链接，打开就能看到建好的空表。

### 第 3 步：跑一次

```bash
python3 trend_collector.py
```

正常输出结尾长这样：

```
{"hot_pool_count": 80, "viral_pool_count": 0}
```

意思是这次写入了 80 条热点。打开飞书表就能看到。

---

## 四、日常使用

### 手动跑

```bash
python3 trend_collector.py
```

### 每天定时跑

**Linux / macOS（crontab）**

```bash
crontab -e
```

加一行（每天上午 10:00）：

```
0 10 * * * cd /你的路径/trend-collector && /usr/bin/python3 trend_collector.py >> cron.log 2>&1
```

**用豆包定时任务**

直接在对话里说「每天10点帮我跑一次热点采集」即可。

> ⚠️ 不建议放在个人电脑上跑。电脑关机 / 休眠任务就断了。建议放在云主机、NAS 或常开的服务器上。

---

## 五、配置说明

所有配置都在 `config.yaml`，改完直接生效，不用重装。

### 关键词（决定你要什么热点）

```yaml
keywords:
  - "手机"
  - "AI"
  - "特斯拉"
```

按你的赛道增删。系统用这些词匹配热点标题，命中才写入表格。

### NewsBing 主数据源

```yaml
newsbing:
  enabled: true
  count_per_source: 100   # 每个榜单取前 N 条
  timeout: 120
  retries: 3
```

关掉就把 `enabled` 改成 `false`。

### 付费源（可选，默认关闭）

```yaml
tikhub:
  enabled: false
  api_key: ""
platforms:
  douyin:
    enabled: false
```

只有你需要「抖音/小红书的具体内容数据」（点赞、收藏、发布时间）时才需要开。**免费源已经覆盖了热榜，日常够用。**

---

## 六、常见问题

**Q：跑完表里是空的？**
关键词没匹配上。打开 `trend_collector.log` 看 `热榜过滤: 490 -> 70 条相关` 这类日志。如果过滤后是 0，说明你的关键词太窄，加几个宽泛的词（比如 `AI`、`数码`）。

**Q：提示 `lark-cli 执行失败: not_found`？**
飞书表的选项里没有这个值。重新跑一次 `setup_feishu.py`，或者手动在飞书表「平台」字段里补上对应选项。

**Q：NewsBing 那步很慢 / 偶尔失败？**
正常。这个接口响应体约 600KB，网络抖动时会中途断开。代码里已经做了 3 次重试 + 截断容错解析，多轮结果会合并互补。极端失败时会退回只用其它免费源。

**Q：能抓到小红书低粉爆款吗？**
不能。NewsBing 给的是「小红书创作热点」（话题榜），不是内容榜。要抓某个账号突然爆了，需要小红书的内容搜索接口（TikHub 付费）。

**Q：飞书表里「热度值」为什么是 0？**
NewsBing 只提供榜内排名，不提供热度数值。热度值列对这类源记 0，真实排名写在「简要描述」里。

**Q：重复的热点会被写两次吗？**
不会。系统会先读当天已有的标题，相似度 ≥60% 直接跳过。

---

## 七、文件说明

```
trend-collector/
├── trend_collector.py    # 主采集脚本
├── setup_feishu.py       # 一键建飞书表
├── config.example.yaml   # 配置模板
├── config.yaml           # 实际配置（setup 自动生成，已 .gitignore）
├── requirements.txt      # 依赖
├── run.sh                # 快捷运行脚本
├── 系统说明.md            # 完整技术说明
└── README.md
```

---

## 八、说明

- 本项目只读取各平台的**公开热榜数据**，不做登录抓取、不绕过任何反爬机制。
- NewsBing 是第三方公开聚合接口，请遵守其使用建议（读取间隔 ≥5 分钟，遇到 429 按 Retry-After 重试）。
- 采集到的内容版权归原平台与原作者，本工具仅用于选题参考。
- 请勿将采集结果直接搬运发布。

---

## License

MIT
