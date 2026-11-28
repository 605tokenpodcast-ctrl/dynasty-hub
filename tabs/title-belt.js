// tabs/title-belt.js: Title Belt (Dashboard tab): one lineal belt per league. Also used by badges and career compare.
// Classic script, loaded after utils.js and before app.js (see index.html). Top-level code here only
// declares functions/state; calls into app.js functions happen at runtime, after every script has loaded.

// --- TROPHY ROOM: THE TITLE BELT (one lineal belt per league) ---
// Rules (also shown on the page):
//  1. The belt starts with the top scorer of Week 1 in the league's first season.
//  2. The holder defends it in every scheduled head-to-head game: regular season, playoffs and consolation.
//  3. A loss passes the belt to the winner. A win or a tie keeps it. A bye week leaves it alone.
//  4. It carries over from season to season. If the holder leaves the league, the belt goes to the
//     defending champion (or, if they're gone too, the top scorer of Week 1 in the new season).
//  5. Games still being played this week don't count until they're final.
let beltCache = null;
function computeTitleBelts() {
    const hub = buildHubData();
    if (beltCache && beltCache.hub === hub) return beltCache.belts;
    const byLeague = {};
    hub.games.forEach(g => { (byLeague[g.league] = byLeague[g.league] || []).push(g); });
    const belts = {};
    Object.keys(byLeague).forEach(league => {
        const games = byLeague[league].sort((a, b) => (a.season - b.season) || (a.weekNum - b.weekNum));
        const seasons = [...new Set(games.map(g => g.season))];
        const reigns = [];
        let cur = null;
        const crown = (owner, season, weekNum, how) => {
            if (cur) cur.end = cur.end || { season, weekNum, how: 'vacated' };
            cur = { owner, league, start: { season, weekNum, how }, defenses: 0, games: 0, end: null };
            reigns.push(cur);
        };
        const week1Leader = season => {
            const sGames = games.filter(g => g.season === season);
            const firstWeek = Math.min(...sGames.map(g => g.weekNum));
            let best = null;
            sGames.filter(g => g.weekNum === firstWeek).forEach(g => {
                [[g.t1, g.s1], [g.t2, g.s2]].forEach(([o, s]) => { if (!best || s > best.s) best = { o, s, weekNum: firstWeek }; });
            });
            return best;
        };
        seasons.forEach(season => {
            const sGames = games.filter(g => g.season === season);
            const playing = new Set(sGames.flatMap(g => [g.t1, g.t2]));
            if (!cur) {
                const w1 = week1Leader(season);
                crown(w1.o, season, w1.weekNum, `first holder: top Week ${w1.weekNum} score (${w1.s.toFixed(2)})`);
            } else if (!playing.has(cur.owner)) {
                const prev = hub.seasons[`${league}||${season - 1}`] || hub.seasons[`${league}||${seasons[seasons.indexOf(season) - 1]}`];
                if (prev && prev.champ && playing.has(prev.champ)) {
                    crown(prev.champ, season, 1, `awarded to the defending champion after ${cur.owner} left the league`);
                } else {
                    const w1 = week1Leader(season);
                    crown(w1.o, season, w1.weekNum, `awarded to the top Week ${w1.weekNum} scorer after ${cur.owner} left the league`);
                }
            }
            sGames.forEach(g => {
                const holderIs1 = g.t1 === cur.owner, holderIs2 = g.t2 === cur.owner;
                if (!holderIs1 && !holderIs2) return;
                const [my, opp, oppName] = holderIs1 ? [g.s1, g.s2, g.t2] : [g.s2, g.s1, g.t1];
                cur.games++;
                if (my >= opp) { cur.defenses++; return; }
                cur.end = { season, weekNum: g.weekNum, how: `lost to ${oppName} ${opp.toFixed(2)}-${my.toFixed(2)}` };
                crown(oppName, season, g.weekNum, `beat ${cur.owner} ${opp.toFixed(2)}-${my.toFixed(2)}`);
            });
        });
        if (!cur) return;
        // Per-manager totals for this league
        const owners = {};
        reigns.forEach(r => {
            const o = owners[r.owner] = owners[r.owner] || { owner: r.owner, reigns: 0, defenses: 0, best: 0 };
            o.reigns++; o.defenses += r.defenses; o.best = Math.max(o.best, r.defenses);
        });
        const last = games[games.length - 1];
        belts[league] = {
            league, reigns, holder: cur, owners: Object.values(owners).sort((a, b) => b.defenses - a.defenses || b.reigns - a.reigns),
            longest: reigns.reduce((a, b) => (b.defenses > a.defenses ? b : a), reigns[0]),
            nextGame: beltNextGame(league, cur.owner, last)
        };
    });
    beltCache = { hub, belts };
    return belts;
}

