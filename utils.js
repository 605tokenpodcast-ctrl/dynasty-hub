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

// ---- Moved from app.js (pure helpers: no DOM, no app.js state) ----

function highlightTrend(btn) {
    const card = btn.closest('[data-trend-league]');
    const owner = btn.dataset.owner;
    const on = card.dataset.hl !== owner;
    card.dataset.hl = on ? owner : '';
    card.querySelectorAll('polyline').forEach(pl => {
        const me = pl.dataset.owner === owner;
        pl.setAttribute('stroke-width', on && me ? '4' : '2');
        pl.setAttribute('opacity', on && !me ? '0.2' : '1');
    });
    card.querySelectorAll('button[data-owner]').forEach(b => b.classList.toggle('bg-slate-800', on && b.dataset.owner === owner));
}

function powerMoveHtml(move, hasPrev) {
    if (!hasPrev || move === null) return '<span class="text-slate-500 text-xs font-bold w-8 text-center">—</span>';
    if (move > 0) return `<span class="text-emerald-400 text-xs font-bold w-8 text-center">▲${move}</span>`;
    if (move < 0) return `<span class="text-rose-400 text-xs font-bold w-8 text-center">▼${-move}</span>`;
    return '<span class="text-slate-500 text-xs font-bold w-8 text-center">•</span>';
}

// Current streak per manager in one league this season: { owner: { kind: 'W' | 'L', n } }
function notesStreaks(games) {
    const by = {};
    [...games].sort((a, b) => a.weekNum - b.weekNum).forEach(g => {
        [[g.t1, g.s1, g.s2], [g.t2, g.s2, g.s1]].forEach(([o, my, op]) => {
            const res = my > op ? 'W' : my < op ? 'L' : 'T';
            const s = by[o];
            by[o] = s && s.kind === res ? { kind: res, n: s.n + 1 } : { kind: res, n: 1 };
        });
    });
    return by;
}

function notesSectionHtml(idx, title, lines) {
    return `
        <div class="bg-slate-900/60 border border-slate-800 rounded-lg p-3 sm:p-4 space-y-2">
            <div class="flex justify-between items-center gap-2">
                <h4 class="font-bold text-white">${escHtml(title)}</h4>
                <button type="button" onclick="copyShowNotes(this, ${idx})" class="shrink-0 bg-slate-900 border border-slate-700 hover:border-accent rounded-lg px-2.5 py-1 text-xs font-semibold text-slate-200">📋 Copy</button>
            </div>
            <ul id="notes-list-${idx}" class="space-y-1.5 text-slate-300 text-[13px] leading-snug">${lines.map(l => `<li>${escHtml(l)}</li>`).join('')}</ul>
        </div>`;
}

// One week's scores as [[who, points], ...] -> [[who, 'w' | 'l' | 't'], ...] against the week's median
function medianResults(list) {
    const sorted = list.map(x => x[1]).sort((a, b) => a - b);
    const n = sorted.length;
    if (n < 2) return [];
    const med = n % 2 ? sorted[(n - 1) / 2] : (sorted[n / 2 - 1] + sorted[n / 2]) / 2;
    return list.map(([who, pts]) => [who, pts > med ? 'w' : pts < med ? 'l' : 't']);
}

// Backup check: a podium placement always counts as a playoff appearance.
// The main rule (top 6 / top 7 in All Flex Zone) is applied in collectRecordsData.
function madePlayoffs(placement) {
    const p = String(placement || '').toLowerCase();
    if (!p.trim()) return false;
    if (/miss|did not|dnq|no playoff|non-playoff/.test(p)) return false;
    return /champion|runner|3rd|4th|playoff/.test(p);
}

