// tabs/records.js: Hall of Records tab: record collection, record cards and modal, record watch (owns recordsDetailStore).
// Classic script, loaded after utils.js and before app.js (see index.html). Top-level code here only
// declares functions/state; calls into app.js functions happen at runtime, after every script has loaded.

function collectRecordsData(leagueFilter) {
    const games = [];
    const standings = [];

    Object.keys(globalMasterData).forEach(leagueName => {
        if (!Array.isArray(globalMasterData[leagueName])) return;
        if (isAwardExcluded(leagueName)) return;
        if (leagueFilter !== 'ALL' && leagueName !== leagueFilter) return;
        const rows = globalMasterData[leagueName] || [];

        // Pass 1: find which weeks were actually played (same rule as H2H)
        const weekStats = {};
        let section = '';
        rows.forEach(r => {
            const col0 = String(r[0] || '').trim();
            const newSec = getSectionType(col0);
            if (newSec) { section = newSec; return; }
            if (section !== 'matchups' || isColumnHeaderRow(col0) || r.length < 7) return;
            const key = `${r[0]}|${r[1]}`;
            if (!weekStats[key]) weekStats[key] = { total: 0, nonZero: 0 };
            weekStats[key].total += 2;
            if ((parseFloat(r[4]) || 0) > 0) weekStats[key].nonZero++;
            if ((parseFloat(r[6]) || 0) > 0) weekStats[key].nonZero++;
        });

        // Pass 2: collect games and standings
        section = '';
        rows.forEach(r => {
            const col0 = String(r[0] || '').trim();
            const newSec = getSectionType(col0);
            if (newSec) { section = newSec; return; }
            if (isColumnHeaderRow(col0)) return;

            if (section === 'standings' && r[1]) {
                const rec = String(r[2] || '').split('-').map(n => parseInt(n, 10) || 0);
                standings.push({
                    league: leagueName,
                    season: parseInt(col0, 10) || 0,
                    owner: getMasterOwner(String(r[1])),
                    w: rec[0] || 0, l: rec[1] || 0, t: rec[2] || 0,
                    pf: parseFloat(String(r[3] || '').replace(/,/g, '')) || 0,
                    placement: String(r[4] || '')
                });
            }

            if (section === 'matchups' && r.length >= 7) {
                const matchupId = String(r[2]).trim();
                if (matchupId === '0' || !matchupId) return;
                const ws = weekStats[`${r[0]}|${r[1]}`];
                if (!ws || ws.total === 0 || (ws.nonZero / ws.total) < 0.75) return;
                const s1 = parseFloat(r[4]);
                const s2 = parseFloat(r[6]);
                if (isNaN(s1) || isNaN(s2) || (s1 === 0 && s2 === 0)) return;
                const t1 = getMasterOwner(r[3]);
                const t2 = getMasterOwner(r[5]);
                if (!t1 || !t2 || t1 === t2) return;
                const week = String(r[1]).trim();
                const weekNum = parseInt(week.replace(/\D/g, ''), 10) || 0;
                if (isOpenWeek(col0, weekNum)) return; // still being played
                games.push({
                    league: leagueName,
                    season: parseInt(col0, 10) || 0,
                    week,
                    weekNum,
                    t1, s1, t2, s2
                });
            }
        });
    });

    // Work out who made the playoffs each season: the top playoffTeamCount() teams by record,
    // ties broken by points for. Anyone with a champion/runner-up/3rd finish also counts.
    const groups = {};
    standings.forEach(s => { (groups[s.league + '||' + s.season] = groups[s.league + '||' + s.season] || []).push(s); });
    const madeMap = {};
    Object.keys(groups).forEach(k => {
        const [league, season] = k.split('||');
        const cutoff = playoffTeamCount(league, season);
        const complete = groups[k].some(s => /league champion/i.test(s.placement));
        [...groups[k]].sort((a, b) => (b.w - a.w) || (a.l - b.l) || (b.pf - a.pf)).forEach((s, i) => {
            s.madePlayoffs = i < cutoff || madePlayoffs(s.placement);
            s.complete = complete;
            madeMap[`${s.league}||${s.season}||${s.owner}`] = s.madePlayoffs;
        });
    });

    // Playoff games = games in or after the league's first playoff week where both teams made the playoffs (skips consolation brackets)
    games.forEach(g => {
        g.playoff = g.weekNum >= playoffStartWeek(g.league, g.season) &&
            !!madeMap[`${g.league}||${g.season}||${g.t1}`] &&
            !!madeMap[`${g.league}||${g.season}||${g.t2}`];
    });

    // Filter out 3rd/5th place games from the playoff pool. Only the final playoff week has them:
    //  - the championship game (involves the champion or runner-up) always counts
    //  - the 3rd place game (involves the 3rd place finisher) counts, unless leagues.json says the league has none
    //  - any other final-week game between playoff teams (5th place) never counts
    const finishInfo = {};
    standings.forEach(s => {
        const k = `${s.league}||${s.season}`;
        if (!finishInfo[k]) finishInfo[k] = {};
        if (/league champion/i.test(s.placement)) finishInfo[k].champ = s.owner;
        else if (/runner-up/i.test(s.placement)) finishInfo[k].runner = s.owner;
        else if (/3rd place/i.test(s.placement)) finishInfo[k].third = s.owner;
    });
    const finalWeek = {};
    games.forEach(g => {
        if (!g.playoff) return;
        const k = `${g.league}||${g.season}`;
        finalWeek[k] = Math.max(finalWeek[k] || 0, g.weekNum);
    });
    games.forEach(g => {
        g.playoffCounts = g.playoff;
        if (!g.playoff) return;
        const k = `${g.league}||${g.season}`;
        const inf = finishInfo[k] || {};
        if (!inf.champ || g.weekNum !== finalWeek[k]) return; // earlier round, or season not finished
        const teams = [g.t1, g.t2];
        if (teams.includes(inf.champ) || teams.includes(inf.runner)) return; // championship game
        const hasThirdPlaceGame = leagueRules(g.league).third_place_game !== false;
        g.playoffCounts = hasThirdPlaceGame && teams.includes(inf.third);
    });

    return { games, standings };
}

