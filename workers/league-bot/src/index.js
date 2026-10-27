// Cloudflare Worker: the Dynasty Hub league bot.
//
// Runs on Cron Triggers (see wrangler.toml) and posts to your group chat:
//   - every 15 minutes: TRADE ALERTS for new trades in any league, with today's value swing
//   - Tuesday 10am CT:  WEEKLY RECAP per league (high score belt, toilet bowl, blowout, nail-biter,
//                       robbed, lucky win)
//   - 30 minutes later: with an Anthropic API key, a "Dynasty Gazette" article per league, stored
//                       for the site's Season Review tab and posted to the chat. It runs in its own
//                       slots (10:30, 10:45, 11:00, 11:15) so each run stays under the free plan's
//                       50 outbound requests; a run that runs low leaves the rest for the next slot.
// Each chat message goes out about 30 seconds after the one before, so a busy run doesn't arrive
// as one wall of text.
//   - Thursday 6pm CT:  MATCHUP PREVIEWS with season averages and win odds
//
// HTTP routes (CORS-enabled for the site):
//   GET /gazette?league=<name>&season=<yyyy>  -> [{ week, text }] for the Season Review tab
//   GET /run?job=alerts|recap|gazette|previews[&dry=1] with header X-Admin-Key: <ADMIN_KEY>  -> run a job by hand
//       (?key=<ADMIN_KEY> also works, but the key then shows up in Cloudflare's request logs)
//
// Settings: LEAGUES, SITE_URL and CHAT_POSTING (on/off) are vars in wrangler.toml. Secrets (wrangler secret put, or the
// dashboard): DISCORD_WEBHOOK_URL and/or GROUPME_BOT_ID, ANTHROPIC_API_KEY (optional), ADMIN_KEY.
import Anthropic from '@anthropic-ai/sdk';

const SLEEPER = 'https://api.sleeper.app/v1';
const FLEA = 'https://www.fleaflicker.com/api';

export default {
  async scheduled(event, env) {
    // Awaited rather than waitUntil: the spacing between chat posts keeps a run going for minutes,
    // which Cron Triggers allow (15 minutes of wall time; waiting doesn't count as CPU time)
    await runJob(jobAt(event.scheduledTime), env, false);
  },

  async fetch(request, env) {
    const url = new URL(request.url);
    const cors = { 'Access-Control-Allow-Origin': '*', 'Content-Type': 'application/json' };
    if (url.pathname === '/gazette') {
      const league = url.searchParams.get('league') || '';
      const season = url.searchParams.get('season') || '';
      const list = (await env.BOT_KV.get(gazetteKey(league, season), 'json')) || [];
      return new Response(JSON.stringify(list), { headers: { ...cors, 'Cache-Control': 'public, max-age=300' } });
    }
    if (url.pathname === '/run') {
      // The X-Admin-Key header keeps the key out of Cloudflare's request logs; ?key= still works from a browser
      const key = request.headers.get('X-Admin-Key') || url.searchParams.get('key');
      if (!env.ADMIN_KEY || key !== env.ADMIN_KEY) return new Response('Forbidden', { status: 403 });
      const job = url.searchParams.get('job');
      if (!['alerts', 'recap', 'gazette', 'previews'].includes(job)) return new Response('Unknown job', { status: 400 });
      const out = await runJob(job, env, url.searchParams.get('dry') === '1');
      return new Response(JSON.stringify(out, null, 2), { headers: cors });
    }
    return new Response('Dynasty Hub league bot', { headers: { 'Content-Type': 'text/plain' } });
  },
};

// Weekly jobs by Central time (Cron Triggers only know UTC). A weekly job takes the place of that
// quarter hour's trade alerts, which keeps each run under the free plan's request limit.
// The Gazette gets four slots: each run writes and posts what fits in its request budget, and
// leagues already posted this week cost nothing in the later slots.
const WEEKLY = {
  'Tue 10:00': 'recap',
  'Tue 10:30': 'gazette', 'Tue 10:45': 'gazette', 'Tue 11:00': 'gazette', 'Tue 11:15': 'gazette',
  'Thu 18:00': 'previews',
};
function jobAt(time) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/Chicago', weekday: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(new Date(time)).map(p => [p.type, p.value]));
  return WEEKLY[`${parts.weekday} ${parts.hour}:${parts.minute}`] || 'alerts';
}

