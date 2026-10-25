"""Read and update leagues.json, the one list of leagues shared by the syncs, the site and the workers."""
import json
import os

CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'leagues.json')


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
