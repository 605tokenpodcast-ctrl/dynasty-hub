// tabs/player-journey.js: Player Journey tab (owns journeyIndex).
// Classic script, loaded after utils.js and before app.js (see index.html). Top-level code here only
// declares functions/state; calls into app.js functions happen at runtime, after every script has loaded.

// --- TAB: PLAYER JOURNEY ---
// normalized name -> { name, pos, events: [{ league, ts, kind, text }], starts: { "league||season||owner": {...} }, rostered: [...] }
let journeyIndex = null;
function buildJourneyIndex() {
    if (journeyIndex) return journeyIndex;
    const idx = {};
    const entry = (name, pos) => {
        const clean = String(name || '').trim();
        if (!clean) return null;
        const k = normalizePlayerName(clean);
        const e = idx[k] = idx[k] || { name: clean, pos: '', events: [], starts: {}, rostered: [] };
        if (pos && !e.pos && !/flex/i.test(pos)) e.pos = pos;
        return e;
    };
    const dateTs = d => {
        const m = String(d || '').match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
        return m ? new Date(+m[3], +m[1] - 1, +m[2]).getTime() : 0;
    };
    Object.keys(globalMasterData).forEach(league => {
        if (!Array.isArray(globalMasterData[league])) return;
        sectionRows(league, 'drafts').forEach(r => {
            const m = String(r[5] || '').match(/^(.*?)\s*\(([^()]+)\)$/);
            const e = m && entry(m[1], m[2]);
            if (!e) return;
            const who = getMasterOwner(r[4]);
            const from = r[6] ? ` (pick originally ${getMasterOwner(r[6])}'s)` : '';
            e.events.push({ league, ts: new Date(parseInt(r[0], 10) || 2000, 4, 1).getTime(), season: r[0], kind: 'draft', who,
                text: `${r[0]} ${String(r[1] || 'draft').toLowerCase()} draft: round ${r[2]}, pick ${r[3]} by ${who}${from}` });
        });
        sectionRows(league, 'trades').forEach(r => {
            if (!r[3] || !r[4]) return;
            const sides = String(r[4]).split(' <---> ').map(side => {
                const m = side.match(/^(.*?) received: \[(.*)\]$/);
                return m ? { owner: getMasterOwner(m[1].trim()), items: m[2] === 'Nothing' ? [] : m[2].split(/,\s*(?![^()]*\))/) } : null;
            }).filter(Boolean);
            sides.forEach(side => {
                const others = sides.filter(x => x !== side).map(x => x.owner).join(' & ');
                side.items.forEach(item => {
                    const it = item.trim();
                    const drafted = it.match(/^(\d{4}) Round (\d+)\w* Pick.*?-> Resulted in drafting:\s*(.*?)\s*\(([^()]+)\)\s*$/);
                    if (drafted) {
                        const e = entry(drafted[3], drafted[4]);
                        if (e) e.events.push({ league, ts: tradeTimestamp(r), kind: 'pick', who: side.owner,
                            text: `${r[1] || r[0]}: the ${drafted[1]} round ${drafted[2]} pick that became him went to ${side.owner} in a trade with ${others}` });
                        return;
                    }
                    if (/^\d{4} Round/.test(it)) return;
                    const m = it.match(/^(.*?)\s*\(([A-Z/]+)(?:\s*-\s*[A-Z]+)?\)$/);
                    const e = m && entry(m[1], m[2]);
                    if (e) e.events.push({ league, ts: tradeTimestamp(r), kind: 'trade', who: side.owner,
                        text: `${r[1] || r[0]}: traded to ${side.owner} by ${others}` });
                });
            });
        });
        sectionRows(league, 'moves').forEach(r => {
            const owner = getMasterOwner(r[3]);
            const bid = parseFloat(r[7]) || 0;
            parseNameList(r[5]).forEach(p => {
                const e = entry(p.name, p.pos);
                if (e) e.events.push({ league, ts: dateTs(r[2]) || new Date(parseInt(r[0], 10) || 2000, 8, 1).getTime(), kind: 'add', who: owner,
                    text: `${r[2] || r[0] + ' ' + r[1]}: picked up by ${owner} (${String(r[4] || 'move').toLowerCase()}${bid ? `, $${bid}` : ''})` });
            });
            parseNameList(r[6]).forEach(p => {
                const e = entry(p.name, p.pos);
                if (e) e.events.push({ league, ts: dateTs(r[2]) || new Date(parseInt(r[0], 10) || 2000, 8, 1).getTime(), kind: 'drop', who: owner,
                    text: `${r[2] || r[0] + ' ' + r[1]}: dropped by ${owner}` });
            });
        });
        sectionRows(league, 'lineups').forEach(r => {
            const owner = getMasterOwner(r[2]);
            const add = (list, started) => parseLineupList(list).forEach(p => {
                const e = entry(p.name, p.pos);
                if (!e) return;
                const k = `${league}||${r[0]}||${owner}`;
                const st = e.starts[k] = e.starts[k] || { league, season: r[0], owner, starts: 0, pts: 0, weeks: 0, best: 0 };
                st.weeks++;
                if (started) { st.starts++; st.pts += p.pts; st.best = Math.max(st.best, p.pts); }
            });
            add(r[5], true);
            add(r[6], false);
        });
        sectionRows(league, 'rosters').forEach(r => {
            String(r[3] || '').split(',').map(x => x.trim()).filter(Boolean).forEach(p => {
                const m = p.match(/^(.+?)\s*\(([A-Z]+)\s*-\s*([A-Z]+)\)$/);
                const e = entry(m ? m[1] : p, m ? m[2] : '');
                if (e) e.rostered.push({ league, owner: getMasterOwner(r[0]), nfl: m ? m[3] : '' });
            });
        });
    });
    return (journeyIndex = idx);
}