// findStreaks: moved to utils.js

// findPlayoffStreaks: moved to utils.js

let recordsDetailStore = [];

function openRecordModal(idx) {
    const d = recordsDetailStore[idx];
    if (!d) return;
    document.getElementById('records-modal-title').innerText = `${d.icon} ${d.title}`;
    document.getElementById('records-modal-blurb').innerText = d.blurb;
    document.getElementById('records-modal-body').innerHTML = d.entries.map((e, i) => `
        <div class="flex justify-between items-start gap-4 pt-3 first:pt-0">
            <div class="flex gap-3">
                <span class="text-slate-500 font-bold text-xs w-6 text-right pt-0.5">#${i + 1}</span>
                <div>
                    <p class="font-bold ${i === 0 ? 'text-accent' : 'text-slate-200'} text-sm">${escHtml(e.name)}</p>
                    <p class="text-xs text-slate-400">${escHtml(e.detail)}</p>
                </div>
            </div>
            <span class="font-mono font-bold ${i === 0 ? 'text-emerald-400' : 'text-slate-300'} text-sm whitespace-nowrap">${escHtml(e.value)}</span>
        </div>
    `).join('') || '<p class="text-xs text-slate-500">Not enough data yet.</p>';
    document.getElementById('records-modal').classList.remove('hidden');
}

function closeRecordModal() {
    document.getElementById('records-modal').classList.add('hidden');
}

