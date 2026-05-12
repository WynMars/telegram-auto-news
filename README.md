# MERIDIAN

> Global news intelligence for independent Chinese-language creators

Meridian has two parts:

- **Frontend** — 3 static HTML pages you can open directly in any browser
- **Backend engine** — Python script that fetches RSS feeds, summarises articles using Gemini 2.5 Flash, and pushes formatted digests to Telegram. Runs on GitHub Actions (no server required).

---

## Project structure

```
meridian/
├── README-EN.md               This file
├── README.md                  Chinese README
│
├── 1-landing.html             Marketing landing page
├── 2-onboarding.html          3-step user onboarding flow
├── 3-dashboard.html           Main product dashboard
│
└── backend/
    ├── news_bot.py            Core Python script
    ├── sources.yaml           RSS feed list (editable)
    ├── keywords.yaml          Topic keyword list (editable)
    ├── requirements.txt       Python dependencies
    ├── .env.example           Environment variable template
    ├── .github/workflows/
    │   └── news.yml           GitHub Actions hourly cron job
    └── state/seen.json        Deduplication state (auto-managed)
```

---

## Part 1 — Frontend (HTML pages)

The three HTML files are fully static — no build step, no dependencies.

### Option A: Open directly (simplest)

Double-click any `.html` file and it opens in your browser. Works fine, though Google Fonts may not load on some browsers due to `file://` protocol restrictions.

### Option B: Local dev server (recommended)

For best results, serve the files over HTTP.

**Python (built-in, no install needed):**

```bash
cd path/to/meridian
python3 -m http.server 8000
```

**Node.js:**

```bash
cd path/to/meridian
npx serve
```

Then open in your browser:

| Page | URL |
|---|---|
| Landing page | http://localhost:8000/1-landing.html |
| Onboarding | http://localhost:8000/2-onboarding.html |
| Dashboard | http://localhost:8000/3-dashboard.html |

Press `Ctrl + C` to stop the server.

### Deploying the frontend publicly

| Method | Steps |
|---|---|
| **Netlify Drop** (fastest) | Go to https://app.netlify.com/drop and drag the `meridian` folder in. Done. |
| **Vercel** | Push to GitHub, then import the repo at https://vercel.com/new |
| **GitHub Pages** | Push to GitHub → Settings → Pages → set source to `main` branch |

---

## Part 2 — Backend engine

The backend script runs on a schedule, fetches news, uses Gemini 2.5 Flash to write Chinese summaries and tweet hooks, and delivers them to Telegram.

### Prerequisites

