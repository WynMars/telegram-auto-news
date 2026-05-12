# 中文推特新闻聚合机器人

> 自动每小时抓取全球新闻 → 按话题过滤（中共人权 / 美国政坛 / 科技 / 经济 / 全球突发）→ Claude 中文总结 + 推文钩子 → 推送到 Telegram

完全运行在 GitHub Actions 上，**零服务器、零运维成本**。Anthropic API 月成本约 $5-15（取决于推送量）。

---

## 一、首次部署（约 15 分钟）

### 1. 准备 3 个密钥

#### a) Anthropic API Key
- 打开 https://console.anthropic.com/settings/keys
- 创建新 key，格式 `sk-ant-...`
- 充值 $5 即可起步

#### b) Telegram Bot Token
- 在 Telegram 里搜索 `@BotFather` → `/newbot` → 起名 → 拿到 `123456789:AAAAA...` 格式的 token
- 跟你的新 bot 发任意一条消息（点 Start）

#### c) Telegram Chat ID
- 推送给自己：在 Telegram 搜 `@userinfobot`，发 `/start`，它返回的 ID 就是你的 chat_id
- 推送到群组：把你的 bot 拉进群 → 在群里发条消息 → 浏览器访问 `https://api.telegram.org/bot<你的TOKEN>/getUpdates` → 找 `"chat":{"id":-100xxx...}`，群组 ID 是负数

### 2. 上传到 GitHub

```bash
# 在本地解压本项目，进入目录
cd news-bot
git init
git add .
git commit -m "init news bot"

# 在 github.com 新建一个 repo（私有公有都行），然后：
git remote add origin git@github.com:你的用户名/news-bot.git
git branch -M main
git push -u origin main
```

### 3. 在 GitHub 仓库里配置 Secrets

打开仓库 → **Settings → Secrets and variables → Actions → New repository secret**

依次添加 3 个：

| Name                  | Value                            |
| --------------------- | -------------------------------- |
| `ANTHROPIC_API_KEY`   | `sk-ant-...`                     |
| `TELEGRAM_BOT_TOKEN`  | `123456789:AAAAA...`             |
| `TELEGRAM_CHAT_ID`    | 你的 chat ID（数字）             |

### 4. 手动测试一次

在仓库的 **Actions → News Bot → Run workflow** 点击运行。等 1-2 分钟，Telegram 应该会收到第一批推送。

成功后什么都不用做，**之后每个整点会自动跑一次**。

---

## 二、日常使用

- **修改话题/关键词**：编辑 `keywords.yaml`，commit 后下个整点生效
- **增删新闻源**：编辑 `sources.yaml`，添加任意 RSS URL
- **暂停**：在 Actions 页面点 `Disable workflow`；恢复点 `Enable`
- **手动触发**：Actions 页面随时 `Run workflow`，方便测试改动
- **查看运行日志**：Actions 页面每次运行都有完整 log，能看到哪些源失败、抓到几条、Claude 摘要是否成功

---

## 三、本地测试（可选）

```bash
cd news-bot
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 复制 .env.example 为 .env 并填入密钥
cp .env.example .env

# 加载环境变量并运行
export $(cat .env | xargs)         # mac/linux
python news_bot.py
```

---

## 四、消息长什么样

每条新闻一条 Telegram 消息，结构：

```
🔥 标题（中文）
🇨🇳中共/人权 ⚡全球突发 · 📡 来源

📝 2-3 句关键事实总结

💡 为什么重要
一句话立场/解读

✍️ 推文钩子
可直接复制改写成推文的开头

🔗 原文链接
```

---

## 五、调优建议

### 推送太多 / 太少？
编辑 `.github/workflows/news.yml` 里的 env：
- `MAX_ARTICLES_PER_RUN`: 默认 8，太吵改 5；信息焦虑改 12
- `LOOKBACK_HOURS`: 默认 3，意味着比当前晚 3 小时内的新闻才纳入

### 想加更多中文源？
在 `sources.yaml` 里加，常用的：
- 端传媒、明镜、纵览中国、博讯、新世纪、追新闻
- 用 Google News RSS 搜任意关键词都行：
  `https://news.google.com/rss/search?q=关键词&hl=zh-CN&gl=US&ceid=US:zh`

### 想换其他模型？
在 workflow env 里加 `ANTHROPIC_MODEL: claude-sonnet-4-6` 等。Haiku 4.5 是速度/成本最优解，质量已经够用。

### 状态去重出问题？
直接删 `state/seen.json` 里的内容（恢复成空 `{"seen": {}, "last_run": null}`），下次运行会从头开始。

---

## 六、成本估算

- **GitHub Actions**：公开仓库无限免费；私有仓库每月免费 2000 分钟，本机器人每次运行约 1-2 分钟，24×30=720 分钟/月，远低于上限
- **Anthropic API**（Haiku 4.5）：每条新闻约 600 tokens 输入 + 250 tokens 输出。每天 240 条 = 月成本约 $5-10
- **Telegram**：免费

---

## 七、常见问题

**Q: GitHub Actions 60 天没活动会暂停定时任务**
A: 本 bot 每小时都在 commit state，会持续保持活跃。但如果你长期 disable 又忘了 enable，会被自动暂停，重新 enable 即可。

**Q: 某个 RSS 源总是失败**
A: 看 Actions 日志里 `✗ 源名称: ...` 的错误。多数是源换了 URL 或挂了，从 sources.yaml 删掉就行。

**Q: 漏了重要新闻**
A: 检查 keywords.yaml 是否覆盖该话题的关键词，或在 sources.yaml 加更专精的源/Google News 搜索。

**Q: 想推送到多个 chat**
A: 把 `TELEGRAM_CHAT_ID` 改成逗号分隔的多个 ID，然后改 `news_bot.py` 里 `send_telegram` 调用部分循环发送（小修改）。

---

## 八、扩展思路

- 加个 `--dry-run` 模式，不发 Telegram 只打印
- 接入 X DM（需要 X API 付费）
- 加 sentiment / bias 标注
- 把每天总结打包成日报 markdown，commit 进 docs/ 文件夹做个静态站