function recordCard(icon, title, blurb, entries) {
    const idx = recordsDetailStore.push({ icon, title, blurb, entries }) - 1;
    const top = entries[0];
    const rest = entries.slice(1, 3);
    const body = top ? `
        <div class="space-y-1">
            <p class="text-2xl font-extrabold text-emerald-400">${escHtml(top.value)}</p>
            <p class="font-bold text-accent text-sm">${escHtml(top.name)}</p>
            <p class="text-xs text-slate-400">${escHtml(top.detail)}</p>
        </div>
        ${rest.length ? `<div class="pt-3 border-t border-slate-800 space-y-2">${rest.map((e, i) => `
            <div class="flex justify-between items-start gap-3 text-xs">
                <div>
                    <span class="text-slate-500 font-bold mr-1">#${i + 2}</span>
                    <span class="font-semibold text-slate-200">${escHtml(e.name)}</span>
                    <p class="text-slate-500 ml-5">${escHtml(e.detail)}</p>
                </div>
                <span class="font-mono font-bold text-slate-300 whitespace-nowrap">${escHtml(e.value)}</span>
            </div>`).join('')}</div>` : ''}
    ` : `<p class="text-xs text-slate-500">Not enough data yet.</p>`;

    return `
        <div onclick="openRecordModal(${idx})" class="bg-cardbg border border-slate-700 hover:border-accent rounded-xl p-5 shadow-sm space-y-3 cursor-pointer transition">
            <div>
                <h3 class="font-bold text-white">${icon} ${title}</h3>
                <p class="text-[11px] text-slate-500">${blurb}</p>
            </div>
            ${body}
            ${entries.length > 3 ? `<p class="text-[11px] text-accent font-semibold pt-1">View top ${entries.length} &rarr;</p>` : ''}
        </div>
    `;
}

// Record Watch: this season's numbers against the all-time records (same league filter as the Hall of Records).
// A record counts as broken when this season beats every earlier season; otherwise the closest
// chase is shown when it's within reach.
function renderRecordWatch(games, filter) {
    const box = document.getElementById('records-watch');
    if (!box) return;
    const cur = Math.max(0, ...games.map(g => g.season));
    // All Leagues: each league against its own history (one league's records mean little in another)
    const leagues = filter === 'ALL' ? [...new Set(games.filter(g => g.season === cur).map(g => g.league))].sort() : [filter];
    const items = leagues.flatMap(lg => recordWatchItems(games.filter(g => g.league === lg), cur)
        .map(it => ({ ...it, title: filter === 'ALL' ? `${lg}: ${it.title}` : it.title })));
    const chip = st => st === 'broken'
        ? '<span class="text-[10px] font-bold bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 px-1.5 py-0.5 rounded">BROKEN</span>'
        : '<span class="text-[10px] font-bold bg-amber-500/15 text-amber-300 border border-amber-500/30 px-1.5 py-0.5 rounded">WITHIN REACH</span>';
    items.sort((a, b) => (a.status === 'broken' ? 0 : 1) - (b.status === 'broken' ? 0 : 1));
    box.innerHTML = !cur ? '' : `
        <div class="bg-cardbg border border-amber-500/30 rounded-xl p-5 space-y-3">
            <div>
                <h3 class="font-bold text-white">👀 Record Watch: ${cur}</h3>
                <p class="text-[11px] text-slate-500">This season against every earlier season of the same league: records already broken, and the ones within reach.</p>
            </div>
            ${items.length ? items.map(it => `
                <div class="flex items-start gap-3 border-t border-slate-800 pt-3 first:border-0 first:pt-0">
                    <span class="text-xl leading-none">${it.icon}</span>
                    <div class="min-w-0 space-y-0.5">
                        <p class="text-sm font-bold text-white">${escHtml(it.title)} ${chip(it.status)}</p>
                        <p class="text-xs text-slate-300">${escHtml(it.text)}</p>
                    </div>
                </div>`).join('') : '<p class="text-sm text-slate-400">No records in danger this season yet.</p>'}
        </div>`;
}

