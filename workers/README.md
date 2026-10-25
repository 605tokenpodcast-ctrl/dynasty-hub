# Cloudflare Workers

| Worker | Folder | What it does |
|---|---|---|
| League bot | `league-bot/` | Trade alerts every 15 minutes, a weekly recap every Tuesday, matchup previews every Thursday, all posted to Discord and/or GroupMe. Writes the weekly "Dynasty Gazette" article for the Season Review tab when it has an Anthropic API key. |
| Live score cache | `live-scores/` | One cached live-score snapshot for every league, refreshed at most once a minute, so each visitor's browser stops calling Sleeper and Fleaflicker on its own. |
| Award cards | `award-cards/` | Turns any award into a 1200×630 image with a share link whose preview shows the card in group chats. |
| Fleaflicker proxy | `fleaflicker-proxy.js` | Existing `dawn-pine-2ee2` worker, deployed by hand. Unchanged. |

All three new workers fit in Cloudflare's free plan.

## One-time setup

### 1. Let GitHub deploy to Cloudflare

1. In Cloudflare, go to **My Profile → API Tokens → Create Token**, pick the **Edit Cloudflare Workers** template, and create it.
2. Copy your **Account ID** from the Workers & Pages overview page (right-hand side).
3. In GitHub, go to the repo's **Settings → Secrets and variables → Actions** and add:
   - `CLOUDFLARE_API_TOKEN`: the token from step 1
   - `CLOUDFLARE_ACCOUNT_ID`: the ID from step 2

### 2. Tell the bot where to post (pick one or both)

- **Discord:** channel settings → **Integrations → Webhooks → New Webhook → Copy Webhook URL**. Add it as the secret `DISCORD_WEBHOOK_URL`.
- **GroupMe:** create a bot at https://dev.groupme.com/bots for your group chat and add its Bot ID as the secret `GROUPME_BOT_ID`.

Optional secrets:

- `ANTHROPIC_API_KEY`: turns on the weekly Gazette articles. Each article is one short Claude request (about 7 a week).
- `BOT_ADMIN_KEY`: any password you like. It lets you run a job by hand, for example `https://dynasty-league-bot.<you>.workers.dev/run?job=recap&key=<password>&dry=1` (`dry=1` shows the messages without posting them).

### 3. Deploy

GitHub → **Actions → Deploy Cloudflare Workers → Run workflow**. It also runs on its own whenever a worker changes on `main`. The first run creates the bot's storage (a KV namespace) automatically.

### 4. Point the site at the workers

The workflow log prints each worker's URL (`https://<name>.<your-subdomain>.workers.dev`). Paste them into `index.html`:

| Constant in `index.html` | Worker URL |
|---|---|
| `LIVE_SCORES_ENDPOINT` | `https://dynasty-live-scores.<you>.workers.dev` |
| `AWARD_CARD_ENDPOINT` | `https://dynasty-award-cards.<you>.workers.dev` |
| `LEAGUE_BOT_ENDPOINT` | `https://dynasty-league-bot.<you>.workers.dev` |

Each one is optional: left empty, the site works exactly as before for that piece.

## Changing things

- **Leagues:** each worker's `wrangler.toml` lists the league IDs. When a Sleeper league rolls over to a new season ID, update it there as well as in `scripts/sync_leagues.py`.
- **Schedule:** the bot's cron times are in `league-bot/wrangler.toml` (UTC).
- **First trade-alert run:** the bot remembers the trades that already exist without announcing them, so the chat doesn't get flooded with old trades.
