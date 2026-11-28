// tabs/luck-index.js: Luck Index tab (true all-play and schedule luck).
// Classic script, loaded after utils.js and before app.js (see index.html). Top-level code here only
// declares functions/state; calls into app.js functions happen at runtime, after every script has loaded.

// --- TAB 6: TRUE ALL-PLAY & SCHEDULE LUCK INDEX ---
function renderLuckIndex() {
    const leagueFilter = document.getElementById('luck-league-filter').value;
    const seasonFilter = document.getElementById('luck-season-filter').value;
    const tbody = document.getElementById('luck-table-body');

    const stats = {};

    Object.keys(globalMasterData).forEach(leagueName => {
        if (leagueFilter !== 'ALL' && leagueName !== leagueFilter) return;
        const rows = globalMasterData[leagueName] || [];
        let section = '';
        const slateMap = {};

        rows.forEach(r => {
            const col0 = String(r[0] || '').trim();
            const newSec = getSectionType(col0);
            if (newSec) { section = newSec; return; }
            if (section !== 'matchups' || isColumnHeaderRow(col0) || r.length < 7) return;

            const season = col0;
            if (seasonFilter !== 'ALL' && season !== seasonFilter) return;
            const week = String(r[1]).trim();
            const weekNum = parseInt(week.replace(/\D/g, ''), 10) || 1;
            if (weekNum >= playoffStartWeek(leagueName, season)) return; // Regular season only for true schedule luck
            if (isOpenWeek(season, weekNum)) return; // still being played
            const matchupId = String(r[2]).trim();
            if (matchupId === '0' || !matchupId) return;

            const key = `${season}|${week}`;
            if (!slateMap[key]) slateMap[key] = [];
            slateMap[key].push({
                t1: getMasterOwner(r[3]),
                s1: parseFloat(r[4]) || 0,
                t2: getMasterOwner(r[5]),
                s2: parseFloat(r[6]) || 0
            });
        });

        Object.keys(slateMap).forEach(key => {
            const games = slateMap[key];
            const allScores = [];
            games.forEach(g => {
                if (g.s1 > 0) allScores.push(g.s1);
                if (g.s2 > 0) allScores.push(g.s2);
            });
            if (allScores.length < games.length * 1.5) return; // skip unplayed weeks

            const teamWeekScores = [];
            games.forEach(g => {
                if (!stats[g.t1]) stats[g.t1] = { w: 0, l: 0, t: 0, apW: 0, apL: 0, pf: 0, pa: 0 };
                if (!stats[g.t2]) stats[g.t2] = { w: 0, l: 0, t: 0, apW: 0, apL: 0, pf: 0, pa: 0 };

                stats[g.t1].pf += g.s1; stats[g.t1].pa += g.s2;
                stats[g.t2].pf += g.s2; stats[g.t2].pa += g.s1;

                if (g.s1 > g.s2) { stats[g.t1].w++; stats[g.t2].l++; }
                else if (g.s2 > g.s1) { stats[g.t2].w++; stats[g.t1].l++; }
                else { stats[g.t1].t++; stats[g.t2].t++; }

                teamWeekScores.push({ mgr: g.t1, score: g.s1 });
                teamWeekScores.push({ mgr: g.t2, score: g.s2 });
            });

            // Calculate All-Play wins/losses for this week
            for (let i = 0; i < teamWeekScores.length; i++) {
                for (let j = 0; j < teamWeekScores.length; j++) {
                    if (i === j) continue;
                    if (teamWeekScores[i].score > teamWeekScores[j].score) stats[teamWeekScores[i].mgr].apW++;
                    else if (teamWeekScores[i].score < teamWeekScores[j].score) stats[teamWeekScores[i].mgr].apL++;
                }
            }
        });
    });

    const rowsData = Object.keys(stats).map(mgr => {
        const d = stats[mgr];
        const games = d.w + d.l + d.t;
        const apGames = d.apW + d.apL;
        const apWinPct = apGames > 0 ? (d.apW / apGames) : 0;
        const expectedWins = games * apWinPct;
        const luckDiff = d.w + d.t / 2 - expectedWins; // a tie is half a win
        return { mgr, ...d, games, apWinPct, expectedWins, luckDiff };
    }).sort((a, b) => b.apWinPct - a.apWinPct);

    tbody.innerHTML = rowsData.map(r => {
        const actualPct = r.games > 0 ? (((r.w + r.t / 2) / r.games) * 100).toFixed(1) : '0.0';
        const allPlayPct = (r.apWinPct * 100).toFixed(1);
        const diffStr = (r.luckDiff >= 0 ? '+' : '') + r.luckDiff.toFixed(1);
        const badge = r.luckDiff >= 1.5
            ? `<span class="bg-amber-500/10 text-amber-300 border border-amber-500/20 px-2.5 py-1 rounded text-xs font-bold">🍀 Lucky (+${r.luckDiff.toFixed(1)} W)</span>`
            : (r.luckDiff <= -1.5
                ? `<span class="bg-rose-500/10 text-rose-300 border border-rose-500/20 px-2.5 py-1 rounded text-xs font-bold">⛈️ Unlucky (${r.luckDiff.toFixed(1)} W)</span>`
                : `<span class="bg-emerald-500/10 text-emerald-300 border border-emerald-500/20 px-2.5 py-1 rounded text-xs font-bold">⚖️ True to Form</span>`);

        return `
            <tr class="hover:bg-slate-800/40 transition">
                <td class="p-4 font-bold text-accent">${escHtml(r.mgr)}</td>
                <td class="p-4 font-semibold">${fmtRecord(r)} <span class="text-xs text-slate-400">(${actualPct}%)</span></td>
                <td class="p-4 font-semibold text-emerald-400">${r.apW}-${r.apL} <span class="text-xs text-slate-400">(${allPlayPct}%)</span></td>
                <td class="p-4 text-xs text-slate-300">PF: <strong>${r.pf.toFixed(1)}</strong> &bull; PA: <strong>${r.pa.toFixed(1)}</strong></td>
                <td class="p-4 font-mono text-xs">${diffStr} Wins <span class="text-slate-400">(Exp: ${r.expectedWins.toFixed(1)})</span></td>
                <td class="p-4">${badge}</td>
            </tr>
        `;
    }).join('');
}
