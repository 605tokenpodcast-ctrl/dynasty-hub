// tabs/trade-synergy.js: Trade Partner Synergy tab: pair matrix and the trade-pair modal (owns tradePairDatabase and sortedSynergyPairs).
// Classic script, loaded after utils.js and before app.js (see index.html). Top-level code here only
// declares functions/state; calls into app.js functions happen at runtime, after every script has loaded.

// State used only by this tab (renderTradeSynergy fills it, openTradeModal reads it)
let sortedSynergyPairs = [];
const tradePairDatabase = {};

// --- TAB 10: TRADE PARTNER SYNERGY MATRIX ---
function renderTradeSynergy() {
    const container = document.getElementById('synergy-content');
    const pairCounts = {};
    Object.keys(tradePairDatabase).forEach(k => delete tradePairDatabase[k]);

    Object.keys(globalMasterData).forEach(leagueName => {
        const rows = globalMasterData[leagueName] || [];
        let section = '';

        rows.forEach(r => {
            const col0 = String(r[0] || '').trim();
            const newSec = getSectionType(col0);
            if (newSec) { section = newSec; return; }
            if (section !== 'trades' || isColumnHeaderRow(col0) || !col0 || !r[3] || !r[4]) return;

            const tradeTeams = String(r[3]).split('&').map(t => getMasterOwner(t.trim())).filter(Boolean);
            if (tradeTeams.length >= 2) {
                const p1 = tradeTeams[0];
                const p2 = tradeTeams[1];
                if (p1 && p2 && p1 !== p2) {
                    const pairKey = [p1, p2].sort().join(' 🤝 ');
                    pairCounts[pairKey] = (pairCounts[pairKey] || 0) + 1;

                    if (!tradePairDatabase[pairKey]) tradePairDatabase[pairKey] = [];
                    tradePairDatabase[pairKey].push({
                        league: leagueName,
                        season: r[0] || '',
                        date: r[1] || '',
                        week: r[2] || '',
                        teams: r[3],
                        breakdown: r[4],
                        row: r
                    });
                }
            }
        });
    });

    sortedSynergyPairs = Object.keys(pairCounts).sort((a, b) => pairCounts[b] - pairCounts[a]);

    let html = `<table class="w-full text-left text-sm border-collapse">`;
    html += `<thead class="bg-slate-900 text-slate-400 border-b border-slate-700"><tr><th class="p-3">Trading Pair (Click to Inspect Deals)</th><th class="p-3 text-right">Blockbusters Completed</th></tr></thead><tbody class="divide-y divide-slate-800">`;

    if (sortedSynergyPairs.length > 0) {
        sortedSynergyPairs.forEach((pair, idx) => {
            html += `
                <tr onclick="openTradeModal(${idx})" class="hover:bg-slate-800/60 transition cursor-pointer">
                    <td class="p-3 font-semibold text-white flex items-center gap-2">
                        <span class="text-accent">🔍</span> ${escHtml(pair)}
                    </td>
                    <td class="p-3 text-right font-bold text-accent">${pairCounts[pair]} Trade${pairCounts[pair] > 1 ? 's' : ''}</td>
                </tr>
            `;
        });
    } else {
        html += `<tr><td colspan="2" class="p-4 text-slate-400 text-center">No trade partnerships extracted.</td></tr>`;
    }

    html += `</tbody></table>`;
    container.innerHTML = html;
}

function openTradeModal(pairIndex) {
    const pairKey = sortedSynergyPairs[pairIndex];
    if (!pairKey) return;

    const modal = document.getElementById('trade-modal');
    const title = document.getElementById('modal-title');
    const body = document.getElementById('modal-body');

    const trades = tradePairDatabase[pairKey] || [];
    title.innerText = `${pairKey} (${trades.length} Trade${trades.length > 1 ? 's' : ''})`;

    body.innerHTML = trades.map(t => `
        <div class="pt-3 first:pt-0 space-y-1.5">
            <div class="flex justify-between items-center text-xs text-slate-400 font-semibold">
                <span class="text-accent uppercase tracking-wider">${escHtml(t.league)}</span>
                <span>${escHtml(t.season)} &bull; ${escHtml(t.week)} (${escHtml(t.date)})</span>
            </div>
            <p class="font-bold text-white text-xs">${escHtml(t.teams)}</p>
            <div class="text-slate-300 text-xs leading-relaxed">${formatTradeBreakdown(t.breakdown)}</div>
            <div class="mt-2 p-3 rounded-lg bg-slate-900/60 border border-slate-800 text-xs leading-relaxed">
                <p class="text-slate-500 text-[11px] uppercase tracking-wide mb-1">Trade Grade</p>
                ${tradeGradeCell(t.row, t.league, tradeTimestamp(t.row))}
            </div>
        </div>
    `).join('');

    modal.classList.remove('hidden');
}

function closeTradeModal() {
    document.getElementById('trade-modal').classList.add('hidden');
}
