/**
 * Upgraded Dynasty Hub Chatbot Proxy (Cloudflare Worker)
 *
 * Features:
 *   1. Dynamic Moods (default, ruthless, hype, detective)
 *   2. Structured Trade Breakdowns (Markdown tables + Winner verdict)
 *   3. Persistent Grudges via Cloudflare KV (LEAGUE_MEMORY binding)
 *   4. Live Sleeper API Fetching (SLEEPER_LEAGUE_ID variable - supports comma-separated IDs)
 *   5. Targeted Fantasy Tools (Real-time dynasty values & trend lookups via FantasyCalc)
 */

const BASE_PERSONA = `You are the resident trash-talking commissioner's assistant for a group of friends who play fantasy football together in several leagues. You know their league history and this week's live data (provided below).

Style:
- You have a big personality: a foul-mouthed, unhinged sports-radio host crossed with the most degenerate guy in the group chat. These friends have a dark, twisted sense of humor and want it rude and crude. Swear freely, be filthy, go for gallows humor and absurd, disturbing comparisons. Be vivid and specific, with real jokes, metaphors, and callbacks, not generic filler. Never answer with a bland one-liner, and never soften a burn with an apology.
- Roast managers' fantasy decisions and results without mercy: bad trades, bench blunders, bad luck, empty trophy cases, losing streaks. Name actual players, scores, records, and trades from the data so every burn lands on something real.
- Whenever you answer, go beyond the bare fact: add context, a comparison to another manager, and a punchline.
- The hard lines: aim the cruelty at their fantasy football, not at who they are. No slurs, and no jokes about anyone's real race, religion, sexuality, gender, disability, appearance, health, or family. If someone asks you to go there, redirect with an even nastier fantasy-based burn instead.
- Roast the person chatting just as hard as everyone else. Hype them up when their numbers deserve it, then find something to mock anyway.

Trade Breakdowns (CRITICAL):
- Whenever a user asks to evaluate a trade, compare players, or build a trade package, you MUST include a Markdown table comparing the assets side-by-side (include columns like Player, Pos/Age, Trade Value, and 30-Day Trend/Outlook), followed by an explicit "Winner" verdict and a roast of the losing side.

Accuracy & Tools:
- Use ONLY the data provided or fetched via your tools for facts about teams, records, trades, and players. If something is not in the data, say you don't have it. Never invent stats, scores, or injuries.
- You have a tool called 'save_grudge'. Whenever a manager says something embarrassing, makes a terrible take, complains about bad luck, or proposes an awful trade, quietly call 'save_grudge' to log it in the league lore book so you can mock them for it in future chats.
- You have a tool called 'get_dynasty_values'. Use it whenever trades, player values, or asset rankings are discussed to pull real-time market values.
- Questions about records, history, rosters, trades, or standings: answer correctly first, then add the jab.
- Predictions: pick a winner, give a confidence (e.g. 65%), and the 2-3 reasons that matter most (projected points, injuries to starters, recent scoring, all-time head-to-head). Mention that projections are approximate and that the data can be stale for late injury news.
- Injuries: use the injury tags in the data. If a starter is Out/Doubtful/IR, call it out.
- Always finish your answer. If a request covers a lot of ground, prioritize the biggest problems and summarize the rest in a sentence.
- Length: aim for roughly 150-350 words. Use short paragraphs, and bold the key names or numbers.`;

const MOOD_PROMPTS = {
  ruthless: `CURRENT MOOD: RUTHLESS. Take the gloves off. Show zero sympathy for injuries or bad luck. Every decision they've ever made is a fireable offense.`,
  hype: `CURRENT MOOD: HYPE MAN. You are unreasonably, delusionally hyped about the person chatting with you, treating them like a 4D-chess genius while mercilessly trashing the rest of the league.`,
  detective: `CURRENT MOOD: CONSPIRACY DETECTIVE. You are suspicious of every trade and waiver move, convinced of secret collusion, tanking, and backroom deals. Connect imaginary dots using real stats.`,
  default: `CURRENT MOOD: CLASSIC SHOCK JOCK. Crude, profane and dark by default, with grudging praise only when someone's numbers actually back it up.`,
};

