"""Copy the league list from leagues.json into the workers' wrangler.toml files.

Run by the deploy-workers workflow before each deploy, so a league that renews for a new season
(the Sleeper sync saves its new ID to leagues.json) reaches the workers too. Safe to run locally.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import league_config  # noqa: E402

ROOT = os.path.dirname(league_config.CONFIG_FILE)


def set_var(path, key, value):
    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()
    pattern = re.compile(rf"^{key} = ('''.*?'''|\"[^\"]*\")", re.M | re.S)
    if not pattern.search(text):
        sys.exit(f"{key} not found in {path}")
    text = pattern.sub(lambda _: f"{key} = {value}", text, count=1)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def main():
    # Only leagues still being played: merge_into / end_season entries are history-only
    active = [lg for lg in league_config.leagues() if not lg.get('merge_into') and not lg.get('end_season')]
    sleeper = [lg['id'] for lg in active if lg['platform'] == 'sleeper']
    flea = [lg['id'] for lg in active if lg['platform'] == 'fleaflicker']

    live = os.path.join(ROOT, 'workers', 'live-scores', 'wrangler.toml')
    set_var(live, 'SLEEPER_LEAGUES', json.dumps(','.join(sleeper)))
    set_var(live, 'FLEA_LEAGUES', json.dumps(','.join(flea)))

    bot_leagues = [{"name": lg['name'], "id": lg['id'], "platform": lg['platform']} for lg in active]
    body = ',\n'.join('  ' + json.dumps(lg, ensure_ascii=False) for lg in bot_leagues)
    set_var(os.path.join(ROOT, 'workers', 'league-bot', 'wrangler.toml'), 'LEAGUES', f"'''[\n{body}\n]'''")
    print(f"workers configured for {len(sleeper)} Sleeper and {len(flea)} Fleaflicker leagues")


if __name__ == '__main__':
    main()
