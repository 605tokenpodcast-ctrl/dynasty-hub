// Cloudflare Worker: read-only CORS proxy for the Fleaflicker API.
//
// Fleaflicker's API sends no CORS headers, so a browser on the Dynasty Hub site can't call it
// directly. This worker forwards a small allow-list of GET calls, caches them for 30 seconds
// and adds CORS headers. The deploy-workers workflow deploys it; its URL is FLEA_PROXY in index.html.
//
// Locked down on purpose: only the endpoints below and the Fleaflicker leagues in leagues.json
// (FLEA_LEAGUES in wrangler.toml), numeric params only.

const ALLOWED_ENDPOINTS = new Set(['FetchLeagueScoreboard', 'FetchLeagueBoxscore', 'FetchLeagueStandings']);
const PASS_PARAMS = ['league_id', 'season', 'scoring_period', 'fantasy_game_id'];
const CACHE_SECONDS = 30;
const ERROR_CACHE_SECONDS = 10; // brief, so an upstream outage isn't hit by every open tab each minute

// Cloudflare ignores the Cache API on *.workers.dev addresses, so responses are also kept in this
// worker's memory: requests reaching the same running copy share one upstream call per URL.
const memory = new Map(); // upstream url -> { expires, res: Promise<{ status, text }> }

export default {
  async fetch(request, env, ctx) {
    // Origins allowed to read responses (ALLOWED_ORIGINS in wrangler.toml)
    const origins = String(env.ALLOWED_ORIGINS || 'https://605tokenpodcast-ctrl.github.io').split(',').map(s => s.trim()).filter(Boolean);
    const origin = request.headers.get('Origin') || '';
    const cors = {
      'Access-Control-Allow-Origin': origins.includes(origin) ? origin : origins[0],
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

    const { status, text } = await upstreamResponse(upstream.toString(), ctx);
    return new Response(text, {
      status,
      headers: { ...cors, 'Content-Type': 'application/json', 'Cache-Control': `public, max-age=${status === 200 ? CACHE_SECONDS : ERROR_CACHE_SECONDS}` },
    });
  },
};

function upstreamResponse(url, ctx) {
  const now = Date.now();
  const hit = memory.get(url);
  if (hit && hit.expires > now) return hit.res;
  const res = fetchUpstream(url, ctx);
  for (const [k, v] of memory) if (v.expires <= now) memory.delete(k);
  memory.set(url, { expires: now + CACHE_SECONDS * 1000, res });
  // Errors are kept only briefly
  res.then(r => { if (r.status !== 200) memory.set(url, { expires: Date.now() + ERROR_CACHE_SECONDS * 1000, res }); },
    () => memory.delete(url));
  return res;
}

async function fetchUpstream(url, ctx) {
  const cache = caches.default;
  const cacheKey = new Request(url);
  const errorKey = new Request(`${url}&_upstream_error=1`);
  const hit = await cache.match(cacheKey);
  if (hit) return { status: 200, text: await hit.text() };
  const err = await cache.match(errorKey);
  if (err) return { status: Number(err.headers.get('X-Upstream-Status')) || 502, text: await err.text() };

  const r = await fetch(url, { headers: { 'User-Agent': 'dynasty-hub fleaflicker proxy' } });
  const text = await r.text();
  const status = r.ok ? 200 : r.status;
  // The Cache API stores only 200s, so a failed call is cached under a separate key as a 200
  // carrying the real status in a header, and turned back into the error when read
  ctx.waitUntil(cache.put(r.ok ? cacheKey : errorKey, new Response(text, {
    headers: {
      'Content-Type': 'application/json',
      'Cache-Control': `public, max-age=${r.ok ? CACHE_SECONDS : ERROR_CACHE_SECONDS}`,
      ...(r.ok ? {} : { 'X-Upstream-Status': String(r.status) }),
    },
  })));
  return { status, text };
}