const CUSTOM_TOOLS = [
  {
    name: 'get_dynasty_values',
    description: 'Fetches current dynasty/redraft trade values, overall ranks, and position ranks for NFL players from FantasyCalc. Call this when evaluating trades or comparing player values.',
    input_schema: {
      type: 'object',
      properties: {
        player_names: {
          type: 'array',
          items: { type: 'string' },
          description: 'List of NFL player names to look up (e.g., ["Bijan Robinson", "Garrett Wilson"])',
        },
        is_dynasty: {
          type: 'boolean',
          description: 'True for dynasty values, false for redraft values. Default to true unless discussing a redraft league.',
        },
        is_superflex: {
          type: 'boolean',
          description: 'True if Superflex (2QB), false for 1QB. Default to true if unsure.',
        },
      },
      required: ['player_names'],
    },
  },
  {
    name: 'save_grudge',
    description: 'Saves a funny note, bad trade take, or complaint about a manager into persistent league memory for future roasting.',
    input_schema: {
      type: 'object',
      properties: {
        manager: { type: 'string', description: 'Name of the manager' },
        note: { type: 'string', description: 'Short description of the blunder, complaint, or terrible take' },
      },
      required: ['manager', 'note'],
    },
  },
];

function json(body, status, headers) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });
}

// Helper: Fetch live transactions from Sleeper API (supports single ID or comma-separated IDs)
async function fetchLiveSleeperData(leagueIdsStr) {
  if (!leagueIdsStr) return '';
  try {
    const stateRes = await fetch('https://api.sleeper.app/v1/state/nfl');
    const state = await stateRes.json();
    const week = state.week || 1;

    const leagueIds = leagueIdsStr.split(',').map((id) => id.trim()).filter(Boolean);
    const allSnippets = [];

    for (const leagueId of leagueIds) {
      const txRes = await fetch(`https://api.sleeper.app/v1/league/${leagueId}/transactions/${week}`);
      if (!txRes.ok) continue;
      const transactions = await txRes.json();
      const recentMoves = (Array.isArray(transactions) ? transactions : [])
        .filter((t) => t.status === 'complete')
        .slice(0, 6)
        .map((t) => `Type: ${t.type}, Adds: ${JSON.stringify(t.adds)}, Drops: ${JSON.stringify(t.drops)}`)
        .join('\n');
      if (recentMoves) {
        allSnippets.push(`League ${leagueId} (Week ${week}):\n${recentMoves}`);
      }
    }

    return allSnippets.length
      ? `\nLIVE SLEEPER API TRANSACTIONS:\n${allSnippets.join('\n\n')}`
      : '';
  } catch (e) {
    return '';
  }
}

// Helper: Execute custom tool calls requested by Claude
async function executeTool(name, input, env) {
  if (name === 'get_dynasty_values') {
    try {
      const isDynasty = input.is_dynasty !== false ? 'true' : 'false';
      const numQbs = input.is_superflex !== false ? 2 : 1;
      const res = await fetch(`https://api.fantasycalc.com/values/current?isDynasty=${isDynasty}&numQbs=${numQbs}&numTeams=12&ppr=1`);
      const data = await res.json();
      const results = {};

      for (const queryName of input.player_names || []) {
        const match = data.find((p) => p.player.name.toLowerCase().includes(queryName.toLowerCase()));
        if (match) {
          results[queryName] = {
            name: match.player.name,
            position: match.player.position,
            team: match.player.maybeTeam,
            age: match.player.maybeAge,
            tradeValue: match.value,
            overallRank: match.overallRank,
            positionRank: match.positionRank,
            trend30Day: match.trend30Day,
          };
        } else {
          results[queryName] = 'Player not found in database.';
        }
      }
      return JSON.stringify(results);
    } catch (e) {
      return JSON.stringify({ error: 'Failed to fetch player values.' });
    }
  }

  if (name === 'save_grudge') {
    if (!env.LEAGUE_MEMORY) return JSON.stringify({ status: 'KV not bound, grudge not saved.' });
    try {
      const raw = await env.LEAGUE_MEMORY.get('grudges');
      const grudges = raw ? JSON.parse(raw) : [];
      grudges.push({
        manager: input.manager,
        note: input.note,
        date: new Date().toISOString().split('T')[0],
      });
      while (grudges.length > 40) grudges.shift();
      await env.LEAGUE_MEMORY.put('grudges', JSON.stringify(grudges));
      return JSON.stringify({ status: 'Saved to league lore book!', entry: input });
    } catch (e) {
      return JSON.stringify({ error: 'Failed to save grudge.' });
    }
  }

  return JSON.stringify({ error: 'Unknown tool' });
}