// Record Watch lines for one league's games: [{ icon, title, status: 'broken' | 'close', text }]
function recordWatchItems(games, cur) {
    const now = games.filter(g => g.season === cur), before = games.filter(g => g.season < cur);
    if (!now.length || !before.length) return [];
    const where = g => `${g.season} ${g.week}`;
    const sidesOf = list => list.flatMap(g => [
        { owner: g.t1, score: g.s1, opp: g.t2, oppScore: g.s2, g }, { owner: g.t2, score: g.s2, opp: g.t1, oppScore: g.s1, g }]);
    const items = [];
    // higher: a bigger value is the record. fmt shows a value. near: how close counts as "within reach"
    const watch = (icon, title, nowBest, oldBest, fmt, near, higher = true) => {
        if (!nowBest || !oldBest) return;
        const beat = higher ? nowBest.v > oldBest.v : nowBest.v < oldBest.v;
        const gap = Math.abs(nowBest.v - oldBest.v);
        if (beat) items.push({ icon, title, status: 'broken', text: `${nowBest.who} set a new mark: ${fmt(nowBest.v)} (${nowBest.where}). Old record ${fmt(oldBest.v)} by ${oldBest.who}, ${oldBest.where}.` });
        else if (gap <= near) items.push({ icon, title, status: 'close', text: `${nowBest.who} is ${fmt(gap)} away: ${fmt(nowBest.v)} vs the record ${fmt(oldBest.v)} by ${oldBest.who} (${oldBest.where}).` });
    };
    const best = (list, val, higher = true) => list.reduce((b, x) => (b === null || (higher ? val(x) > val(b) : val(x) < val(b)) ? x : b), null);
    const pts = v => `${v.toFixed(2)} pts`;

    const sNow = sidesOf(now), sOld = sidesOf(before);
    const hiN = best(sNow, x => x.score), hiO = best(sOld, x => x.score);
    watch('💥', 'Highest score', hiN && { v: hiN.score, who: hiN.owner, where: where(hiN.g) }, hiO && { v: hiO.score, who: hiO.owner, where: where(hiO.g) }, pts, 15);
    const real = x => x.score >= 20; // skips abandoned teams
    const loN = best(sNow.filter(real), x => x.score, false), loO = best(sOld.filter(real), x => x.score, false);
    watch('🪫', 'Lowest score', loN && { v: loN.score, who: loN.owner, where: where(loN.g) }, loO && { v: loO.score, who: loO.owner, where: where(loO.g) }, pts, 10, false);
    const lossN = best(sNow.filter(x => x.score < x.oppScore), x => x.score), lossO = best(sOld.filter(x => x.score < x.oppScore), x => x.score);
    watch('🥷', 'Most points in a loss', lossN && { v: lossN.score, who: lossN.owner, where: where(lossN.g) }, lossO && { v: lossO.score, who: lossO.owner, where: where(lossO.g) }, pts, 12);
    const margin = x => x.score - x.oppScore;
    const blN = best(sNow, margin), blO = best(sOld, margin);
    watch('🚜', 'Biggest blowout', blN && { v: margin(blN), who: blN.owner, where: where(blN.g) }, blO && { v: margin(blO), who: blO.owner, where: where(blO.g) }, pts, 15);

    // Season scoring pace (regular season points per game; earlier seasons need 8+ games to count)
    const ppg = list => {
        const t = {};
        list.filter(g => g.weekNum < playoffStartWeek(g.league, g.season)).forEach(g => {
            [[g.t1, g.s1], [g.t2, g.s2]].forEach(([o, sc]) => {
                const k = `${g.league}||${g.season}||${o}`;
                const r = t[k] = t[k] || { owner: o, league: g.league, season: g.season, pts: 0, n: 0 };
                r.pts += sc; r.n++;
            });
        });
        return Object.values(t).map(r => ({ ...r, v: r.pts / r.n }));
    };
    const pN = best(ppg(now).filter(r => r.n >= 3), r => r.v), pO = best(ppg(before).filter(r => r.n >= 8), r => r.v);
    const seasonWhere = r => `${r.season}`;
    watch('📈', 'Best scoring season (points per game)', pN && { v: pN.v, who: pN.owner, where: `${seasonWhere(pN)}, ${pN.n} games so far` }, pO && { v: pO.v, who: pO.owner, where: seasonWhere(pO) }, v => `${v.toFixed(1)} ppg`, 6);

    // Active streaks against the longest ever (streaks run across seasons, within one league)
    ['W', 'L'].forEach(kind => {
        const record = findStreaks(games, kind)[0];
        if (!record) return;
        const byKey = {};
        games.forEach(g => [[g.t1, g.s1, g.s2], [g.t2, g.s2, g.s1]].forEach(([o, my, op]) => {
            (byKey[`${g.league}||${o}`] = byKey[`${g.league}||${o}`] || []).push({ g, res: my > op ? 'W' : my < op ? 'L' : 'T' });
        }));
        let top = null;
        Object.entries(byKey).forEach(([k, arr]) => {
            arr.sort((a, b) => (a.g.season - b.g.season) || (a.g.weekNum - b.g.weekNum));
            if (arr[arr.length - 1].g.season !== cur) return;
            let n = 0;
            for (let i = arr.length - 1; i >= 0 && arr[i].res === kind; i--) n++;
            if (n && (!top || n > top.n)) top = { n, owner: k.split('||')[1], league: k.split('||')[0] };
        });
        if (!top || top.n < 3) return;
        const label = kind === 'W' ? 'wins' : 'losses';
        const isRecordHolder = record.owner === top.owner && record.league === top.league && record.end.season === cur;
        const recWhere = `${record.start.season}`;
        if (isRecordHolder) items.push({ icon: kind === 'W' ? '🔥' : '🧊', title: kind === 'W' ? 'Longest winning streak' : 'Longest losing streak', status: 'broken', text: `${top.owner} has ${top.n} straight ${label}, the longest ever and still going.` });
        else if (record.len - top.n <= 3) items.push({ icon: kind === 'W' ? '🔥' : '🧊', title: kind === 'W' ? 'Longest winning streak' : 'Longest losing streak', status: 'close', text: `${top.owner} has ${top.n} straight ${label}. The record is ${record.len} by ${record.owner} (${recWhere}).` });
    });

    return items;
}

