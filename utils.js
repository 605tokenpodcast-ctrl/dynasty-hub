// utils.js — Pure utility functions for Dynasty Hub
// Loaded before app.js. These have no side effects and can be used anywhere.

function normalizePlayerName(name) {
    return String(name || '')
        .toLowerCase()
        .replace(/[.'']/g, '')
        .replace(/\b(jr|sr|ii|iii|iv|v)\b/g, '')
        .replace(/\s+/g, ' ')
        .trim();
}

const PICK_KEY_RE = /^(20\d\d) (\d+)(?:st|nd|rd|th)(?: \((Early|Mid|Late)\))?$/;

function buildValueFormat(players) {
    const norm = {};
    const picks = {}; // round -> year -> { Early, Mid, Late, base }
    Object.keys(players || {}).forEach(k => {
        const pm = k.match(PICK_KEY_RE);
        if (pm) {
            const byYear = picks[pm[2]] = picks[pm[2]] || {};
            const slot = byYear[pm[1]] = byYear[pm[1]] || {};
            slot[pm[3] || 'base'] = players[k];
            return;
        }
        norm[normalizePlayerName(k)] = players[k];
    });
    return { players: players || {}, norm, picks };
}

function getValueFormat(leagueName) {
    const key = leagueValueFormats[String(leagueName || '').trim().toLowerCase()];
    return valueFormats[key] || valueFormats[defaultValueFormat];
}

function getMasterOwner(teamString) {
    const trimmed = String(teamString || '').trim();
    if (!trimmed) return '';
    const lowerTrimmed = trimmed.toLowerCase();
    
    for (let key in aliasOverrides) {
        if (lowerTrimmed.includes(key)) {
            return aliasOverrides[key];
        }
    }

    const match = trimmed.match(/\(([^)]+)\)\s*$/);
    const username = (match && match[1]) ? match[1].trim() : trimmed;
    const lowerUser = username.toLowerCase();
    if (aliasOverrides[lowerUser]) return aliasOverrides[lowerUser];
    // Exact (case-insensitive) username matches, e.g. Fleaflicker -> Sleeper identities
    if (exactAliases[lowerUser]) return exactAliases[lowerUser];
    return username;
}

function getSectionType(col0) {
    const s = String(col0 || '').trim().toUpperCase();
    if (!s.startsWith('---')) return null;
    if (s.includes('LEAGUE PROFILE')) return 'profile';
    if (s.includes('STANDINGS')) return 'standings';
    if (s.includes('CURRENT ROSTERS')) return 'rosters';
    if (s.includes('TRADE HISTORY')) return 'trades';
    if (s.includes('WEEKLY LINEUPS')) return 'lineups';
    if (s.includes('FREE AGENT MOVES')) return 'moves';
    if (s.includes('BOX SCORES')) return 'boxscores';
    if (s.includes('MATCHUPS')) return 'matchups';
    if (s.includes('DRAFT HISTORY')) return 'drafts';
    return 'other';
}

function isColumnHeaderRow(col0) {
    const c = String(col0 || '').trim().toLowerCase();
    return c === 'team' || c === 'owner' || c === 'manager' || c.includes('player') || c === 'position';
}
