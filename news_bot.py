#!/usr/bin/env python3
"""
News Bot — 中文推特创作者的自动化新闻聚合器
- 抓取 RSS 源
- 按关键词过滤话题（中共人权 / 美国政坛 / 科技 / 经济 / 全球突发）
- Gemini 2.5 Flash 生成中文摘要 + 推文钩子
- 推送到 Telegram
- 在 state/seen.json 中持久化去重数据
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import feedparser
import httpx
import yaml
from google import genai

# ---- Config -----------------------------------------------------------------

ROOT = Path(__file__).parent
STATE_DIR = ROOT / "state"
STATE_FILE = STATE_DIR / "seen.json"
SOURCES_FILE = ROOT / "sources.yaml"
KEYWORDS_FILE = ROOT / "keywords.yaml"

MAX_ARTICLES_PER_RUN = int(os.getenv("MAX_ARTICLES_PER_RUN", "8"))
LOOKBACK_HOURS = int(os.getenv("LOOKBACK_HOURS", "3"))
DEDUP_KEEP = 3000
SUMMARY_BATCH_SIZE = 5
HTTP_TIMEOUT = 15
REQUEST_DELAY = 0.3
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("news-bot")

TOPIC_EMOJI = {
    "china_human_rights": "🇨🇳",
    "us_politics": "🇺🇸",
    "tech": "🤖",
    "economy": "💰",
    "global_breaking": "⚡",
}
TOPIC_LABEL = {
    "china_human_rights": "中共/人权",
    "us_politics": "美国政坛",
    "tech": "科技",
    "economy": "经济",
    "global_breaking": "全球突发",
}


# ---- Data model -------------------------------------------------------------

@dataclass
class Article:
    title: str
    url: str
    source: str
    published: Optional[str]
    summary_raw: str
    topics: list = field(default_factory=list)
    score: float = 0.0

    @property
    def url_hash(self) -> str:
        return hashlib.sha256(canonical_url(self.url).encode()).hexdigest()[:16]

    @property
    def title_key(self) -> str:
        # Coarse normalization for cross-source dedup
        t = re.sub(r"[^\w\s]", "", self.title.lower())
        return " ".join(t.split())[:80]


# ---- Utilities --------------------------------------------------------------

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "cmp", "smid", "partner",
}


def canonical_url(url: str) -> str:
    try:
        p = urlparse(url)
        params = [(k, v) for k, v in parse_qsl(p.query) if k.lower() not in TRACKING_PARAMS]
        return urlunparse(p._replace(query=urlencode(params), fragment=""))
    except Exception:
        return url


def html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"seen": {}, "last_run": None}
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.warning(f"Could not read state, starting fresh: {e}")
        return {"seen": {}, "last_run": None}


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    seen = state.get("seen", {})
    if len(seen) > DEDUP_KEEP:
        # Keep most recent N entries by timestamp
        sorted_items = sorted(seen.items(), key=lambda kv: kv[1], reverse=True)
        state["seen"] = dict(sorted_items[:DEDUP_KEEP])
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ---- Fetching ---------------------------------------------------------------

def fetch_feed(name: str, url: str) -> list[Article]:
    articles: list[Article] = []
    try:
        with httpx.Client(
            timeout=HTTP_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "NewsBot/1.0 (+github.com)"},
        ) as client:
            r = client.get(url)
            r.raise_for_status()
            content = r.content

        parsed = feedparser.parse(content)
        for entry in parsed.entries[:30]:
            title = (entry.get("title") or "").strip()
            link = (entry.get("link") or "").strip()
            if not title or not link:
                continue

            published = None
            for field_name in ("published_parsed", "updated_parsed"):
                t = entry.get(field_name)
                if t:
                    try:
                        published = datetime(*t[:6], tzinfo=timezone.utc).isoformat()
                        break
                    except (TypeError, ValueError):
                        pass

            summary = entry.get("summary") or entry.get("description") or ""
            summary = re.sub(r"<[^>]+>", " ", summary)
            summary = re.sub(r"\s+", " ", summary).strip()[:500]

            articles.append(Article(
                title=title,
                url=link,
                source=name,
                published=published,
                summary_raw=summary,
            ))
        log.info(f"  ✓ {name}: {len(articles)} entries")
    except Exception as e:
        log.warning(f"  ✗ {name}: {type(e).__name__}: {e}")
    return articles


def fetch_all(sources: dict) -> list[Article]:
    out: list[Article] = []
    for category, feeds in sources.items():
        log.info(f"Fetching category: {category}")
        for feed_name, url in feeds.items():
            out.extend(fetch_feed(feed_name, url))
            time.sleep(REQUEST_DELAY)
    log.info(f"Fetched total: {len(out)} entries")
    return out


# ---- Filtering / ranking ----------------------------------------------------

def match_topics(article: Article, keywords: dict) -> list[str]:
    text = (article.title + " " + article.summary_raw).lower()
    matched: list[str] = []
    for topic, terms in keywords.items():
        for term in terms:
            t = str(term).lower()
            # English (ASCII) words use word-boundary; CJK uses substring
            if re.fullmatch(r"[\x00-\x7f\s]+", t):
                if re.search(rf"\b{re.escape(t)}\b", text):
                    matched.append(topic)
                    break
            else:
                if t in text:
                    matched.append(topic)
                    break
    return matched


def score_article(article: Article, corroboration: int) -> float:
    topic_score = min(len(article.topics) * 0.3, 1.0)

    recency_score = 0.5
    if article.published:
        try:
            pub = datetime.fromisoformat(article.published.replace("Z", "+00:00"))
            age_h = (datetime.now(timezone.utc) - pub).total_seconds() / 3600
            recency_score = max(0.0, 1.0 - age_h / 24)
        except ValueError:
            pass

    corrob_score = min((corroboration - 1) * 0.4, 1.0)

    # Weights: recency 30%, topics 40%, corroboration 30%
    return recency_score * 0.3 + topic_score * 0.4 + corrob_score * 0.3


def filter_and_rank(
    articles: list[Article],
    keywords: dict,
    seen: dict,
) -> list[Article]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    candidates: list[Article] = []
    for a in articles:
        if a.url_hash in seen:
            continue
        a.topics = match_topics(a, keywords)
        if not a.topics:
            continue
        if a.published:
            try:
                pub = datetime.fromisoformat(a.published.replace("Z", "+00:00"))
                if pub < cutoff:
                    continue
            except ValueError:
                pass
        candidates.append(a)

    # Group similar titles for corroboration
    title_groups: dict[str, list[Article]] = {}
    for a in candidates:
        title_groups.setdefault(a.title_key, []).append(a)

    final: list[Article] = []
    seen_titles = set()
    for a in candidates:
        if a.title_key in seen_titles:
            continue
        seen_titles.add(a.title_key)
        a.score = score_article(a, len(title_groups[a.title_key]))
        final.append(a)

    final.sort(key=lambda x: x.score, reverse=True)
    return final[:MAX_ARTICLES_PER_RUN]


# ---- Summarization ----------------------------------------------------------

def summarize_articles(articles: list[Article], client: genai.Client) -> dict:
    """Returns {url_hash: summary_dict}."""
    results: dict[str, dict] = {}
    for i in range(0, len(articles), SUMMARY_BATCH_SIZE):
        batch = articles[i:i + SUMMARY_BATCH_SIZE]
        batch_input = "\n\n".join(
            f"[{idx}] 标题: {a.title}\n来源: {a.source}\n原文摘要: {a.summary_raw[:400]}\nURL: {a.url}"
            for idx, a in enumerate(batch)
        )

        prompt = f"""你是为中文推特创作者服务的新闻编辑。下面是 {len(batch)} 条新闻。