- Python 3.11+
- A [Gemini API key](https://aistudio.google.com/apikey) (free tier available)
- A Telegram bot token and chat ID (instructions below)

### Get your API keys

#### Gemini API key

1. Go to https://aistudio.google.com/apikey
2. Click **Create API key** and copy it (starts with `AIzaSy...`)
3. The free tier is enough to get started

#### Telegram bot token

1. Open Telegram and search for `@BotFather`
2. Send `/newbot`, follow the prompts, and copy the token it gives you (format: `123456789:AAAA...`)
3. Start a conversation with your new bot by pressing **Start**

#### Telegram chat ID

- **Personal chat:** Search `@userinfobot` in Telegram, send `/start`, and it returns your ID
- **Group chat:** Add your bot to a group, send a message, then open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser and find `"chat":{"id":-100xxx...}` (group IDs are negative)

### Running locally

```bash
cd meridian/backend

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Open .env and fill in your three keys
```

Your [backend/.env](backend/.env.example) should look like this:

```env
GEMINI_API_KEY=AIzaSy-xxxxxxxxxxxxxxxxxxxx
TELEGRAM_BOT_TOKEN=123456789:AAAAAA-BBBBBBBBBBBBB
TELEGRAM_CHAT_ID=123456789
```

Load the variables and run:

```bash
# macOS / Linux
export $(cat .env | xargs)
python news_bot.py

# Windows (PowerShell)
Get-Content .env | ForEach-Object { $parts = $_ -split '=', 2; [System.Environment]::SetEnvironmentVariable($parts[0], $parts[1]) }
python news_bot.py
```

### Deploying to GitHub Actions (automated, zero-server)

This is the recommended way to run the bot in production. It runs every hour automatically for free.

1. Push the `backend/` folder contents to a new GitHub repository
2. Go to your repo → **Settings → Secrets and variables → Actions → New repository secret**
3. Add these three secrets:

| Secret name | Value |
|---|---|
| `GEMINI_API_KEY` | `AIzaSy-...` |
| `TELEGRAM_BOT_TOKEN` | `123456789:AAAA...` |
| `TELEGRAM_CHAT_ID` | Your numeric chat ID |

4. Go to **Actions → News Bot → Run workflow** and trigger a manual run to test
5. If you receive a Telegram message, the setup is complete. The bot will now run automatically at the top of every hour

The workflow file is at [backend/.github/workflows/news.yml](backend/.github/workflows/news.yml).

---

## Configuration

### Topics and keywords — `backend/keywords.yaml`

Five built-in topics, each with English and Chinese keywords:

| Topic | Description |
|---|---|
| `china_human_rights` | CCP, Xinjiang, Hong Kong, dissidents, political prisoners |
| `us_politics` | US Congress, White House, elections, Supreme Court |
| `tech` | AI, semiconductors, Big Tech, chip bans |
| `economy` | Federal Reserve, inflation, tariffs, interest rates |
| `global_breaking` | Wars, disasters, coups, Taiwan, Ukraine, Israel |

Add or remove terms freely. English terms use word-boundary matching; Chinese/CJK terms use substring matching.

### News sources — `backend/sources.yaml`

Add any RSS feed URL. Works with standard RSS/Atom feeds and Google News search feeds:

```
https://news.google.com/rss/search?q=YOUR+KEYWORDS&hl=en-US&gl=US&ceid=US:en
```

### Optional environment variables

| Variable | Default | Description |
|---|---|---|
| `MAX_ARTICLES_PER_RUN` | `8` | Max articles sent per run |
| `LOOKBACK_HOURS` | `3` | Only include articles published in the last N hours |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model to use for summaries |

---

## What a Telegram message looks like

```
🔥 Article title (Chinese)
🇺🇸US Politics · 📡 Source name

📝 2–3 sentence summary covering who/what/when/where

💡 Why it matters
One-line editorial take

✍️ Tweet hook
A ready-to-use opening line for a tweet

🔗 Original article link
```

---

## Cost estimate

| Service | Cost |
|---|---|
| GitHub Actions | Free for public repos; private repos get 2,000 min/month free (bot uses ~720 min/month) |
| Gemini API (2.5 Flash) | Free tier available; paid tier ~$0.075/1M input tokens — well under $5/month at this volume |
| Telegram | Free |

---

## Troubleshooting

**Bot ran but no Telegram messages arrived**
Check the Actions run log for lines starting with `✗` (feed failures) or `No new relevant articles`. The bot skips articles older than `LOOKBACK_HOURS` and articles it has already sent.

**A feed keeps failing**
Open the Actions log and look for `✗ feed-name: ...`. The feed URL may have changed or the site may be down. Remove or update the entry in `sources.yaml`.

**Missing articles on an important topic**
Check `keywords.yaml` — add relevant keywords for that topic. You can also add a targeted Google News RSS feed for that search term.

**GitHub Actions stopped running automatically**
GitHub pauses scheduled workflows after 60 days of repo inactivity. The bot commits `state/seen.json` each run, which keeps it active. If you disabled and re-enabled the workflow after a long pause, just re-enable it from the Actions tab.

**Want to reset deduplication (resend all recent articles)**
Edit `backend/state/seen.json` and replace its contents with `{"seen": {}, "last_run": null}`, then commit.

---

## Customisation quick reference

| Goal | Where to change |
|---|---|
| Rename the brand | Search and replace "MERIDIAN" in the HTML files |
| Change pricing | Edit the `tier-price` section in `1-landing.html` |
| Change topic tracks | Edit `keywords.yaml` and the persona section in the HTML files |
| Add news sources | Add RSS URLs to `backend/sources.yaml` |
| Change run frequency | Edit the `cron` line in `backend/.github/workflows/news.yml` |
| Change Gemini model | Set `GEMINI_MODEL` in the workflow env or `.env` file |
| Change the colour scheme | Edit the `:root { }` CSS variables at the top of each HTML file |
