// tabs/player-exposure.js: Player Exposure matrix tab (multi-league player exposure).
// Classic script, loaded after utils.js and before app.js (see index.html). Top-level code here only
// declares functions/state; calls into app.js functions happen at runtime, after every script has loaded.

// --- TAB 4: MULTI-LEAGUE PLAYER EXPOSURE MATRIX ---
function initExposureFilter() {
    const mgrs = new Set();
    Object.keys(globalMasterData).forEach(leagueName => {
        const rows = globalMasterData[leagueName] || [];
        let section = '';
        rows.forEach(r => {
            const col0 = String(r[0] || '').trim();
            const newSec = getSectionType(col0);
            if (newSec) { section = newSec; return; }
            if (section === 'rosters' && !isColumnHeaderRow(col0) && col0) {
                mgrs.add(getMasterOwner(col0));
            }
        });
    });
    const sel = document.getElementById('exposure-mgr-filter');
    sel.innerHTML = '<option value="ALL">All Managers (Global Exposure)</option>';
    Array.from(mgrs).sort().forEach(m => sel.appendChild(new Option(m, m)));
}

function renderPlayerExposure() {
    const mgrFilter = document.getElementById('exposure-mgr-filter').value;
    const query = (document.getElementById('exposure-search')?.value || '').toLowerCase();
    const grid = document.getElementById('exposure-grid');

    const playerMap = {};

    Object.keys(globalMasterData).forEach(leagueName => {
        const rows = globalMasterData[leagueName] || [];
        let section = '';

        rows.forEach(r => {
            const col0 = String(r[0] || '').trim();
            const newSec = getSectionType(col0);
            if (newSec) { section = newSec; return; }
            if (section !== 'rosters' || isColumnHeaderRow(col0) || !col0) return;

            const owner = getMasterOwner(col0);
            if (mgrFilter !== 'ALL' && owner !== mgrFilter) return;

            const roster = String(r[3] || '').split(',').map(s => s.trim()).filter(Boolean);
            roster.forEach(pEntry => {
                if (query && !pEntry.toLowerCase().includes(query) && !owner.toLowerCase().includes(query)) return;
                if (!playerMap[pEntry]) {
                    playerMap[pEntry] = {
                        entry: pEntry,
                        ktc: scorePlayerKTC(pEntry), // default format, so it doesn't depend on which league comes first
                        shares: []
                    };
                }
                playerMap[pEntry].shares.push({ league: leagueName, owner });
            });
        });
    });

    const sortedPlayers = Object.values(playerMap).sort((a, b) => {
        if (b.shares.length !== a.shares.length) return b.shares.length - a.shares.length;
        return b.ktc - a.ktc;
    }).slice(0, 60);

    if (sortedPlayers.length === 0) {
        grid.innerHTML = `<p class="text-slate-400 col-span-3 text-center py-6">No matching players found.</p>`;
        return;
    }

    grid.innerHTML = sortedPlayers.map(p => {
        const ownerBadges = p.shares.map(s => `
            <span class="bg-slate-900 border border-slate-800 px-2 py-1 rounded text-xs flex justify-between items-center">
                <strong class="text-accent">${escHtml(s.owner)}</strong>
                <span class="text-slate-400 text-[11px] ml-2">${escHtml(s.league)}</span>
            </span>
        `).join('');

        return `
            <div class="bg-cardbg border border-slate-700 rounded-xl p-4 shadow-sm space-y-3 flex flex-col justify-between">
                <div class="flex justify-between items-start gap-2">
                    <div>
                        <h4 class="font-bold text-white text-sm">${escHtml(p.entry)}</h4>
                        <p class="text-xs text-emerald-400 font-semibold">${p.ktc.toLocaleString()} KTC</p>
                    </div>
                    <span class="bg-blue-500/10 text-blue-400 border border-blue-500/20 px-2.5 py-0.5 rounded-full text-xs font-bold whitespace-nowrap">
                        ${p.shares.length} Share${p.shares.length > 1 ? 's' : ''}
                    </span>
                </div>
                <div class="space-y-1.5 pt-2 border-t border-slate-800">
                    ${ownerBadges}
                </div>
            </div>
        `;
    }).join('');
}