// Per-run caches: Workers on the free plan get 50 outbound requests per run, so nothing is fetched twice
let memo = new Map();
// Outbound requests made by this run (data, Claude and chat posts), checked against the limit
let used = 0;
const REQUEST_LIMIT = 50;
function counted(url, init) {
  used++;
  return fetch(url, init);
}
function once(key, fn) {
  if (!memo.has(key)) memo.set(key, fn());
  return memo.get(key);
}

async function runJob(job, env, dry) {
  memo = new Map();
  used = 0;
  lastPost = 0;
  const leagues = JSON.parse(env.LEAGUES || '[]');
  const state = await getJson(`${SLEEPER}/state/nfl`);
  const season = Number(state.season);
  const messages = [];
  const notes = [];
  const say = text => messages.push(text);
  for (const lg of leagues) {
    try {
      if (job === 'alerts') await tradeAlerts(lg, state, env, say, dry);
      if (job === 'recap') await weeklyRecap(lg, season, Number(state.week), env, say);
      if (job === 'gazette') notes.push(`${lg.name}: ${await weeklyGazette(lg, leagues, season, Number(state.week), env, say, dry)}`);
      if (job === 'previews' && state.season_type === 'regular') await previews(lg, season, Number(state.week), say);
    } catch (e) {
      console.log(`${job} ${lg.name}: ${e.stack || e}`);
      notes.push(`${lg.name}: error: ${e.message || e}`);
    }
  }
  // One chat message per league (or per trade), spaced out by post(). The Gazette posts its own
  // articles as it writes them, so it isn't collected here.
  if (!dry && job !== 'gazette') {
    for (const text of messages) await post(env, text);
  }
  return { job, season, week: state.week, requests: used, notes, messages };
}

// ---------- data helpers ----------
async function getJson(url) {
  const r = await counted(url, { headers: { 'User-Agent': 'dynasty-hub league bot' } });
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.json();
}

const num = x => {
  if (x && typeof x === 'object') x = x.value ?? x.formatted;
  const n = parseFloat(String(x ?? '').replace(/,/g, ''));
  return isNaN(n) ? 0 : n;
};

function sleeperRosters(leagueId) {
  return once(`rosters:${leagueId}`, () => getJson(`${SLEEPER}/league/${leagueId}/rosters`));
}

async function sleeperLabels(leagueId) {
  const [users, rosters] = await Promise.all([once(`users:${leagueId}`, () => getJson(`${SLEEPER}/league/${leagueId}/users`)), sleeperRosters(leagueId)]);
  const byUser = {};
  users.forEach(u => {
    const team = ((u.metadata || {}).team_name || '').trim();
    byUser[u.user_id] = team && team.toLowerCase() !== (u.display_name || '').toLowerCase() ? `${team} (${u.display_name})` : u.display_name;
  });
  const out = {};
  rosters.forEach(r => { out[r.roster_id] = byUser[r.owner_id] || `Team ${r.roster_id}`; });
  return out;
}

// One week of games as [{ a, as, b, bs }] with team labels
async function weekGames(lg, season, week) {
  if (lg.platform === 'fleaflicker') {
    const board = await getJson(`${FLEA}/FetchLeagueScoreboard?sport=NFL&league_id=${lg.id}&season=${season}&scoring_period=${week}`);
    return (board.games || []).filter(g => g.home && g.away).map(g => ({
      a: g.home.name, as: num((g.homeScore || {}).score), b: g.away.name, bs: num((g.awayScore || {}).score),
    }));
  }
  const [labels, matchups] = await Promise.all([sleeperLabels(lg.id), getJson(`${SLEEPER}/league/${lg.id}/matchups/${week}`)]);
  const pairs = {};
  matchups.forEach(m => { if (m.matchup_id) (pairs[m.matchup_id] = pairs[m.matchup_id] || []).push(m); });
  return Object.values(pairs).filter(p => p.length === 2).map(([x, y]) => ({
    a: labels[x.roster_id], as: Number(x.points) || 0, b: labels[y.roster_id], bs: Number(y.points) || 0,
  }));
}

