// Cloudflare Worker: read-only CORS proxy for the Fleaflicker API.
//
// Fleaflicker's API sends no CORS headers, so a browser on the Dynasty Hub site can't call it
// directly. This worker forwards a small allow-list of GET calls, caches them for 30 seconds
// and adds CORS headers. The deploy-workers workflow deploys it; its URL is FLEA_PROXY in index.html.
//
// Locked down on purpose: only the endpoints below and the Fleaflicker leagues in leagues.json
// (FLEA_LEAGUES in wrangler.toml), numeric params only.

const ALLOWED_ENDPOINTS = new Set(['FetchLeagueScoreboard', 'FetchLeagueBoxscore', 'FetchLeagueStandings']);
// Origins allowed to read responses. Add a custom domain here if the site moves.
const ALLOWED_ORIGINS = ['https://605tokenpodcast-ctrl.github.io'];
const PASS_PARAMS = ['league_id', 'season', 'scoring_period', 'fantasy_game_id'];
const CACHE_SECONDS = 30;
const ERROR_CACHE_SECONDS = 10; // brief, so an upstream outage isn't hit by every open tab each minute

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
    const allowedLeagues = new Set(String(env.FLEA_LEAGUES || '165455').split(',').map(s => s.trim()));
    if (!ALLOWED_ENDPOINTS.has(endpoint) || !allowedLeagues.has(url.searchParams.get('league_id'))) {
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
    const errorKey = new Request(`${upstream.toString()}&_upstream_error=1`);
    let res = await cache.match(cacheKey);
    if (!res) {
      const err = await cache.match(errorKey);
      if (err) res = new Response(err.body, { status: Number(err.headers.get('X-Upstream-Status')) || 502, headers: { 'Content-Type': 'application/json' } });
    }
    if (!res) {
      const r = await fetch(upstream.toString(), { headers: { 'User-Agent': 'dynasty-hub fleaflicker proxy' } });
      res = new Response(r.body, {
        status: r.status,
        headers: { 'Content-Type': 'application/json', 'Cache-Control': `public, max-age=${r.ok ? CACHE_SECONDS : ERROR_CACHE_SECONDS}` },
      });
      // The Cache API stores only 200s, so a failed call is cached under a separate key as a 200
      // carrying the real status in a header, and turned back into the error when read
      if (r.ok) ctx.waitUntil(cache.put(cacheKey, res.clone()));
      else ctx.waitUntil(cache.put(errorKey, new Response(await res.clone().text(), {
        headers: { 'Content-Type': 'application/json', 'Cache-Control': `public, max-age=${ERROR_CACHE_SECONDS}`, 'X-Upstream-Status': String(r.status) },
      })));
    }
    const out = new Response(res.body, res);
    Object.entries(cors).forEach(([k, v]) => out.headers.set(k, v));
    return out;
  },
};
