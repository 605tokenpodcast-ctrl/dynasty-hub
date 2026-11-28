// tabs/weekly-awards.js: Weekly Awards tab (bench blunders and weekly awards).
// Classic script, loaded after utils.js and before app.js (see index.html). Top-level code here only
// declares functions/state; calls into app.js functions happen at runtime, after every script has loaded.

// --- TAB 5: THIS SEASON'S BENCH BLUNDERS & WEEKLY AWARDS ---
function renderWeeklyAwards() {
    const leagueFilter = document.getElementById('awards-league-filter').value;
    const benchList = [];
    const weeklyHighs = [];
    const managerBenchPoints = {};

    // This season's lineups (every league, Fleaflicker too), one bucket per league and week
    const season = parseInt(latestSeason(), 10) || 0;
    const buckets = {};
    const top = list => list.reduce((best, p) => (!best || p.pts > best.pts ? p : best), null);
    const label = p => p ? `${p.name} (${p.pos}) (${p.pts.toFixed(2)})` : 'None (0.00)';
    buildHubData().lineups.forEach(l => {
        if (l.season !== season || (leagueFilter !== 'ALL' && l.league !== leagueFilter)) return;
        const st = top(l.starters), bn = top(l.bench);
        (buckets[`${l.league}||${l.weekNum}`] = buckets[`${l.league}||${l.weekNum}`] || []).push({
            league: l.league, week: l.week, owner: l.owner, rawTeam: l.team, totalScore: l.score,
            topStarter: label(st), topBench: label(bn), benchPts: bn ? bn.pts : 0
        });
    });
    const teamsInLeague = {};
    Object.values(buckets).forEach(entries => {
        teamsInLeague[entries[0].league] = Math.max(teamsInLeague[entries[0].league] || 0, entries.length);
    });

    Object.values(buckets).forEach(entries => {
        if (entries.length < teamsInLeague[entries[0].league] * 0.75) return; // partly played week

        // Weekly High Roller
        const sortedByTotal = [...entries].sort((a, b) => b.totalScore - a.totalScore);
        if (sortedByTotal[0] && sortedByTotal[0].totalScore > 0) {
            weeklyHighs.push(sortedByTotal[0]);
        }

        // Bench explosions
        entries.forEach(e => {
            if (e.benchPts > 0) {
                benchList.push(e);
                managerBenchPoints[e.owner] = (managerBenchPoints[e.owner] || 0) + e.benchPts;
            }
        });
    });

    benchList.sort((a, b) => b.benchPts - a.benchPts);
    weeklyHighs.sort((a, b) => b.totalScore - a.totalScore);

    const topBenchManager = Object.keys(managerBenchPoints).sort((a, b) => managerBenchPoints[b] - managerBenchPoints[a])[0] || 'N/A';
    const highestSingleWeek = weeklyHighs[0];
    const biggestBenchBlunder = benchList[0];

    document.getElementById('awards-summary-cards').innerHTML = `
        <div class="bg-cardbg border border-slate-700 rounded-xl p-5 space-y-1">
            <p class="text-xs text-slate-400 font-bold uppercase">🏆 ${escHtml(latestSeason())} Single-Week High Score</p>
            <p class="text-2xl font-extrabold text-emerald-400">${highestSingleWeek ? highestSingleWeek.totalScore.toFixed(2) + ' pts' : 'N/A'}</p>
            <p class="text-xs text-slate-300">${highestSingleWeek ? escHtml(`${highestSingleWeek.owner} (${highestSingleWeek.league} • ${highestSingleWeek.week})`) : ''}</p>
        </div>
        <div class="bg-cardbg border border-slate-700 rounded-xl p-5 space-y-1">
            <p class="text-xs text-slate-400 font-bold uppercase">🪑 Biggest Single-Player Bench Explosion</p>
            <p class="text-2xl font-extrabold text-amber-400">${biggestBenchBlunder ? escHtml(biggestBenchBlunder.topBench) : 'N/A'}</p>
            <p class="text-xs text-slate-300">${biggestBenchBlunder ? escHtml(`Benched by ${biggestBenchBlunder.owner} (${biggestBenchBlunder.league} • ${biggestBenchBlunder.week})`) : ''}</p>
        </div>
        <div class="bg-cardbg border border-slate-700 rounded-xl p-5 space-y-1">
            <p class="text-xs text-slate-400 font-bold uppercase">👑 Cumulative Max Bench Points Leader</p>
            <p class="text-2xl font-extrabold text-rose-400">${escHtml(topBenchManager)}</p>
            <p class="text-xs text-slate-300">${managerBenchPoints[topBenchManager] ? managerBenchPoints[topBenchManager].toFixed(2) + ' total top-bench points left on pine' : ''}</p>
        </div>
    `;

    document.getElementById('bench-blunders-list').innerHTML = benchList.slice(0, 25).map(b => `
        <div class="bg-slate-900 border border-slate-800 p-3 rounded-lg flex justify-between items-center text-xs">
            <div>
                <span class="font-bold text-accent">${escHtml(b.owner)}</span>
                <span class="text-slate-400 ml-1">(${escHtml(b.league)} &bull; ${escHtml(b.week)})</span>
                <p class="text-slate-300 mt-0.5">Benched: <strong class="text-amber-400">${escHtml(b.topBench)}</strong></p>
            </div>
            <span class="bg-amber-500/10 text-amber-300 border border-amber-500/20 px-2.5 py-1 rounded font-mono font-bold">${b.benchPts.toFixed(2)} pts</span>
        </div>
    `).join('');

    document.getElementById('weekly-highs-list').innerHTML = weeklyHighs.map(w => `
        <div class="bg-slate-900 border border-slate-800 p-3 rounded-lg flex justify-between items-center text-xs">
            <div>
                <span class="font-bold text-accent">${escHtml(w.owner)}</span>
                <span class="text-slate-400 ml-1">(${escHtml(w.league)} &bull; ${escHtml(w.week)})</span>
                <p class="text-slate-300 mt-0.5">MVP Starter: <strong class="text-emerald-400">${escHtml(w.topStarter)}</strong></p>
            </div>
            <span class="bg-emerald-500/10 text-emerald-300 border border-emerald-500/20 px-2.5 py-1 rounded font-mono font-bold">${w.totalScore.toFixed(2)} pts</span>
        </div>
    `).join('');
}