function siteJson(env, file) {
  return once(`site:${file}`, () => getJson(new URL(file, env.SITE_URL).toString()).catch(() => null));
}

// Same rules as the site: the league's own FantasyCalc format, picks valued by their draft year
async function valueOf(env, leagueName) {
  const data = (await siteJson(env, 'ktc_values.json')) || {};
  const formats = data.formats || {};
  const fmtKey = Object.entries(data.league_formats || {})
    .find(([name]) => name.trim().toLowerCase() === String(leagueName || '').trim().toLowerCase());
  const players = (fmtKey && formats[fmtKey[1]] && formats[fmtKey[1]].players) || data.players || {};
  const norm = s => String(s).toLowerCase().replace(/[.']/g, '').replace(/\b(jr|sr|ii|iii|iv|v)\b/g, '').replace(/\s+/g, ' ').trim();
  const byNorm = {};
  Object.entries(players).forEach(([k, v]) => { byNorm[norm(k)] = v; });
  const picks = data.picks || {};
  const ord = r => (r === '1' ? '1st' : r === '2' ? '2nd' : r === '3' ? '3rd' : `${r}th`);
  const pickValue = (year, round) => {
    // Redraft formats have no picks; borrow the default (dynasty) table, then the nearest listed year
    const pools = [players, data.players || {}];
    for (const pool of pools) {
      const years = [...new Set(Object.keys(pool).filter(k => new RegExp(`^20\\d\\d ${ord(round)}( |$)`).test(k)).map(k => Number(k.slice(0, 4))))];
      if (!years.length) continue;
      const best = years.reduce((a, b) => (Math.abs(b - year) < Math.abs(a - year) ? b : a));
      const v = pool[`${best} ${ord(round)} (Mid)`] || pool[`${best} ${ord(round)}`];
      if (v) return v;
    }
    return picks[round] || 0;
  };
  return item => {
    const pick = item.match(/^(\d{4}) Round (\d+)/);
    if (pick) return pickValue(Number(pick[1]), pick[2]);
    const name = item.replace(/\s*\([^)]*\)\s*$/, '');
    return players[name] || byNorm[norm(name)] || 0;
  };
}

// ---------- trade alerts ----------
async function tradeAlerts(lg, state, env, say, dry) {
  const seenKey = `seen:${lg.id}`;
  const seen = (await env.BOT_KV.get(seenKey, 'json')) || null;
  const trades = lg.platform === 'fleaflicker' ? await fleaTrades(lg) : await sleeperTrades(lg, state, env);
  if (seen === null) {
    // First run for this league: remember what exists without announcing old trades
    if (!dry) await env.BOT_KV.put(seenKey, JSON.stringify(trades.map(t => t.id).slice(0, 300)));
    return;
  }
  const fresh = trades.filter(t => !seen.includes(t.id));
  if (!fresh.length) return;
  const value = await valueOf(env, lg.name);
  fresh.forEach(t => {
    const lines = t.sides.map(s => {
      const v = s.items.reduce((a, i) => a + value(i), 0);
      const items = s.items.length ? s.items.map(i => `• ${i}`).join('\n') : '• nothing';
      return { text: `**${s.team}** gets (value ${Math.round(v).toLocaleString()}):\n${items}`, v };
    });
    const top = [...lines].sort((x, y) => y.v - x.v);
    const swing = top.length > 1 && top[0].v ? ` Value swing: ${Math.round(top[0].v - top[1].v).toLocaleString()}.` : '';
    say(`🚨 **TRADE ALERT** • ${lg.name}\n\n${lines.map(l => l.text).join('\n\n')}\n\n${swing.trim()} ${env.SITE_URL}?tab=trades`);
  });
  if (!dry) await env.BOT_KV.put(seenKey, JSON.stringify([...fresh.map(t => t.id), ...seen].slice(0, 300)));
}

async function sleeperTrades(lg, state, env) {
  const meta = await siteJson(env, 'player_meta.json');
  const names = (meta && meta.ids) || {};
  const week = Math.max(1, Number(state.leg || state.week) || 1);
  const [labels, ...lists] = await Promise.all([
    sleeperLabels(lg.id),
    getJson(`${SLEEPER}/league/${lg.id}/transactions/${week}`),
    week > 1 ? getJson(`${SLEEPER}/league/${lg.id}/transactions/${week - 1}`) : Promise.resolve([]),
  ]);
  return lists.flat().filter(t => t.type === 'trade' && t.status === 'complete').map(t => ({
    id: String(t.transaction_id),
    sides: (t.roster_ids || []).map(rid => ({
      team: labels[rid] || `Team ${rid}`,
      items: [
        ...Object.entries(t.adds || {}).filter(([, r]) => r === rid).map(([pid]) => names[pid] || (/^[A-Z]{2,3}$/.test(pid) ? `${pid} (DEF)` : `Player ${pid}`)),
        ...(t.draft_picks || []).filter(p => p.owner_id === rid).map(p => `${p.season} Round ${p.round} Pick`),
      ],
    })),
  }));
}

async function fleaTrades(lg) {
  const data = await getJson(`${FLEA}/FetchTrades?sport=NFL&league_id=${lg.id}&filter=TRADES_COMPLETED`);
  return (data.trades || []).map(t => ({
    id: String(t.id),
    sides: (t.teams || []).map(s => ({
      team: (s.team || {}).name || 'Team',
      items: [
        ...(s.playersObtained || []).map(p => {
          const pro = p.proPlayer || (p.leaguePlayer || {}).proPlayer || p;
          return `${pro.nameFull || 'Player'} (${pro.position || ''})`;
        }),
        ...(s.picksObtained || []).map(pk => `${pk.season} Round ${((pk.slot || {}).round) || pk.round || 1} Pick`),
      ],
    })),
  }));
}

// ---------- weekly recap + gazette ----------
function gazetteKey(league, season) {
  return `gazette:${league}:${season}`;
}

// Facts for the latest week that has final scores (the NFL state may or may not have rolled over yet)
async function weeklyFacts(lg, season, stateWeek) {
  let week = stateWeek, games = await weekGames(lg, season, week);
  if (!games.some(g => g.as > 0 || g.bs > 0) && week > 1) { week--; games = await weekGames(lg, season, week); }
  if (!games.length || !games.every(g => g.as > 0 && g.bs > 0)) return null;

  const sides = games.flatMap(g => [{ t: g.a, s: g.as, o: g.b, os: g.bs }, { t: g.b, s: g.bs, o: g.a, os: g.as }]).sort((x, y) => y.s - x.s);
  const margins = games.map(g => ({ w: g.as >= g.bs ? g.a : g.b, l: g.as >= g.bs ? g.b : g.a, ws: Math.max(g.as, g.bs), ls: Math.min(g.as, g.bs) }))
    .map(m => ({ ...m, m: m.ws - m.ls })).sort((x, y) => y.m - x.m);
  const f = n => n.toFixed(2);
  const facts = [
    `🥊 High Score Belt: ${sides[0].t} (${f(sides[0].s)})`,
    `🚽 Toilet Bowl: ${sides[sides.length - 1].t} (${f(sides[sides.length - 1].s)})`,
    `🚜 Biggest Blowout: ${margins[0].w} over ${margins[0].l}, ${f(margins[0].ws)}–${f(margins[0].ls)}`,
    `😰 Nail-Biter: ${margins[margins.length - 1].w} over ${margins[margins.length - 1].l} by ${f(margins[margins.length - 1].m)}`,
  ];
  if (sides[1].s < sides[1].os) facts.push(`🥷 Robbed: ${sides[1].t} scored ${f(sides[1].s)} (2nd-most) and still lost`);
  sides.slice(-3).filter(x => x.s > x.os).forEach(x => facts.push(`🍀 Lucky Win: ${x.t} won with just ${f(x.s)}`));
  return { week, facts, scoreboard: games.map(g => `${g.a} ${f(g.as)} – ${f(g.bs)} ${g.b}`) };
}

async function weeklyRecap(lg, season, stateWeek, env, say) {
  const r = await weeklyFacts(lg, season, stateWeek);
  if (r) say(`📰 **${lg.name} • Week ${r.week} Recap**\n${r.facts.join('\n')}\n${env.SITE_URL}?tab=awardcenter`);
}

// Writes and posts one article per league per week, and says what it did (shown by /run).
// A dry run returns the article instead of storing or posting it.
// Worst case for one league: 4 data requests, 2 Claude attempts and 3 chat posts.
const GAZETTE_REQUESTS = 9;
async function weeklyGazette(lg, leagues, season, stateWeek, env, say, dry) {
  if (!env.ANTHROPIC_API_KEY) return 'skipped, no ANTHROPIC_API_KEY';
  // Marks a league as posted (or being written) for this week, so later slots and overlapping runs skip it
  const postedKey = `gazette-posted:${lg.name}:${season}:${stateWeek}`;
  if (!dry && await env.BOT_KV.get(postedKey)) return 'already posted this week';
  if (used + GAZETTE_REQUESTS > REQUEST_LIMIT) return 'left for the next run (request limit)';
  const r = await weeklyFacts(lg, season, stateWeek);
  if (!r) return 'scores not final yet';
  const key = gazetteKey(lg.name, season);
  const list = (await env.BOT_KV.get(key, 'json')) || [];
  // Already written from these final scores (e.g. stored but not yet posted); an article written
  // before the week finished gets rewritten
  const board = r.scoreboard.join('|');
  let saved = list.find(a => a.week === r.week && a.board === board);
  if (!saved) {
    if (!dry) await env.BOT_KV.put(postedKey, 'writing', { expirationTtl: 1800 });
    const angle = GAZETTE_ANGLES[(leagues.indexOf(lg) + r.week) % GAZETTE_ANGLES.length];
    const earlier = await recentGazettes(env, leagues, lg, season, r.week, list);
    const article = await writeGazette(env, lg.name, season, r.week, r.facts, r.scoreboard, angle, earlier).catch(e => {
      console.log(`gazette ${lg.name}: ${e.stack || e}`);
      return null;
    });
    if (!article) {
      if (!dry) await env.BOT_KV.delete(postedKey);
      return 'Claude returned no article, will retry next run';
    }
    if (dry) { say(`📰 ${lg.name} Week ${r.week} Gazette (dry run, not saved):\n${article}`); return 'written (dry run)'; }
    saved = { week: r.week, text: article, at: Date.now(), board };
    await env.BOT_KV.put(key, JSON.stringify([...list.filter(a => a.week !== r.week), saved]));
  } else if (dry) {
    say(`📰 ${lg.name} Week ${r.week} Gazette (dry run, already saved):\n${saved.text}`);
    return 'already written (dry run)';
  }
  const link = `${env.SITE_URL}?${new URLSearchParams({ tab: 'review', league: lg.name, season })}`;
  await post(env, `🗞️ **THE DYNASTY GAZETTE** • ${lg.name} Week ${r.week}\n\n${plainText(saved.text)}\n\nEvery issue: ${link}`);
  await env.BOT_KV.put(postedKey, 'posted', { expirationTtl: 8 * 24 * 3600 });
  return 'written and posted';
}

// The chats show plain text, so drop the Markdown the Gazette is written in (same rules as the site)
function plainText(md) {
  return String(md || '').replace(/\r/g, '')
    .replace(/^#{1,6}\s*/gm, '')
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/\*(\S[^*]*?)\*/g, '$1')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '$1 ($2)')
    .replace(/^\s*[-*]\s+/gm, '• ')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

// Each league gets a different angle each week (a league's index plus the week number, so no two
// leagues share one in the same week and a league's angle rotates). The angle changes the framing,
// not the voice.
const GAZETTE_ANGLES = [
  'a war correspondent filing a dispatch from the front lines of a massacre',
  'a nature documentary narrator watching the weak get eaten',
  'a police blotter and crime-scene report',
  'the obituary page, with eulogies for the dead rosters',
  'a courtroom: charges read, evidence presented, sentences handed down',
  'a trashy celebrity gossip column full of scandal and leaked texts',
  'an unhinged sports talk radio host taking calls',
  'a horror movie, with the losers as the idiots who split up',
  'a hostage negotiation and ransom note',
  'a doctor delivering terminal diagnoses at an underfunded hospital',
];

// This week's articles from the other leagues (written earlier in this run or an earlier slot) and
// this league's last two weeks, so jokes, insults and headlines aren't repeated
async function recentGazettes(env, leagues, lg, season, week, ownList) {
  const out = [];
  for (const other of leagues) {
    if (other === lg) continue;
    const list = (await env.BOT_KV.get(gazetteKey(other.name, season), 'json')) || [];
    const a = list.find(x => x.week === week);
    if (a) out.push(`${other.name}, week ${week}:\n${a.text}`);
  }
  ownList.filter(a => a.week < week && a.week >= week - 2).forEach(a => out.push(`${lg.name}, week ${a.week}:\n${a.text}`));
  return out;
}

async function writeGazette(env, league, season, week, facts, scoreboard, angle, earlier) {
  // Many managers play in several leagues, so a recycled insult lands on the same people twice
  const avoid = earlier.length
    ? `\n\nThe same friends read every league's Gazette. These columns already ran; do not reuse their jokes, insults, ` +
      `comparisons, metaphors, headline structure or punchlines. Every burn here must be new:\n\n${earlier.join('\n\n---\n\n')}`
    : '';
  // One retry at most, and through counted() so the request budget stays honest
  const client = new Anthropic({ apiKey: env.ANTHROPIC_API_KEY, maxRetries: 1, fetch: counted });
  const response = await client.beta.messages.create({
    model: 'claude-opus-5-5',
    max_tokens: 4000,
    output_config: { effort: 'low' },
    betas: ['server-side-fallback-2026-07-01'],
    fallbacks: 'default',
    system: 'You write "The Dynasty Gazette", a weekly tabloid column for a group of friends in a fantasy football league. ' +
      'They have a dark, twisted sense of humor and want it rude and crude: swear freely, be filthy, use gallows humor and ' +
      'absurd, disturbing comparisons, and never soften a burn. Write in Markdown: a bold headline, then 3-4 short paragraphs ' +
      '(about 250 words). Savage the losers, grudgingly hype the winners, and only use the facts given. No player stats beyond ' +
      'what is listed. Aim the cruelty at their fantasy football, not at who they are: no slurs, and no jokes about anyone\'s ' +
      'real race, religion, sexuality, gender, disability, appearance, health or family.',
    messages: [{
      role: 'user',
      content: `League: ${league}\nSeason ${season}, Week ${week}\n\nFinal scores:\n${scoreboard.join('\n')}\n\nWeekly awards:\n${facts.join('\n')}` +
        `\n\nThis week's angle: write it as ${angle}. Keep the Gazette's voice; the angle is the framing.${avoid}`,
    }],
  });
  if (response.stop_reason === 'refusal') return null;
  return response.content.filter(b => b.type === 'text').map(b => b.text).join('\n').trim() || null;
}

// ---------- matchup previews ----------
async function previews(lg, season, week, say) {
  const games = await weekGames(lg, season, week);
  if (!games.length || games.some(g => g.as > 0 || g.bs > 0)) return; // already underway or no schedule
  // Season averages from the standings (one request), with a typical weekly spread of 25 points
  const avg = {};
  if (lg.platform === 'fleaflicker') {
    const data = await getJson(`${FLEA}/FetchLeagueStandings?sport=NFL&league_id=${lg.id}&season=${season}`);
    (data.divisions || []).flatMap(d => d.teams || []).concat(data.teams || []).forEach(t => {
      const rec = t.recordOverall || {};
      const gp = num(rec.wins) + num(rec.losses) + num(rec.ties);
      if (gp) avg[t.name] = num(t.pointsFor ?? rec.pointsFor) / gp;
    });
  } else {
    const [labels, rosters] = await Promise.all([sleeperLabels(lg.id), sleeperRosters(lg.id)]);
    rosters.forEach(r => {
      const s = r.settings || {};
      const gp = (s.wins || 0) + (s.losses || 0) + (s.ties || 0);
      if (gp) avg[labels[r.roster_id]] = ((s.fpts || 0) + (s.fpts_decimal || 0) / 100) / gp;
    });
  }
  const SD = 25;
  const lines = games.map(g => {
    const a = avg[g.a] || 0, b = avg[g.b] || 0;
    const z = (a - b) / Math.sqrt(2 * SD * SD);
    const pA = 1 / (1 + Math.exp(-1.702 * z)); // logistic approximation of the normal CDF
    const fav = pA >= 0.5 ? g.a : g.b;
    return `• ${g.a} (${a.toFixed(1)} avg) vs ${g.b} (${b.toFixed(1)} avg) → **${fav}** ${Math.round(Math.max(pA, 1 - pA) * 100)}%`;
  });
  say(`🔮 **${lg.name} • Week ${week} Preview**\n${lines.join('\n')}`);
}

// ---------- posting ----------
// Separate messages go out about 30 seconds apart; the parts of one long message follow 3 seconds
// apart so they stay together and in order.
const MESSAGE_GAP_MS = 30000;
const PART_GAP_MS = 3000;
let lastPost = 0;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function send(gap, url, body) {
  const wait = lastPost + gap - Date.now();
  if (lastPost && wait > 0) await sleep(wait);
  await counted(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    .catch(e => console.log(`post failed: ${e}`));
  lastPost = Date.now();
}

async function post(env, text) {
  // CHAT_POSTING = "off" in wrangler.toml pauses the chat without stopping the Gazette for the site
  if (String(env.CHAT_POSTING || 'on').toLowerCase() === 'off') return;
  // Discord and GroupMe each get the message; the first part waits out the gap from the last message
  if (env.DISCORD_WEBHOOK_URL) {
    let gap = MESSAGE_GAP_MS;
    for (const chunk of split(text, 1900)) { await send(gap, env.DISCORD_WEBHOOK_URL, { content: chunk }); gap = PART_GAP_MS; }
  }
  if (env.GROUPME_BOT_ID) {
    // GroupMe has no Markdown and a 1000-character limit
    let gap = env.DISCORD_WEBHOOK_URL ? 0 : MESSAGE_GAP_MS;
    for (const chunk of split(text.replace(/\*\*|_/g, ''), 950)) {
      await send(gap, 'https://api.groupme.com/v3/bots/post', { bot_id: env.GROUPME_BOT_ID, text: chunk });
      gap = PART_GAP_MS;
    }
  }
}

// Splits at line breaks, and inside a line too long to fit on its own (at a space where possible)
function split(text, max) {
  const out = [];
  let cur = '';
  text.split('\n').forEach(line => {
    while (line.length > max) {
      const cut = line.lastIndexOf(' ', max) > max / 2 ? line.lastIndexOf(' ', max) : max;
      if (cur) { out.push(cur); cur = ''; }
      out.push(line.slice(0, cut));
      line = line.slice(cut).trimStart();
    }
    if ((cur + '\n' + line).length > max && cur) { out.push(cur); cur = line; }
    else cur = cur ? `${cur}\n${line}` : line;
  });
  if (cur) out.push(cur);
  return out;
}
