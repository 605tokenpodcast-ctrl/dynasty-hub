// Cloudflare Worker: shareable award cards.
//
//   GET /card?icon=🥊&title=High Score Belt&name=Kronik&value=167.54 pts&detail=...  -> 1200x630 PNG
//   GET /share?<same params>  -> a tiny page whose link preview (Discord, iMessage, GroupMe...) is the
//                                card, and which sends people on to the site's Awards Center
//
// The site's "📤 Share card" links point at /share (AWARD_CARD_ENDPOINT in index.html).
// Text comes from the link itself, so every field is length-limited and escaped.
import { ImageResponse } from 'workers-og';

const LIMITS = { icon: 8, title: 60, name: 60, value: 40, detail: 160 };

function params(url) {
  const out = {};
  Object.entries(LIMITS).forEach(([k, max]) => { out[k] = [...String(url.searchParams.get(k) || '')].slice(0, max).join(''); });
  if (!out.icon) out.icon = '🏆';
  return out;
}

const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function cardHtml(p) {
  return `
    <div style="display:flex;flex-direction:column;justify-content:space-between;width:1200px;height:630px;padding:64px;background:linear-gradient(135deg,#0f172a 0%,#1e293b 100%);color:#f1f5f9;font-family:sans-serif;">
      <div style="display:flex;align-items:center;font-size:40px;color:#94a3b8;">
        <span style="margin-right:20px;">🏈</span><span>Multi-League Dynasty Hub</span>
      </div>
      <div style="display:flex;flex-direction:column;">
        <div style="display:flex;align-items:center;font-size:64px;font-weight:700;">
          <span style="margin-right:24px;">${esc(p.icon)}</span><span>${esc(p.title)}</span>
        </div>
        <div style="display:flex;font-size:96px;font-weight:800;color:#3b82f6;margin-top:24px;">${esc(p.name)}</div>
        <div style="display:flex;font-size:56px;font-weight:700;color:#34d399;margin-top:8px;">${esc(p.value)}</div>
      </div>
      <div style="display:flex;font-size:32px;color:#cbd5e1;">${esc(p.detail)}</div>
    </div>`;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const p = params(url);

    if (url.pathname === '/card') {
      return new ImageResponse(cardHtml(p), {
        width: 1200,
        height: 630,
        emoji: 'twemoji',
        headers: { 'Cache-Control': 'public, max-age=86400' },
      });
    }

    if (url.pathname === '/share') {
      const card = new URL('/card', url);
      Object.entries(p).forEach(([k, v]) => card.searchParams.set(k, v));
      const site = new URL(env.SITE_URL);
      site.searchParams.set('tab', 'awardcenter');
      const title = `${p.icon} ${p.title}: ${p.name}`;
      const desc = `${p.value}${p.detail ? ' • ' + p.detail : ''}`;
      return new Response(`<!doctype html>
<html><head><meta charset="utf-8">
<title>${esc(title)}</title>
<meta property="og:title" content="${esc(title)}">
<meta property="og:description" content="${esc(desc)}">
<meta property="og:image" content="${esc(card.toString())}">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta http-equiv="refresh" content="0; url=${esc(site.toString())}">
</head><body style="background:#0f172a;color:#f1f5f9;font-family:sans-serif;text-align:center;padding:2rem">
<img src="${esc(card.toString())}" alt="${esc(title)}" style="max-width:100%;border-radius:12px">
<p><a style="color:#3b82f6" href="${esc(site.toString())}">Open the Dynasty Hub</a></p>
</body></html>`, { headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'public, max-age=3600' } });
    }

    return new Response('Dynasty Hub award cards: /card or /share', { headers: { 'Content-Type': 'text/plain' } });
  },
};
