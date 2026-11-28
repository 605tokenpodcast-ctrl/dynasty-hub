// tabs/trophy-room.js: Trophy Room (Dashboard tab): titles, runner-ups and third places per manager.
// Classic script, loaded after utils.js and before app.js (see index.html). Top-level code here only
// declares functions/state; calls into app.js functions happen at runtime, after every script has loaded.

// --- TAB 1: TROPHY ROOM ---
function renderTrophyRoom(leagueNames) {
    const grid = document.getElementById('trophy-room-grid');
    grid.innerHTML = '';
    const managers = {};

    leagueNames.forEach(leagueName => {
        const rows = globalMasterData[leagueName] || [];
        let section = '';

        rows.forEach(r => {
            const col0 = String(r[0] || '').trim();
            const newSec = getSectionType(col0);
            if (newSec) { section = newSec; return; }
            if (section !== 'standings' || isColumnHeaderRow(col0) || !r[1]) return;

            const rawTeam = String(r[1]).trim();
            const master = getMasterOwner(rawTeam);
            const placement = String(r[4] || '');
            const season = String(r[0] || '');

            if (!managers[master]) {
                managers[master] = {
                    titles: 0, runnerUps: 0, thirdPlaces: 0,
                    titleDetails: [], allLeagues: new Set()
                };
            }

            managers[master].allLeagues.add(leagueName);

            if (placement.includes('League Champion')) {
                managers[master].titles++;
                managers[master].titleDetails.push(`${leagueName} (${season})`);
            } else if (placement.includes('Runner-Up')) {
                managers[master].runnerUps++;
            } else if (placement.includes('3rd Place')) {
                managers[master].thirdPlaces++;
            }
        });
    });

    const champsList = Object.keys(managers)
        .filter(m => managers[m].titles > 0)
        .sort((a, b) => {
            if (managers[b].titles !== managers[a].titles) return managers[b].titles - managers[a].titles;
            if (managers[b].runnerUps !== managers[a].runnerUps) return managers[b].runnerUps - managers[a].runnerUps;
            return managers[b].thirdPlaces - managers[a].thirdPlaces;
        });

    champsList.forEach(manager => {
        const data = managers[manager];
        const meta = managerMeta[manager] || {};
        const card = document.createElement('div');
        card.className = "bg-cardbg border border-slate-700 rounded-xl p-6 shadow-sm flex flex-col justify-between space-y-4";
        card.innerHTML = `
            <div>
                <div class="flex justify-between items-start gap-2">
                    <div>
                        <h3 class="text-xl font-bold text-accent">${escHtml(manager)}</h3>
                        ${meta.tagline ? `<p class="text-xs text-amber-400/90 font-medium mt-0.5">"${escHtml(meta.tagline)}"</p>` : ''}
                    </div>
                    <span class="bg-amber-500/10 text-amber-400 border border-amber-500/20 px-3 py-1 rounded-full text-xs font-bold whitespace-nowrap">
                        🏆 ${data.titles} Title${data.titles > 1 ? 's' : ''}
                    </span>
                </div>
                <div class="flex gap-3 mt-3 text-xs text-slate-300">
                    <span class="bg-slate-900 border border-slate-800 px-2.5 py-1 rounded">🥈 ${data.runnerUps} Runner-Up</span>
                    <span class="bg-slate-900 border border-slate-800 px-2.5 py-1 rounded">🥉 ${data.thirdPlaces} 3rd Place</span>
                </div>
            </div>
            <div class="pt-3 border-t border-slate-800 text-xs space-y-1.5">
                <p class="text-slate-400">Title Banners: <span class="text-amber-300 font-semibold">${escHtml(data.titleDetails.join(', '))}</span></p>
                <p class="text-slate-400">Active Leagues (${data.allLeagues.size}): <span class="text-slate-200 font-semibold">${escHtml(Array.from(data.allLeagues).join(', '))}</span></p>
            </div>
        `;
        grid.appendChild(card);
    });
}