// Longest run of consecutive wins ('W') or losses ('L') for one manager inside one league (carries across seasons)
function findStreaks(games, kind) {
    const byKey = {};
    games.forEach(g => {
        [[g.t1, g.s1, g.s2], [g.t2, g.s2, g.s1]].forEach(([owner, my, opp]) => {
            const k = g.league + '||' + owner;
            (byKey[k] = byKey[k] || []).push({ g, res: my > opp ? 'W' : (my < opp ? 'L' : 'T') });
        });
    });

    const best = [];
    Object.keys(byKey).forEach(k => {
        const [league, owner] = k.split('||');
        const arr = byKey[k].sort((a, b) => (a.g.season - b.g.season) || (a.g.weekNum - b.g.weekNum));
        let len = 0, start = null, last = null, top = null;
        const close = () => { if (len > 0 && (!top || len > top.len)) top = { league, owner, len, start, end: last }; };
        arr.forEach(x => {
            if (x.res === kind) {
                if (len === 0) start = x.g;
                len++; last = x.g;
            } else { close(); len = 0; }
        });
        close();
        if (top) best.push(top);
    });
    return best.sort((a, b) => b.len - a.len);
}

function findPlayoffStreaks(standings) {
    const byKey = {};
    standings.forEach(s => {
        if (!s.complete) return; // ignore seasons still in progress
        const k = s.league + '||' + s.owner;
        if (!byKey[k]) byKey[k] = {};
        byKey[k][s.season] = s.madePlayoffs;
    });

    const best = [];
    Object.keys(byKey).forEach(k => {
        const [league, owner] = k.split('||');
        const seasons = Object.keys(byKey[k]).map(Number).sort((a, b) => a - b);
        let len = 0, startSeason = 0, prev = null, top = null;
        seasons.forEach(season => {
            const made = byKey[k][season];
            if (made && prev !== null && season === prev + 1 && len > 0) {
                len++;
            } else if (made) {
                len = 1; startSeason = season;
            } else {
                len = 0;
            }
            if (len > 0 && (!top || len > top.len)) top = { league, owner, len, startSeason, endSeason: season };
            prev = season;
        });
        if (top) best.push(top);
    });
    return best.sort((a, b) => b.len - a.len);
}

// "Josh Allen (QB) 30.00; Bijan Robinson (RB) 20.00" -> [{ name, pos, pts }]
function parseLineupList(text) {
    return String(text || '').split('; ').map(s => {
        const m = s.match(/^(.*) \(([^()]+)\) (-?[\d.]+)$/);
        return m ? { name: m[1].trim(), pos: m[2], pts: parseFloat(m[3]) || 0 } : null;
    }).filter(Boolean);
}

// "Bench Guy (WR), Other Guy (RB)" -> [{ name, pos }]
function parseNameList(text) {
    return String(text || '').split(/,\s*(?![^()]*\))/).map(s => {
        const m = s.trim().match(/^(.*?)\s*\(([^()]+)\)$/);
        return m ? { name: m[1].trim(), pos: m[2] } : (s.trim() ? { name: s.trim(), pos: '' } : null);
    }).filter(Boolean);
}