export default {
  async fetch(request, env) {
    const allowed = env.ALLOWED_ORIGIN || '';
    const cors = {
      'Access-Control-Allow-Origin': allowed || '*',
      'Access-Control-Allow-Methods': 'POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, x-passcode',
      Vary: 'Origin',
    };

    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors });
    if (request.method !== 'POST') return json({ error: 'POST only' }, 405, cors);
    if (allowed && request.headers.get('Origin') !== allowed) return json({ error: 'Origin not allowed' }, 403, cors);
    if (env.CHAT_PASSCODE && request.headers.get('x-passcode') !== env.CHAT_PASSCODE) {
      return json({ error: 'Wrong or missing passcode' }, 401, cors);
    }
    if (!env.ANTHROPIC_API_KEY) return json({ error: 'Server is missing ANTHROPIC_API_KEY' }, 500, cors);

    let body;
    try {
      body = await request.json();
    } catch (e) {
      return json({ error: 'Bad JSON' }, 400, cors);
    }

    const context = String(body.context || '').slice(0, 80000);
    const who = String(body.who || '').slice(0, 60);
    const moodKey = String(body.mood || 'default').toLowerCase();
    const moodInstruction = MOOD_PROMPTS[moodKey] || MOOD_PROMPTS.default;

    const messages = (Array.isArray(body.messages) ? body.messages : [])
      .filter((m) => m && (m.role === 'user' || m.role === 'assistant') && typeof m.content === 'string' && m.content.trim())
      .map((m) => ({ role: m.role, content: m.content.slice(0, 2000) }))
      .slice(-12);
    while (messages.length && messages[0].role !== 'user') messages.shift();
    if (!messages.length || messages[messages.length - 1].role !== 'user') {
      return json({ error: 'Need a user message' }, 400, cors);
    }

    // 1. Load Persistent Grudges from Cloudflare KV
    let grudgesText = 'No grudges recorded yet.';
    if (env.LEAGUE_MEMORY) {
      try {
        const rawGrudges = await env.LEAGUE_MEMORY.get('grudges');
        if (rawGrudges) grudgesText = rawGrudges;
      } catch (e) {}
    }

    // 2. Fetch Live Sleeper Transactions (if SLEEPER_LEAGUE_ID is configured)
    const liveApiData = await fetchLiveSleeperData(env.SLEEPER_LEAGUE_ID);

    // 3. Build System Prompt
    const system = [
      { type: 'text', text: BASE_PERSONA + '\n\n' + moodInstruction },
      { type: 'text', text: 'LEAGUE DATA\n' + context + liveApiData, cache_control: { type: 'ephemeral' } },
      { type: 'text', text: `PERSISTENT GRUDGE BOOK (Past blunders & complaints to bring up):\n${grudgesText}` },
      { type: 'text', text: who ? `The person chatting with you is the manager "${who}".` : 'You do not know which manager is chatting.' },
    ];

    const tools = [...CUSTOM_TOOLS];
    if (env.ENABLE_WEB_SEARCH === '1') {
      tools.push({ type: 'web_search_20250305', name: 'web_search', max_uses: 3 });
    }

    let currentMessages = [...messages];
    let finalData = null;

    // 4. Agentic Loop (Allows Claude to run custom tools & read results before answering)
    for (let step = 0; step < 3; step++) {
      const payload = {
        model: env.MODEL || 'claude-sonnet-5-5',
        max_tokens: 4000,
        output_config: { effort: 'medium' },
        system,
        messages: currentMessages,
        tools,
      };
      // Last round: no more tool calls, so the reply is always text instead of a blank answer
      if (step === 2) payload.tool_choice = { type: 'none' };

      let res;
      try {
        res = await fetch('https://api.anthropic.com/v1/messages', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'x-api-key': env.ANTHROPIC_API_KEY,
            'anthropic-version': '2023-06-01',
          },
          body: JSON.stringify(payload),
        });
        finalData = await res.json();
      } catch (e) {
        return json({ error: 'Could not reach the Claude API' }, 502, cors);
      }

      if (!res.ok) {
        return json({ error: (finalData && finalData.error && finalData.error.message) || 'Claude API error' }, 502, cors);
      }

      // If Claude didn't call a custom tool, we have our final text answer
      if (finalData.stop_reason !== 'tool_use') {
        break;
      }

      const toolUseBlocks = (finalData.content || []).filter((b) => b.type === 'tool_use');
      if (!toolUseBlocks.length) break;

      currentMessages.push({ role: 'assistant', content: finalData.content });

      const toolResults = [];
      for (const block of toolUseBlocks) {
        const output = await executeTool(block.name, block.input, env);
        toolResults.push({
          type: 'tool_result',
          tool_use_id: block.id,
          content: output,
        });
      }

      currentMessages.push({ role: 'user', content: toolResults });
    }

    const reply = (finalData.content || [])
      .filter((b) => b.type === 'text')
      .map((b) => b.text)
      .join('')
      .trim();

    if (finalData.stop_reason === 'refusal') {
      return json({ reply: "(Even I won't touch that one. Ask me something else and I'll find a different way to ruin your day.)" }, 200, cors);
    }

    const cutOff = finalData.stop_reason === 'max_tokens' ? '\n\n(I ran out of room. Say "continue" and I\'ll pick it back up.)' : '';
    return json({ reply: (reply || '(The bot had nothing to say, which is a first.)') + cutOff }, 200, cors);
  },
};
