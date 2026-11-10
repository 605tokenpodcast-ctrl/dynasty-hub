"""Read and update leagues.json, the one list of leagues shared by the syncs, the site and the workers."""
import json
import os
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(ROOT, 'leagues.json')
MANAGERS_FILE = os.path.join(ROOT, 'managers_config.json')


def load():
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def save(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        f.write('\n')


def leagues(platform=None):
    return [lg for lg in load()['leagues'] if platform is None or lg['platform'] == platform]


def set_league_id(old_id, new_id):
    """Point the league currently stored as `old_id` at `new_id` (a Sleeper league renewing for a new season)."""
    config = load()
    for lg in config['leagues']:
        if lg['id'] == old_id:
            lg['id'] = new_id
    save(config)


def record_str(wins, losses, ties=0):
    """A standings record: 'W-L', or 'W-L-T' when there are ties (the site reads both)."""
    return f"{wins}-{losses}-{ties}" if ties else f"{wins}-{losses}"


CENTRAL = ZoneInfo('America/Chicago')


def central_date(ms):
    """'M/D/YYYY' in US Central time for an epoch time in milliseconds (seconds also accepted), '' if missing.
    The leagues are in Central time, so a trade made at 9pm isn't dated the next day (UTC)."""
    try:
        v = float(ms)
    except (TypeError, ValueError):
        return ''
    if v <= 0:
        return ''
    if v < 1e11:   # seconds, not ms
        v *= 1000.0
    d = datetime.fromtimestamp(v / 1000.0, tz=timezone.utc).astimezone(CENTRAL)
    return f"{d.month}/{d.day}/{d.year}"


def manager_aliases():
    """(aliasOverrides, exactAliases) from managers_config.json, as the site reads them."""
    try:
        with open(MANAGERS_FILE, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        cfg = {}
    return cfg.get('aliasOverrides') or {}, {k.lower(): v for k, v in (cfg.get('exactAliases') or {}).items()}


def master_owner(label, aliases=None):
    """The manager behind a team label, the same way getMasterOwner in index.html works it out:
    "Team Name (username)" -> username, with aliasOverrides (text in the label) and exactAliases applied."""
    overrides, exact = aliases or manager_aliases()
    text = str(label or '').strip()
    low = text.lower()
    for key, name in overrides.items():
        if key in low:
            return name
    m = re.search(r'\(([^)]+)\)\s*$', text)
    user = (m.group(1) if m else text).strip()
    return overrides.get(user.lower()) or exact.get(user.lower()) or user