// The holder's next scheduled game: the first unplayed week of the current season (from the synced schedule)
function beltNextGame(league, owner, lastGame) {
    if (!lastGame) return null;
    let next = null;
    sectionRows(league, 'matchups').forEach(r => {
        if ((parseInt(r[0], 10) || 0) !== lastGame.season || String(r[2]).trim() === '0') return;
        const wk = weekNumber(r[1]);
        if (wk <= lastGame.weekNum || (next && wk >= next.weekNum)) return;
        const t1 = getMasterOwner(r[3]), t2 = getMasterOwner(r[5]);
        if (t1 === owner && t2) next = { weekNum: wk, opp: t2 };
        else if (t2 === owner && t1) next = { weekNum: wk, opp: t1 };
    });
    // The championship bracket isn't set yet, so don't guess a playoff opponent
    return next && next.weekNum < playoffStartWeek(league, lastGame.season) ? next : null;
}

// beltWhen: moved to utils.js

function renderTitleBelt() {
    const box = document.getElementById('title-belt-grid');
    if (!box) return;
    const belts = Object.values(computeTitleBelts()).sort((a, b) => a.league.localeCompare(b.league));
    if (!belts.length) { box.innerHTML = '<p class="text-xs text-slate-500">No finished games yet.</p>'; return; }
    box.innerHTML = belts.map(b => {
        const h = b.holder;
        const lineage = [...b.reigns].reverse().map(r => `
            <li class="flex justify-between gap-3 py-1.5 border-b border-slate-800 last:border-0">
                <div class="min-w-0">
                    <p class="font-semibold text-slate-200">${escHtml(r.owner)}</p>
                    <p class="text-slate-500">${escHtml(beltWhen(r.start))}: ${escHtml(r.start.how)}</p>
                </div>
                <span class="whitespace-nowrap text-amber-300 font-bold">${r.defenses} def.</span>
            </li>`).join('');
        const leaders = b.owners.slice(0, 5).map((o, i) => `
            <li class="flex justify-between gap-3"><span class="truncate">${i + 1}. ${escHtml(o.owner)}</span>
            <span class="whitespace-nowrap text-slate-400">${o.defenses} def. &bull; ${o.reigns} reign${o.reigns === 1 ? '' : 's'}</span></li>`).join('');
        return `
        <div class="bg-cardbg border border-amber-500/30 rounded-xl p-4 space-y-3">
            <div class="flex justify-between items-start gap-2">
                <div class="min-w-0">
                    <p class="text-xs text-slate-400 truncate">${escHtml(b.league)}</p>
                    <h4 class="text-lg font-bold text-amber-300 break-words">🥊 ${escHtml(h.owner)}</h4>
                </div>
                <span class="bg-amber-500/10 text-amber-300 border border-amber-500/20 px-2.5 py-0.5 rounded-full text-xs font-bold whitespace-nowrap">${h.defenses} defense${h.defenses === 1 ? '' : 's'}</span>
            </div>
            <p class="text-xs text-slate-400">Holder since ${escHtml(beltWhen(h.start))} (${escHtml(h.start.how)}).</p>
            ${b.nextGame ? `<p class="text-xs text-slate-300">Next defense: <span class="font-semibold">Week ${b.nextGame.weekNum} vs ${escHtml(b.nextGame.opp)}</span></p>` : ''}
            <p class="text-xs text-slate-400">Longest reign: <span class="text-slate-200 font-semibold">${escHtml(b.longest.owner)}</span>, ${b.longest.defenses} straight defenses from ${escHtml(beltWhen(b.longest.start))}. The belt has changed hands ${b.reigns.length - 1} times.</p>
            <details class="text-xs">
                <summary class="cursor-pointer text-accent font-semibold">Belt leaders</summary>
                <ol class="mt-2 space-y-1 text-slate-300">${leaders}</ol>
            </details>
            <details class="text-xs">
                <summary class="cursor-pointer text-accent font-semibold">Full lineage (${b.reigns.length} reigns)</summary>
                <ul class="mt-2 max-h-72 overflow-y-auto pr-1">${lineage}</ul>
            </details>
        </div>`;
    }).join('');
}