{batch_input}

请为每一条用简体中文输出一个对象，字段如下：
- "index": 编号（整数）
- "title_zh": 中文标题（不超过 30 字）
- "summary": 2-3 句中文总结，覆盖关键事实（who/what/when/where）
- "why_matters": 一句话解释为什么这条值得关注（推特创作者视角）
- "tweet_hook": 一句可直接用作推文开头的钩子（中文，不加 hashtag，不加引号）

只返回 JSON 数组，不要任何其他文字、不要 markdown 代码块、不要前后说明。
格式：[{{"index": 0, "title_zh": "...", "summary": "...", "why_matters": "...", "tweet_hook": "..."}}, ...]"""

        try:
            resp = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
            )
            text = resp.text.strip()
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            data = json.loads(text)
            for item in data:
                idx = item.get("index")
                if isinstance(idx, int) and 0 <= idx < len(batch):
                    results[batch[idx].url_hash] = item
        except Exception as e:
            log.error(f"Summarization batch {i // SUMMARY_BATCH_SIZE} failed: {e}")
    return results


# ---- Telegram ---------------------------------------------------------------

def format_message(article: Article, summary: dict) -> str:
    topics_str = " ".join(
        f"{TOPIC_EMOJI.get(t, '#')}{TOPIC_LABEL.get(t, t)}" for t in article.topics
    )
    title = html_escape(summary.get("title_zh") or article.title)
    summary_text = html_escape(summary.get("summary", ""))
    why = html_escape(summary.get("why_matters", ""))
    hook = html_escape(summary.get("tweet_hook", ""))

    return (
        f"🔥 <b>{title}</b>\n"
        f"{topics_str} · 📡 {html_escape(article.source)}\n\n"
        f"📝 {summary_text}\n\n"
        f"💡 <b>为什么重要</b>\n{why}\n\n"
        f"✍️ <b>推文钩子</b>\n<i>{hook}</i>\n\n"
        f"🔗 <a href=\"{html_escape(article.url)}\">原文链接</a>"
    )


def send_telegram(token: str, chat_id: str, text: str) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            r = client.post(url, json=payload)
            if r.status_code != 200:
                log.error(f"Telegram error {r.status_code}: {r.text[:200]}")
                return False
            return True
    except Exception as e:
        log.error(f"Telegram send failed: {e}")
        return False


# ---- Main -------------------------------------------------------------------

def main() -> int:
    api_key = os.getenv("GEMINI_API_KEY")
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
    tg_chat = os.getenv("TELEGRAM_CHAT_ID")
    if not api_key:
        log.error("GEMINI_API_KEY not set")
        return 2
    if not tg_token or not tg_chat:
        log.error("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
        return 2

    sources = load_yaml(SOURCES_FILE)
    keywords = load_yaml(KEYWORDS_FILE)
    state = load_state()
    seen = state.get("seen", {})

    log.info(
        f"Loaded {sum(len(v) for v in sources.values())} feeds, "
        f"{sum(len(v) for v in keywords.values())} keywords, "
        f"{len(seen)} seen URLs"
    )

    articles = fetch_all(sources)
    if not articles:
        log.warning("No articles fetched (all feeds may have failed)")
        return 0

    selected = filter_and_rank(articles, keywords, seen)
    log.info(f"Selected {len(selected)} articles to summarize")

    if not selected:
        log.info("No new relevant articles this hour")
        state["last_run"] = datetime.now(timezone.utc).isoformat()
        save_state(state)
        return 0

    client = genai.Client(api_key=api_key)
    summaries = summarize_articles(selected, client)
    log.info(f"Got {len(summaries)} summaries from Claude")

    sent = 0
    now_ts = int(time.time())
    for a in selected:
        s = summaries.get(a.url_hash)
        if not s:
            log.warning(f"No summary for: {a.title[:60]}")
            continue
        if send_telegram(tg_token, tg_chat, format_message(a, s)):
            sent += 1
            seen[a.url_hash] = now_ts
        time.sleep(0.5)  # Telegram polite throttle

    log.info(f"Sent {sent}/{len(selected)} messages to Telegram")

    state["seen"] = seen
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