// Elo over every game since 2015, one rating per manager across all leagues.
// K = 24, a quarter of the gap to 1500 is given back at the start of each season.
function computeElo(games, leagueFilter) {
    const K = 24, BASE = 1500, REGRESS = 0.25;
    const ratings = {}, peak = {}, record = {}, history = {};
    let curSeason = null;
    [...games].filter(g => !leagueFilter || leagueFilter === 'ALL' || g.league === leagueFilter)
        .sort((a, b) => (a.season - b.season) || (a.weekNum - b.weekNum))
        .forEach(g => {
            if (g.season !== curSeason) {
                if (curSeason !== null) Object.keys(ratings).forEach(o => { (history[o] = history[o] || []).push({ season: curSeason, rating: ratings[o] }); });
                Object.keys(ratings).forEach(o => { ratings[o] += (BASE - ratings[o]) * REGRESS; });
                curSeason = g.season;
            }
            const ra = ratings[g.t1] ?? BASE, rb = ratings[g.t2] ?? BASE;
            const exp = 1 / (1 + Math.pow(10, (rb - ra) / 400));
            const res = g.s1 > g.s2 ? 1 : g.s1 < g.s2 ? 0 : 0.5;
            ratings[g.t1] = ra + K * (res - exp);
            ratings[g.t2] = rb - K * (res - exp);
            [[g.t1, res], [g.t2, 1 - res]].forEach(([o, r]) => {
                const rec = record[o] = record[o] || { w: 0, l: 0, t: 0, games: 0 };
                rec.games++;
                if (r === 1) rec.w++; else if (r === 0) rec.l++; else rec.t++;
                if (!peak[o] || ratings[o] > peak[o].rating) peak[o] = { rating: ratings[o], season: g.season, week: g.week, league: g.league };
            });
        });
    if (curSeason !== null) Object.keys(ratings).forEach(o => { (history[o] = history[o] || []).push({ season: curSeason, rating: ratings[o] }); });
    const table = Object.keys(ratings).map(o => ({ owner: o, rating: ratings[o], peak: peak[o], ...record[o], history: history[o] || [] }))
        .sort((a, b) => b.rating - a.rating);
    return { table, ratings };
}

// Sleeper chat shows plain text, so drop the Markdown the Gazette is written in
function gazettePlainText(md) {
    return String(md || '').replace(/\r/g, '')
        .replace(/^#{1,6}\s*/gm, '')
        .replace(/\*\*(.+?)\*\*/g, '$1')
        .replace(/\*(\S[^*]*?)\*/g, '$1')
        .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '$1 ($2)')
        .replace(/^\s*[-*]\s+/gm, '• ')
        .replace(/\n{3,}/g, '\n\n')
        .trim();
}

function hindsightBadge(t) {
    const sorted = [...t.sides].sort((a, b) => b.value - a.value);
    if (sorted.length < 2 || !sorted[0].value) return '<span class="text-slate-500">• no value data</span>';
    const share = sorted[0].value / (sorted.reduce((a, b) => a + b.value, 0) || 1);
    const verdict = share >= 0.65 ? 'Fleeced' : share >= 0.55 ? 'Won' : 'Even';
    return `<span class="ml-1 bg-emerald-500/10 text-emerald-300 border border-emerald-500/20 px-1.5 py-0.5 rounded font-bold">🔎 ${verdict === 'Even' ? 'Even trade' : `${escHtml(sorted[0].owner)} ${verdict}`}</span>
        <span class="text-slate-500">${t.sides.map(s => `${escHtml(s.owner)} ${Math.round(s.value).toLocaleString()}`).join(' vs ')}</span>`;
}

function beltWhen(p) {
    return p.weekNum ? `${p.season} Wk ${p.weekNum}` : String(p.season);
}

