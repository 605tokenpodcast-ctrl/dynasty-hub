// tabs/sacko-wall.js: Sacko Hall of Shame (Dashboard tab).
// Classic script, loaded after utils.js and before app.js. Everything here is only called later
// (from TAB_RENDERERS.dashboard in app.js), so it can use app.js functions such as buildHubData()
// and the helpers in utils.js (escHtml) as globals.

function renderSackoWall() {
    const box = document.getElementById('sacko-wall');
    if (!box) return;
    const tally = {};
    Object.values(buildHubData().seasons).forEach(st => {
        if (!st.sacko) return;
        (tally[st.sacko] = tally[st.sacko] || []).push(`${st.league} (${st.season})`);
    });
    const owners = Object.keys(tally).sort((a, b) => tally[b].length - tally[a].length || a.localeCompare(b));
    box.innerHTML = owners.length ? owners.map(o => `
        <div class="bg-cardbg border border-rose-900/50 rounded-xl p-4 space-y-2">
            <div class="flex justify-between items-start gap-2">
                <h4 class="font-bold text-rose-200">${escHtml(o)}</h4>
                <span class="bg-rose-500/10 text-rose-300 border border-rose-500/20 px-2.5 py-0.5 rounded-full text-xs font-bold whitespace-nowrap">💩 ${tally[o].length} Sacko${tally[o].length > 1 ? 's' : ''}</span>
            </div>
            <p class="text-xs text-slate-400">${escHtml(tally[o].join(', '))}</p>
        </div>`).join('') : '<p class="text-xs text-slate-500">No finished seasons yet.</p>';
}