function initPlayerJourney() {
    const idx = buildJourneyIndex();
    // Suggestions: players with some history, most-traveled first
    const names = Object.values(idx).filter(e => e.events.length || Object.keys(e.starts).length)
        .sort((a, b) => (b.events.length + Object.keys(b.starts).length) - (a.events.length + Object.keys(a.starts).length));
    document.getElementById('journey-names').innerHTML = names.slice(0, 1500).map(e => `<option value="${escHtml(e.name)}">`).join('');
    renderPlayerJourney();
}

function renderPlayerJourney() {
    const box = document.getElementById('journey-content');
    const q = normalizePlayerName(document.getElementById('journey-search').value);
    const idx = buildJourneyIndex();
    if (!q) {
        // Most-traveled players as a starting point
        const top = Object.values(idx).filter(e => /^(QB|RB|WR|TE)$/.test(e.pos)).map(e => ({ e, owners: new Set(e.events.map(x => x.who).concat(Object.values(e.starts).filter(s => s.starts).map(s => s.owner))).size }))
            .sort((a, b) => b.owners - a.owners).slice(0, 12);
        box.innerHTML = `<div class="bg-cardbg border border-slate-700 rounded-xl p-5 space-y-3">
            <h3 class="font-bold text-white">🧳 Most-traveled players</h3>
            <p class="text-xs text-slate-400">Played for, or passed through, the most managers. Tap one, or search above.</p>
            <div class="flex flex-wrap gap-2">${top.map(t => `<button type="button" onclick="openJourney(this.dataset.name)" data-name="${escHtml(t.e.name)}" class="bg-slate-900 border border-slate-700 hover:border-accent rounded-full px-3 py-1 text-xs font-semibold text-slate-200">${escHtml(t.e.name)} <span class="text-slate-500">${t.owners} teams</span></button>`).join('')}</div>
        </div>`;
        return;
    }
    let e = idx[q];
    if (!e) {
        const matches = Object.keys(idx).filter(k => k.includes(q)).slice(0, 12);
        if (matches.length === 1) e = idx[matches[0]];
        else {
            box.innerHTML = matches.length
                ? `<div class="flex flex-wrap gap-2">${matches.map(k => `<button type="button" onclick="openJourney(this.dataset.name)" data-name="${escHtml(idx[k].name)}" class="bg-slate-900 border border-slate-700 hover:border-accent rounded-full px-3 py-1 text-xs font-semibold text-slate-200">${escHtml(idx[k].name)}</button>`).join('')}</div>`
                : '<p class="text-sm text-slate-400">No player by that name in any league\'s history.</p>';
            return;
        }
    }

    const leagues = [...new Set([...e.events.map(x => x.league), ...Object.values(e.starts).map(s => s.league), ...e.rostered.map(r => r.league)])].sort();
    // Career points scored for each manager (starting lineups only)
    const byOwner = {};
    Object.values(e.starts).forEach(s => {
        const o = byOwner[s.owner] = byOwner[s.owner] || { owner: s.owner, starts: 0, pts: 0, leagues: new Set() };
        o.starts += s.starts; o.pts += s.pts; o.leagues.add(s.league);
    });
    const owners = Object.values(byOwner).filter(o => o.starts).sort((a, b) => b.pts - a.pts);
    const icons = { draft: '📋', trade: '🔁', pick: '🎟️', add: '➕', drop: '✂️' };
    const sections = leagues.map(lg => {
        const items = e.events.filter(x => x.league === lg).map(x => ({ ts: x.ts, html: `${icons[x.kind] || '•'} ${escHtml(x.text)}` }));
        Object.values(e.starts).filter(s => s.league === lg).forEach(s => {
            items.push({ ts: new Date(parseInt(s.season, 10) || 2000, 11, 31).getTime() + 1, html: s.starts
                ? `🏈 <strong class="text-white">${escHtml(s.season)} for ${escHtml(s.owner)}</strong>: ${s.starts} start${s.starts === 1 ? '' : 's'}, ${s.pts.toFixed(1)} pts (${(s.pts / s.starts).toFixed(1)} a start, best ${s.best.toFixed(1)})${s.weeks > s.starts ? `, ${s.weeks - s.starts} week${s.weeks - s.starts === 1 ? '' : 's'} on the bench` : ''}`
                : `🪑 ${escHtml(s.season)} for ${escHtml(s.owner)}: on the bench all ${s.weeks} week${s.weeks === 1 ? '' : 's'}` });
        });
        items.sort((a, b) => a.ts - b.ts);
        const now = e.rostered.filter(r => r.league === lg);
        return `<div class="bg-cardbg border border-slate-700 rounded-xl p-4 space-y-2">
            <div class="flex justify-between items-center gap-2">
                <h3 class="font-bold text-white truncate">${escHtml(lg)}</h3>
                <span class="text-xs ${now.length ? 'text-emerald-300' : 'text-slate-500'} shrink-0">${now.length ? `Now: ${now.map(r => escHtml(r.owner)).join(', ')}` : 'Not rostered now'}</span>
            </div>
            <ul class="space-y-1.5 text-xs text-slate-300">${items.map(i => `<li>${i.html}</li>`).join('') || '<li class="text-slate-500">Rostered, nothing else on record.</li>'}</ul>
        </div>`;
    });
    const value = Math.max(0, ...leagues.map(lg => playerValueByName(e.name, lg)));
    const age = (playerMeta[e.name] || [])[0];
    box.innerHTML = `
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3">
            <div class="flex flex-wrap justify-between items-baseline gap-2">
                <h3 class="text-xl font-extrabold text-white">${escHtml(e.name)} <span class="text-sm text-slate-400 font-semibold">${escHtml(e.pos)}${age ? ` · age ${escHtml(age)}` : ''}</span></h3>
                ${value ? `<span class="text-sm text-emerald-300 font-bold">Value today ${value.toLocaleString()}</span>` : ''}
            </div>
            ${owners.length ? `<div class="flex flex-wrap gap-2 text-xs">${owners.map(o => `<span class="bg-cardbg border border-slate-700 rounded-lg px-2.5 py-1"><strong class="text-accent">${escHtml(o.owner)}</strong> ${o.pts.toFixed(0)} pts in ${o.starts} starts</span>`).join('')}</div>
            <p class="text-[11px] text-slate-500">Points he scored in each manager's starting lineup, all leagues${owners.length > 1 ? `. Most for ${escHtml(owners[0].owner)}` : ''}.</p>` : ''}
        </div>
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">${sections.join('')}</div>`;
}

function openJourney(name) {
    document.getElementById('journey-search').value = name;
    renderPlayerJourney();
}