function chatEscape(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// "2027 Round 3rd Pick (originally from Team (user)) -> Resulted in drafting: X (WR)" -> "2027 Rd 3 pick -> drafted X (WR)"
function shortTradeItem(label) {
    return String(label || '')
        .replace(/\s*\(originally from (?:[^()]|\([^()]*\))*\)/, '')
        .replace(/ Round (\d+)\w* Pick/i, ' Rd $1 pick')
        .replace(/\s*-> Resulted in drafting:\s*/, ' -> drafted ');
}

// "2027 Mid Round 1" -> { yr: 2027, rd: 1 }
function parsePickSlot(s) {
    const m = String(s || '').match(/\b(20\d\d)\s+(?:(?:Early|Mid|Late)\s+)?Round\s+(\d+)/i);
    return m ? { yr: +m[1], rd: +m[2] } : null;
}

function tradeValueKey(leagueName, r) {
    return `${leagueName}||${r[0]}||${r[1]}||${r[4]}`;
}

// The player a traded item stands for: the player himself, or who a pick was used on (null for an unused pick)
function tradeItemPlayerName(item) {
    const s = String(item || '').trim();
    const drafted = s.match(/Resulted in drafting:\s*(.+?)\s*(?:\([A-Z/]+\))?\s*$/);
    if (drafted) return drafted[1];
    if (/^\d{4}\s+Round/i.test(s)) return null;
    const m = s.match(/^(.*?)\s*\(([A-Z/]+)(?:\s*-\s*[A-Z]+)?\)$/);
    return m ? m[1] : s;
}

// Letter grade from a side's share of the trade, scaled so an even split is 50% however many teams
function tradeLetter(share, sides) {
    const s = share * sides / 2;
    return s >= 0.70 ? 'A+' : s >= 0.62 ? 'A' : s >= 0.55 ? 'B' : s >= 0.45 ? 'C' : s >= 0.38 ? 'D' : 'F';
}

// Draft years of a picks-only trade (every item on every side is a pick), else null
function pickOnlyYears(breakdown) {
    const items = String(breakdown || '').split(' <---> ').flatMap(side => {
        const m = side.match(/^(.*?) received: \[(.*)\]$/);
        return m && m[2] !== 'Nothing' ? m[2].split(/,\s*(?![^()]*\))/) : [];
    });
    const years = items.map(i => (String(i).trim().match(/^(\d{4})\s+Round/i) || [])[1]);
    return items.length && years.every(Boolean) ? years.map(Number) : null;
}

function draftPickLetter(diff) {
    return diff >= 1.5 ? 'A+' : diff >= 0.6 ? 'A' : diff >= 0.2 ? 'B' : diff >= -0.35 ? 'C' : diff >= -1 ? 'D' : 'F';
}

// One draft swings a lot; a career of drafts evens out, so its scale is tighter
function draftRatioLetter(r, career = false) {
    const [aPlus, a, b, c, d] = career ? [1.3, 1.18, 1.07, 0.93, 0.82] : [1.6, 1.3, 1.1, 0.9, 0.7];
    return r >= aPlus ? 'A+' : r >= a ? 'A' : r >= b ? 'B' : r >= c ? 'C' : r >= d ? 'D' : 'F';
}

function draftGradeBadge(gr, title = '') {
    const color = gr.startsWith('A') ? 'text-emerald-300 border-emerald-500/30 bg-emerald-500/10' : gr === 'B' ? 'text-sky-300 border-sky-500/30 bg-sky-500/10'
        : gr === 'C' ? 'text-slate-300 border-slate-600 bg-slate-800' : gr === 'D' ? 'text-amber-300 border-amber-500/30 bg-amber-500/10' : 'text-rose-300 border-rose-500/30 bg-rose-500/10';
    return `<span class="inline-block min-w-[2rem] text-center border rounded font-bold px-1 ${color}"${title ? ` title="${escHtml(title)}"` : ''}>${gr}</span>`;
}

function draftPickLabel(p) {
    return `${p.round}.${String(p.inRound).padStart(2, '0')}`;
}

function draftOwnerChips(d) {
    const owners = Object.values(d.owners || {}).sort((a, b) => b.ratio - a.ratio);
    if (!owners.length) return '';
    return `<div class="flex flex-wrap gap-2">${owners.map(o => `<div class="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs flex items-center gap-2">
        ${draftGradeBadge(o.grade)}<span class="font-semibold text-slate-200">${escHtml(o.owner)}</span>
        <span class="font-mono text-slate-400" title="What their picks produced vs what those slots should have">${o.ratio.toFixed(2)}×</span></div>`).join('')}</div>`;
}

function draftTitle(d) {
    return `${d.season} ${escHtml(d.kind)} Draft`;
}

function escHtml(v) {
    return String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function weekNumber(w) {
    const m = String(w || '').match(/(\d+)/);
    return m ? parseInt(m[1], 10) : 0;
}

// Standard normal CDF (Abramowitz-Stegun 7.1.26)
function normalCdf(z) {
    const t = 1 / (1 + 0.3275911 * Math.abs(z) / Math.SQRT2);
    const erf = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-z * z / 2);
    return z >= 0 ? (1 + erf) / 2 : (1 - erf) / 2;
}

