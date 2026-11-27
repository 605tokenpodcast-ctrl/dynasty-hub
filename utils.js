// utils.js — Pure, side-effect-free helpers
// These functions do not reference any variables defined in app.js

function normalizePlayerName(name) {
    return String(name || '')
        .toLowerCase()
        .replace(/[.'']/g, '')
        .replace(/\b(jr|sr|ii|iii|iv|v)\b/g, '')
        .replace(/\s+/g, ' ')
        .trim();
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
