// Cloudflare Worker: read-only CORS proxy for the Fleaflicker API.
//
// Fleaflicker's API sends no CORS headers, so a browser on the Dynasty Hub site can't call it
// directly. This worker forwards a small allow-list of GET calls, caches them for 30 seconds
// and adds CORS headers. Deploy it (Workers & Pages -> Create -> paste this file), then put its
// URL into FLEA_PROXY in index.html.
//
// Locked down on purpose: only the endpoints and league IDs below, numeric params only.

const ALLOWED_ENDPOINTS = new Set(['FetchLeagueScoreboard', 'FetchLeagueBoxscore', 'FetchLeagueStandings']);
const ALLOWED_LEAGUES = new Set(['165455']); // Branden's League
// Origins allowed to read responses. Add a custom domain here if the site moves.
const ALLOWED_ORIGINS = ['https://605tokenpodcast-ctrl.github.io'];
const PASS_PARAMS = ['league_id', 'season', 'scoring_period', 'fantasy_game_id'];
const CACHE_SECONDS = 30;

export default {
  async fetch(request, env, ctx) {
    const origin = request.headers.get('Origin') || '';
    const cors = {
      'Access-Control-Allow-Origin': ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0],
      'Access-Control-Allow-Methods': 'GET, OPTIONS',
      'Vary': 'Origin',
    };
    if (request.method === 'OPTIONS') return new Response(null, { headers: cors });
    if (request.method !== 'GET') return new Response('Method not allowed', { status: 405, headers: cors });

    const url = new URL(request.url);
    const endpoint = url.searchParams.get('endpoint');
    if (!ALLOWED_ENDPOINTS.has(endpoint) || !ALLOWED_LEAGUES.has(url.searchParams.get('league_id'))) {
      return new Response('Not allowed', { status: 403, headers: cors });
    }

    const upstream = new URL(`https://www.fleaflicker.com/api/${endpoint}`);
    upstream.searchParams.set('sport', 'NFL');
    for (const key of PASS_PARAMS) {
      const value = url.searchParams.get(key);
      if (value === null || value === '') continue;
      if (!/^\d+$/.test(value)) return new Response(`Bad ${key}`, { status: 400, headers: cors });
      upstream.searchParams.set(key, value);
    }

    const cache = caches.default;
    const cacheKey = new Request(upstream.toString());
    let res = await cache.match(cacheKey);
    if (!res) {
      const r = await fetch(upstream.toString(), { headers: { 'User-Agent': 'dynasty-hub fleaflicker proxy' } });
      res = new Response(r.body, {
        status: r.status,
        headers: { 'Content-Type': 'application/json', 'Cache-Control': `public, max-age=${CACHE_SECONDS}` },
      });
      if (r.ok) ctx.waitUntil(cache.put(cacheKey, res.clone()));
    }
    const out = new Response(res.body, res);
    Object.entries(cors).forEach(([k, v]) => out.headers.set(k, v));
    return out;
  },
};