function meanSd(xs) {
    if (!xs.length) return { mean: 0, sd: 0 };
    const mean = xs.reduce((a, b) => a + b, 0) / xs.length;
    const v = xs.length > 1 ? xs.reduce((a, b) => a + (b - mean) ** 2, 0) / (xs.length - 1) : 0;
    return { mean, sd: Math.sqrt(v) };
}

// Score model from this season's finals, shrunk toward the league average so 2-3 games don't dominate
function scoreModel(teamRow, leagueScores) {
    const lg = meanSd(leagueScores);
    const lgMean = lg.mean || 110, lgSd = lg.sd || 25;
    const scores = teamRow ? teamRow.scores : [];
    const own = meanSd(scores);
    const n = scores.length, k = 3;
    const mean = (own.mean * n + lgMean * k) / (n + k);
    const sd = Math.sqrt(((n > 1 ? own.sd ** 2 : lgSd ** 2) * n + lgSd ** 2 * k) / (n + k));
    return { mean, sd, se: sd / Math.sqrt(n + k) }; // se = uncertainty in the team's true average
}

function fmtRecord(r) {
    return `${r.w}-${r.l}${r.t ? '-' + r.t : ''}`;
}

function isSleeperLeagueId(id) { return /^\d{12,}$/.test(id); }

function isFleaLeagueId(id) { return /^\d{4,9}$/.test(id); }

function fleaNum(x) {
    if (x && typeof x === 'object') x = x.value ?? x.formatted;
    const n = parseFloat(String(x ?? '').replace(/,/g, ''));
    return isNaN(n) ? 0 : n;
}

// Plays out a playoff field (team indexes in seed order). Each round the top seeds take any byes
// and the rest pair best vs worst, reseeded every round. play(a, b) -> [winner, loser].
// Returns { champ, ru, third } (undefined when the field is too small).
function simulateBracket(field, play, thirdGame) {
    let alive = field.slice();
    let semis = [], ru;
    const seedIdx = t => field.indexOf(t);
    while (alive.length > 1) {
        let size = 1;
        while (size < alive.length) size *= 2;
        const byes = size - alive.length;
        const next = alive.slice(0, byes), rest = alive.slice(byes), losers = [];
        for (let i = 0; i < rest.length / 2; i++) {
            const [w, l] = play(rest[i], rest[rest.length - 1 - i]);
            next.push(w); losers.push(l);
        }
        next.sort((a, b) => seedIdx(a) - seedIdx(b));
        if (next.length === 1) ru = losers[0];
        else if (next.length === 2) semis = losers.slice().sort((a, b) => seedIdx(a) - seedIdx(b));
        alive = next;
    }
    let third;
    if (semis.length === 2) third = thirdGame ? play(semis[0], semis[1])[0] : semis[0];
    else if (semis.length === 1) third = semis[0];
    return { champ: alive[0], ru, third };
}

// order: teams in regular-season standings order (best first); fin: { champ, ru, third }.
// Returns teams in draft order (first pick first). Podium teams that aren't known yet are skipped.
function rookieDraftOrder(order, fin, rule) {
    const podium = (rule === 'standings' ? [] : rule === 'finals' ? [fin.ru, fin.champ] : [fin.third, fin.ru, fin.champ])
        .filter(t => t !== undefined && t !== null);
    const rest = order.filter(t => !podium.includes(t)).reverse();
    return rest.concat(podium);
}

function pct(p) {
    if (p === null || p === undefined) return '—';
    if (p >= 0.9995) return '100%';
    if (p > 0 && p < 0.005) return '<1%';
    if (p < 1 && p > 0.995) return '>99%';
    return `${Math.round(p * 100)}%`;
}

function ordinalSuffix(n) {
    const s = ['th', 'st', 'nd', 'rd'], v = n % 100;
    return n + (s[(v - 20) % 10] || s[v] || s[0]);
}
