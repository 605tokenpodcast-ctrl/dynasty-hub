// tabs/badge-legend.js: Badge Legend (Managers tab): 'how badges are earned' list. Reads BADGE_RULES/BADGE_STYLES (app.js) at runtime.
// Classic script, loaded after utils.js and before app.js (see index.html). Top-level code here only
// declares functions/state; calls into app.js functions happen at runtime, after every script has loaded.

// "How badges are earned" list at the top of the Managers tab, with who holds each one
function renderBadgeLegend() {
    const box = document.getElementById('badge-legend-list');
    if (!box) return;
    const byOwner = computeManagerBadges();
    box.innerHTML = BADGE_RULES.map(rule => {
        const holders = Object.keys(byOwner).filter(o => byOwner[o].some(b => b.name === rule.name))
            .sort((a, b) => (byOwner[b].find(x => x.name === rule.name).value - byOwner[a].find(x => x.name === rule.name).value) || a.localeCompare(b));
        return `
        <li class="py-2 border-b border-slate-800 last:border-0">
            <p><span class="border ${BADGE_STYLES[rule.kind]} px-2 py-0.5 rounded-full font-semibold whitespace-nowrap">${rule.icon} ${escHtml(rule.name)}</span>
            <span class="text-slate-300 ml-1">${escHtml(rule.rule)}</span></p>
            <p class="text-slate-500 mt-1">${holders.length ? escHtml(holders.join(', ')) : 'Nobody yet.'}</p>
        </li>`;
    }).join('');
}
