// tabs/draft-picks-matrix.js: Draft Picks Matrix (Draft Picks tab).
// Classic script, loaded after utils.js and before app.js (see index.html). Top-level code here only
// declares functions/state; calls into app.js functions happen at runtime, after every script has loaded.

// --- TAB 7: DRAFT PICKS MATRIX ---
function renderDraftPicksMatrix() {
    const grid = document.getElementById('picks-matrix-grid');
    grid.innerHTML = '';
    const ownerPicks = {};

    Object.keys(globalMasterData).forEach(leagueName => {
        const rows = globalMasterData[leagueName] || [];
        let section = '';

        rows.forEach(r => {
            const col0 = String(r[0] || '').trim();
            const newSec = getSectionType(col0);
            if (newSec) { section = newSec; return; }
            if (section !== 'rosters' || isColumnHeaderRow(col0) || !r[0]) return;

            const owner = getMasterOwner(col0);
            const picksStr = String(r[4] || '').trim();
            const picksList = picksStr ? picksStr.split(',').map(s => s.trim()).filter(s => s && s.toLowerCase() !== 'none') : [];

            if (!ownerPicks[owner]) {
                ownerPicks[owner] = { totalPicks: 0, firstRoundCount: 0, ktcValue: 0, byLeague: {} };
            }

            ownerPicks[owner].byLeague[leagueName] = picksList;
            picksList.forEach(p => {
                ownerPicks[owner].totalPicks++;
                ownerPicks[owner].ktcValue += scoreDraftPickKTC(p, leagueName);
                if (/Round\s+1\b/i.test(p)) ownerPicks[owner].firstRoundCount++;
            });
        });
    });

    const sortedOwners = Object.keys(ownerPicks).sort((a, b) => {
        if (ownerPicks[b].firstRoundCount !== ownerPicks[a].firstRoundCount) return ownerPicks[b].firstRoundCount - ownerPicks[a].firstRoundCount;
        return ownerPicks[b].ktcValue - ownerPicks[a].ktcValue;
    });

    sortedOwners.forEach(owner => {
        const data = ownerPicks[owner];
        const card = document.createElement('div');
        card.className = "bg-cardbg border border-slate-700 rounded-xl p-6 shadow-sm space-y-4 flex flex-col justify-between";

        let leaguesHtml = '';
        Object.keys(data.byLeague).forEach(lg => {
            const picks = data.byLeague[lg];
            const counts = {};
            picks.forEach(p => { counts[p] = (counts[p] || 0) + 1; });

            const badges = Object.keys(counts).map(p => {
                const qty = counts[p];
                const isFirst = /Round\s+1\b/i.test(p);
                const badgeClass = isFirst
                    ? "bg-amber-500/20 text-amber-300 border-amber-500/40 font-bold"
                    : "bg-slate-800 text-slate-300 border-slate-700";
                return `<span class="inline-block text-xs px-2 py-0.5 rounded border ${badgeClass}">${qty > 1 ? qty + 'x ' : ''}${escHtml(p)}</span>`;
            }).join(' ');

            leaguesHtml += `
                <div class="bg-slate-900 border border-slate-800 p-3 rounded-lg space-y-2">
                    <div class="flex justify-between items-center text-xs">
                        <span class="font-bold text-accent uppercase tracking-wider">${escHtml(lg)}</span>
                        <span class="text-slate-400">${picks.length} Picks</span>
                    </div>
                    <div class="flex flex-wrap gap-1.5">
                        ${badges || '<span class="text-xs text-slate-500">No future picks</span>'}
                    </div>
                </div>
            `;
        });

        card.innerHTML = `
            <div class="space-y-3">
                <div class="flex justify-between items-start gap-2">
                    <div>
                        <h3 class="text-lg font-bold text-accent">${escHtml(owner)}</h3>
                        <p class="text-xs text-emerald-400 font-semibold mt-0.5">Pick Capital: ${data.ktcValue.toLocaleString()} KTC</p>
                    </div>
                    <div class="text-right">
                        <span class="bg-amber-500/10 text-amber-400 border border-amber-500/20 px-2.5 py-1 rounded-full text-xs font-bold block">🔥 ${data.firstRoundCount}x 1st Rd</span>
                        <span class="text-xs text-slate-400 mt-1 block">${data.totalPicks} Total Picks</span>
                    </div>
                </div>
                <div class="space-y-2.5 max-h-80 overflow-y-auto pr-1">
                    ${leaguesHtml}
                </div>
            </div>
        `;
        grid.appendChild(card);
    });
}