function renderRecords() {
    const filterEl = document.getElementById('records-league-filter');
    const grid = document.getElementById('records-grid');
    if (!filterEl || !grid) return;
    const { games, standings } = collectRecordsData(filterEl.value);
    renderRecordWatch(games, filterEl.value);
    const when = g => `${g.season} ${g.week}`;
    const range = (s, e) => (s.season === e.season && s.week === e.week) ? when(s) : `${when(s)} → ${when(e)}`;
    const cards = [];
    recordsDetailStore = [];

    // --- Streaks ---
    const winStreaks = findStreaks(games, 'W');
    cards.push(recordCard('🔥', 'Longest Winning Streak', 'Most consecutive wins in one league (carries across seasons)',
        winStreaks.slice(0, 10).map(s => ({ name: s.owner, value: `${s.len} wins`, detail: `${s.league} • ${range(s.start, s.end)}` }))));

    const loseStreaks = findStreaks(games, 'L');
    cards.push(recordCard('🧊', 'Longest Losing Streak', 'Most consecutive losses in one league',
        loseStreaks.slice(0, 10).map(s => ({ name: s.owner, value: `${s.len} losses`, detail: `${s.league} • ${range(s.start, s.end)}` }))));

    const playoffStreaks = findPlayoffStreaks(standings);
    cards.push(recordCard('🎟️', 'Playoff Streak', 'Most consecutive seasons making the playoffs in one league',
        playoffStreaks.slice(0, 10).map(s => ({ name: s.owner, value: `${s.len} seasons`, detail: `${s.league} • ${s.startSeason}–${s.endSeason}` }))));

    // --- Championships ---
    const titlesByLeague = {};
    const titlesBySeason = {};
    const runnerUps = {};
    standings.forEach(s => {
        if (s.placement.includes('League Champion')) {
            const k1 = s.owner + '||' + s.league;
            (titlesByLeague[k1] = titlesByLeague[k1] || { owner: s.owner, league: s.league, seasons: [] }).seasons.push(s.season);
            const k2 = s.owner + '||' + s.season;
            (titlesBySeason[k2] = titlesBySeason[k2] || { owner: s.owner, season: s.season, leagues: [] }).leagues.push(s.league);
        }
        if (s.placement.includes('Runner-Up')) runnerUps[s.owner] = (runnerUps[s.owner] || 0) + 1;
    });

    cards.push(recordCard('👑', 'Dynasty Award', 'Most championships in a single league',
        Object.values(titlesByLeague).sort((a, b) => b.seasons.length - a.seasons.length).slice(0, 10)
            .map(t => ({ name: t.owner, value: `${t.seasons.length} title${t.seasons.length > 1 ? 's' : ''}`, detail: `${t.league} • ${t.seasons.sort().join(', ')}` }))));

    cards.push(recordCard('🏆', 'Greatest Single Season', 'Most championships won in the same season across leagues',
        Object.values(titlesBySeason).sort((a, b) => b.leagues.length - a.leagues.length).slice(0, 10)
            .map(t => ({ name: t.owner, value: `${t.leagues.length} title${t.leagues.length > 1 ? 's' : ''}`, detail: `${t.season} • ${t.leagues.join(', ')}` }))));

    const titleTotals = {};
    standings.forEach(s => { if (s.placement.includes('League Champion')) titleTotals[s.owner] = (titleTotals[s.owner] || 0) + 1; });
    cards.push(recordCard('🥈', 'Always a Bridesmaid', 'Most runner-up finishes (fewer titles breaks ties)',
        Object.keys(runnerUps).sort((a, b) => (runnerUps[b] - runnerUps[a]) || ((titleTotals[a] || 0) - (titleTotals[b] || 0))).slice(0, 10)
            .map(o => ({ name: o, value: `${runnerUps[o]} runner-up${runnerUps[o] > 1 ? 's' : ''}`, detail: `${titleTotals[o] || 0} career title${(titleTotals[o] || 0) === 1 ? '' : 's'}` }))));

    // --- Single-game feats ---
    const sides = [];
    games.forEach(g => {
        sides.push({ owner: g.t1, score: g.s1, opp: g.t2, oppScore: g.s2, g });
        sides.push({ owner: g.t2, score: g.s2, opp: g.t1, oppScore: g.s1, g });
    });
    const sideDetail = x => `vs ${x.opp} (${x.oppScore.toFixed(2)}) • ${x.g.league} • ${when(x.g)}`;

    cards.push(recordCard('💥', 'Highest Single-Game Score', 'The biggest score ever put up in a week',
        [...sides].sort((a, b) => b.score - a.score).slice(0, 10)
            .map(x => ({ name: x.owner, value: `${x.score.toFixed(2)} pts`, detail: sideDetail(x) }))));

    cards.push(recordCard('🪦', 'Lowest Playoff Score', 'Fewest points in a playoff game (playoff teams only)',
        sides.filter(x => x.g.playoffCounts && x.score >= 20).sort((a, b) => a.score - b.score).slice(0, 10)
            .map(x => ({ name: x.owner, value: `${x.score.toFixed(2)} pts`, detail: sideDetail(x) }))));

    const margins = games.filter(g => g.s1 !== g.s2).map(g => {
        const w1 = g.s1 > g.s2;
        return { winner: w1 ? g.t1 : g.t2, loser: w1 ? g.t2 : g.t1, ws: w1 ? g.s1 : g.s2, ls: w1 ? g.s2 : g.s1, margin: Math.abs(g.s1 - g.s2), g };
    });
    const marginDetail = m => `${m.ws.toFixed(2)}–${m.ls.toFixed(2)} over ${m.loser} • ${m.g.league} • ${when(m.g)}`;

    cards.push(recordCard('🚜', 'Biggest Blowout', 'Largest margin of victory',
        [...margins].sort((a, b) => b.margin - a.margin).slice(0, 10)
            .map(m => ({ name: m.winner, value: `+${m.margin.toFixed(2)}`, detail: marginDetail(m) }))));

    cards.push(recordCard('😰', 'Nail-Biter', 'Closest finish on record',
        [...margins].sort((a, b) => a.margin - b.margin).slice(0, 10)
            .map(m => ({ name: m.winner, value: `+${m.margin.toFixed(2)}`, detail: marginDetail(m) }))));

    cards.push(recordCard('💔', 'Heartbreak Award', 'Most points scored in a loss',
        sides.filter(x => x.score < x.oppScore).sort((a, b) => b.score - a.score).slice(0, 10)
            .map(x => ({ name: x.owner, value: `${x.score.toFixed(2)} pts (L)`, detail: sideDetail(x) }))));

    // --- Season-long feats ---
    cards.push(recordCard('📈', 'Best Season Record', 'Highest win % in a season (minimum 10 games)',
        standings.filter(s => (s.w + s.l + s.t) >= 10)
            .map(s => ({ ...s, pct: (s.w + 0.5 * s.t) / (s.w + s.l + s.t) }))
            .sort((a, b) => b.pct - a.pct || b.w - a.w).slice(0, 10)
            .map(s => ({ name: s.owner, value: `${s.w}-${s.l}${s.t ? '-' + s.t : ''}`, detail: `${s.league} • ${s.season} • ${s.placement || 'No placement'}` }))));

    const seasonPts = {};
    const seasonGames = {};
    games.forEach(g => {
        if (g.weekNum >= playoffStartWeek(g.league, g.season)) return; // regular season only
        [[g.t1, g.s1], [g.t2, g.s2]].forEach(([o, s]) => {
            const k = `${o}||${g.league}||${g.season}`;
            seasonPts[k] = (seasonPts[k] || 0) + s;
            seasonGames[k] = (seasonGames[k] || 0) + 1;
        });
    });
    cards.push(recordCard('🚀', 'Highest-Scoring Season', 'Most regular-season points in one year (minimum 10 games)',
        Object.keys(seasonPts).filter(k => seasonGames[k] >= 10).sort((a, b) => seasonPts[b] - seasonPts[a]).slice(0, 10)
            .map(k => { const [o, lg, sn] = k.split('||'); return { name: o, value: `${seasonPts[k].toFixed(1)} pts`, detail: `${lg} • ${sn}` }; })));

    // --- Rivalries ---
    const pairs = {};
    games.forEach(g => {
        if (g.s1 === g.s2) return;
        const [a, b] = [g.t1, g.t2].sort();
        const k = a + '||' + b;
        if (!pairs[k]) pairs[k] = { a, b, aw: 0, bw: 0 };
        const winner = g.s1 > g.s2 ? g.t1 : g.t2;
        if (winner === a) pairs[k].aw++; else pairs[k].bw++;
    });
    cards.push(recordCard('😈', 'Biggest Nemesis', 'Most lopsided head-to-head record (minimum 5 games)',
        Object.values(pairs).filter(p => p.aw + p.bw >= 5)
            .sort((x, y) => Math.abs(y.aw - y.bw) - Math.abs(x.aw - x.bw)).slice(0, 10)
            .map(p => {
                const aLeads = p.aw >= p.bw;
                return { name: `${aLeads ? p.a : p.b} over ${aLeads ? p.b : p.a}`, value: `${Math.max(p.aw, p.bw)}-${Math.min(p.aw, p.bw)}`, detail: `${p.aw + p.bw} games played` };
            })));

    cards.push(recordCard('⚔️', 'Greatest Rivalry', 'Most-played head-to-head matchup',
        Object.values(pairs).sort((x, y) => (y.aw + y.bw) - (x.aw + x.bw)).slice(0, 10)
            .map(p => ({ name: `${p.a} vs ${p.b}`, value: `${p.aw + p.bw} games`, detail: `Series: ${p.a} ${p.aw}-${p.bw} ${p.b}` }))));

    grid.innerHTML = cards.join('');
}
