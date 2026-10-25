// Cloudflare Worker: one cached snapshot of live scores for every league.
//
// Without it, every visitor's browser calls Sleeper (users + rosters + matchups per league) and the
// Fleaflicker proxy (scoreboard + one boxscore per game) on its own. This worker makes those calls
// at most once a minute per Cloudflare location and returns one small JSON:
//
//   GET /?season=2026&week=8
//   {
//     ts,
//     sleeper: { [leagueId]: { labels: { rosterId: "Team (user)" }, matchups: [{ roster_id, matchup_id, points, starters, players_points }] } },
//     flea:    { [leagueId]: { games: [{ id, home, away, homeScore, awayScore, projected: { home, away } }] } }
//   }
//
// The site (LIVE_SCORES_ENDPOINT in index.html) uses it first and falls back to direct calls.
// Leagues and allowed origins are vars in wrangler.toml.

const CACHE_SECONDS = 60;

export default {
  async fetch(request, env, ctx) {
    const origins = String(env.ALLOWED_ORIGINS || '').split(',').map(s => s.trim()).filter(Boolean);
    const origin = request.headers.get('Origin') || '';
    const cors = {
      'Access-Control-Allow-Origin': origins.includes(origin) ? origin : (origins[0] || '*'),
      'Access-Control-Allow-Methods': 'GET, OPTIONS',
      'Vary': 'Origin',
    };
    if (request.method === 'OPTIONS') return new Response(null, { headers: cors });
    if (request.method !== 'GET') return new Response('Method not allowed', { status: 405, headers: cors });

    const url = new URL(request.url);
    const season = url.searchParams.get('season') || '';
    const week = url.searchParams.get('week') || '';
    if (!/^\d{4}$/.test(season) || !/^\d{1,2}$/.test(week)) return new Response('season and week required', { status: 400, headers: cors });

    const cache = caches.default;
    const cacheKey = new Request(`https://live-scores.cache/${season}/${week}`);
    let res = await cache.match(cacheKey);
    if (!res) {
      const body = await buildSnapshot(env, season, week);
      res = new Response(JSON.stringify(body), {
        headers: { 'Content-Type': 'application/json', 'Cache-Control': `public, max-age=${CACHE_SECONDS}` },
      });
      ctx.waitUntil(cache.put(cacheKey, res.clone()));
    }
    const out = new Response(res.body, res);
    Object.entries(cors).forEach(([k, v]) => out.headers.set(k, v));
    return out;
  },
};

const list = s => String(s || '').split(',').map(x => x.trim()).filter(Boolean);

async function getJson(url) {
  const r = await fetch(url, { headers: { 'User-Agent': 'dynasty-hub live scores' } });
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.json();
}

async function buildSnapshot(env, season, week) {
  const out = { ts: Date.now(), season: Number(season), week: Number(week), sleeper: {}, flea: {} };
  await Promise.all([
    ...list(env.SLEEPER_LEAGUES).map(id => sleeperLeague(id, week).then(v => { out.sleeper[id] = v; }).catch(() => {})),
    ...list(env.FLEA_LEAGUES).map(id => fleaLeague(id, season, week).then(v => { out.flea[id] = v; }).catch(() => {})),
  ]);
  return out;
}

async function sleeperLeague(id, week) {
  const base = `https://api.sleeper.app/v1/league/${id}`;
  const [users, rosters, matchups] = await Promise.all([getJson(`${base}/users`), getJson(`${base}/rosters`), getJson(`${base}/matchups/${week}`)]);
  const byUser = {};
  users.forEach(u => {
    const display = String(u.display_name || 'Unknown').trim();
    const team = String((u.metadata || {}).team_name || '').trim();
    byUser[u.user_id] = team && team.toLowerCase() !== display.toLowerCase() ? `${team} (${display})` : display;
  });
  const labels = {};
  rosters.forEach(r => { labels[r.roster_id] = byUser[r.owner_id] || `Team ${r.roster_id}`; });
  return {
    labels,
    matchups: matchups.map(m => ({ roster_id: m.roster_id, matchup_id: m.matchup_id, points: m.points, starters: m.starters, players_points: m.players_points })),
  };
}

async function fleaLeague(id, season, week) {
  const base = `https://www.fleaflicker.com/api`;
  const qs = `sport=NFL&league_id=${id}&season=${season}&scoring_period=${week}`;
  const board = await getJson(`${base}/FetchLeagueScoreboard?${qs}`);
  const games = board.games || [];
  const boxes = await Promise.allSettled(games.map(g => getJson(`${base}/FetchLeagueBoxscore?${qs}&fantasy_game_id=${g.id}`)));
  return {
    games: games.map((g, i) => {
      const box = boxes[i].status === 'fulfilled' ? (boxes[i].value.game || {}) : {};
      return {
        id: g.id, home: g.home, away: g.away, homeScore: g.homeScore, awayScore: g.awayScore,
        projected: { home: (box.homeScore || {}).projected, away: (box.awayScore || {}).projected },
      };
    }),
  };
}
