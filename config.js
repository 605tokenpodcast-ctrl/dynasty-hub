// config.js: shared constants and lookup tables (no logic that touches app state).
// Loaded first (before utils.js, tabs/*.js and app.js). These are top-level const declarations in a classic
// script, so every later script sees them as globals. Each name must be declared ONLY here: a duplicate
// const/let declaration in another script throws a SyntaxError and stops that script from loading.

// Offline fallback only: used when ktc_values.json can't be fetched. Live values REPLACE this table
// (never merge), otherwise stale entries like "Marvin Harrison Jr." shadow the live "Marvin Harrison Jr".
const FALLBACK_PLAYER_VALUES = {
    "Bijan Robinson": 9999, "Ja'Marr Chase": 9950, "Justin Jefferson": 9850, "CeeDee Lamb": 9600,
    "Jahmyr Gibbs": 9550, "Malik Nabers": 9450, "Amon-Ra St. Brown": 9400, "Puka Nacua": 9250,
    "Ashton Jeanty": 9200, "Brock Bowers": 9150, "Josh Allen": 9100, "Jayden Daniels": 9000,
    "Lamar Jackson": 8850, "Breece Hall": 8600, "Marvin Harrison Jr.": 8550, "De'Von Achane": 8500,
    "Drake Maye": 8450, "Jaxon Smith-Njigba": 8400, "Brian Thomas Jr.": 8350, "Trey McBride": 8300,
    "Nico Collins": 8250, "Garrett Wilson": 8150, "Drake London": 8100, "Jalen Hurts": 8050,
    "Saquon Barkley": 8000, "Ladd McConkey": 7950, "Rome Odunze": 7900, "Tetairoa McMillan": 7850,
    "Omarion Hampton": 7800, "Jeremiyah Love": 7750, "Sam LaPorta": 7650, "Patrick Mahomes": 7600,
    "Joe Burrow": 7550, "C.J. Stroud": 7450, "Jonathan Taylor": 7400, "Rashee Rice": 7350,
    "Kyren Williams": 7300, "Kenneth Walker III": 7200, "Bucky Irving": 7150, "James Cook III": 7100,
    "A.J. Brown": 7050, "DeVonta Smith": 7000, "Chris Olave": 6900, "Tee Higgins": 6850,
    "Jordan Love": 6800, "Caleb Williams": 6750, "Bo Nix": 6700, "TreVeyon Henderson": 6650,
    "Quinshon Judkins": 6600, "Luther Burden III": 6550, "Travis Hunter": 6500, "Emeka Egbuka": 6450,
    "Colston Loveland": 6400, "Tyler Warren": 6350, "Zay Flowers": 6300, "George Pickens": 6250,
    "Jameson Williams": 6200, "Brandon Aiyuk": 6100, "DK Metcalf": 6050, "Jordan Addison": 6000,
    "Xavier Worthy": 5950, "Josh Jacobs": 5900, "Christian McCaffrey": 5850, "Chuba Hubbard": 5750,
    "Justin Herbert": 5700, "Brock Purdy": 5650, "Kyler Murray": 5600, "Jaylen Waddle": 5550,
    "Cam Skattebo": 5500, "Kaleb Johnson": 5450, "RJ Harvey": 5400, "Carnell Tate": 5350,
    "Jordyn Tyson": 5300, "Makai Lemon": 5250, "Arch Manning": 5200, "Fernando Mendoza": 5100,
    "Dalton Kincaid": 5050, "George Kittle": 5000, "Tucker Kraft": 4950, "T.J. Hockenson": 4900,
    "Derrick Henry": 4850, "David Montgomery": 4800, "Chase Brown": 4750, "D'Andre Swift": 4700,
    "Terry McLaurin": 4650, "DJ Moore": 4600, "Keon Coleman": 4550, "Ricky Pearsall": 4500,
    "Jayden Reed": 4450, "Khalil Shakir": 4400, "Matthew Golden": 4350, "Tre' Harris": 4300,
    "Jayden Higgins": 4250, "Bhayshul Tuten": 4200, "Dylan Sampson": 4150, "Woody Marks": 4100,
    "Zachariah Branch": 4050, "Denzel Boston": 4000, "KC Concepcion Jr.": 3950, "Kenyon Sadiq": 3900,
    "Harold Fannin Jr.": 3850, "Jaxson Dart": 3800, "Cam Ward": 3750, "Tyler Shough": 3700,
    "Michael Penix Jr.": 3650, "Bryce Young": 3600, "Trevor Lawrence": 3550, "Dak Prescott": 3500,
    "Baker Mayfield": 3450, "Jared Goff": 3400, "Sam Darnold": 3300, "Travis Etienne Jr.": 3250,
    "Rhamondre Stevenson": 3200, "Javonte Williams": 3150, "Brian Robinson Jr.": 3100, "Jaylen Warren": 3050,
    "Jordan Mason": 3000, "Rachaad White": 2950, "Zach Charbonnet": 2900, "Trey Benson": 2850,
    "Blake Corum": 2800, "Braelon Allen": 2750, "Tyrone Tracy Jr.": 2700, "Isiah Pacheco": 2650,
    "Alvin Kamara": 2600, "Aaron Jones Sr.": 2500, "Davante Adams": 2450, "Mike Evans": 2400,
    "Courtland Sutton": 2350, "Michael Pittman Jr.": 2300, "Deebo Samuel Sr.": 2250, "Chris Godwin Jr.": 2200,
    "Jerry Jeudy": 2150, "Jakobi Meyers": 2100, "Christian Watson": 2050, "Romeo Doubs": 2000,
    "Josh Downs": 1950, "Wan'Dale Robinson": 1900, "Quentin Johnston": 1850, "Jauan Jennings": 1800,
    "Alec Pierce": 1750, "Rashid Shaheed": 1700, "Kyle Pitts Sr.": 2400, "Mark Andrews": 2300,
    "Jake Ferguson": 2250, "David Njoku": 2100, "Isaiah Likely": 2050, "Pat Freiermuth": 1900,
    "Cade Otton": 1800, "Brandon Aubrey": 1500
};

// Pick keys from FantasyCalc look like "2027 1st", "2027 1st (Mid)" or "2028 3rd (Early)"
const PICK_KEY_RE = /^(20\d\d) (\d+)(?:st|nd|rd|th)(?: \((Early|Mid|Late)\))?$/;

const TREND_COLORS = ['#3b82f6', '#f59e0b', '#10b981', '#ef4444', '#a855f7', '#06b6d4', '#f97316', '#84cc16', '#ec4899', '#eab308', '#14b8a6', '#94a3b8', '#6366f1', '#d946ef'];

// Weekly power score, 0-100: each part is scaled within the league (best team = 1, worst = 0)
const POWER_WEIGHTS = { allPlay: 0.30, ppg: 0.20, recent: 0.15, winPct: 0.15, value: 0.20 };

const POWER_RECENT_WEEKS = 3;

// One button turns the synced data into talking points for the podcast: each league's week
// (scores, upsets, power moves, the playoff race, records in danger, trades, next week's game
// to watch, the Gazette's lead) plus an "around the hub" segment across every league.
// Leagues the show doesn't cover are left out: SFB16 by name, or exclude_from_podcast in leagues.json.
const PODCAST_SKIP = /sfb16|super mario kart/i;

// Playoff week, playoff spots and 3rd-place games per league. Edit leagues.json, not this code.
const DEFAULT_LEAGUE_RULES = { type: 'dynasty', playoff_start_week: { '0': 15 }, playoff_teams: 6, third_place_game: true };

// Every league plays its championship in week 17; week 18 is unused.
const LAST_PLAYOFF_WEEK = 17;

// After deploying workers/award-cards, paste its URL here. Empty = no share links.
const AWARD_CARD_ENDPOINT = 'https://dynasty-award-cards.605tokenpodcast.workers.dev';

// Dark-surface categorical palette (fixed order; validated for adjacent pairs)
const SERIES_COLORS = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'];

// After deploying workers/league-bot, paste its URL here to show the weekly Gazette articles.
const LEAGUE_BOT_ENDPOINT = 'https://dynasty-league-bot.605tokenpodcast.workers.dev';

// Each badge: id, icon, name, kind (good / shame), rule text, and a test that returns a count (0 = not earned)
// or a short detail string. Built from finished games, final standings, trades and the Title Belt.
const BADGE_RULES = [
    { icon: '🏆', name: 'Champion', kind: 'gold', rule: 'Won a league title.', test: m => m.titles },
    { icon: '🔁', name: 'Back-to-Back', kind: 'gold', rule: 'Won the same league two seasons in a row.', test: m => m.repeats },
    { icon: '🥈', name: 'Bridesmaid', kind: 'good', rule: 'Finished runner-up two or more times.', test: m => m.runners >= 2 ? m.runners : 0 },
    { icon: '🎟️', name: 'Playoff Regular', kind: 'good', rule: 'Made the playoffs in five or more finished seasons.', test: m => m.playoffs >= 5 ? m.playoffs : 0 },
    { icon: '📈', name: 'Points Machine', kind: 'good', rule: 'Led a league in regular-season points for a finished season.', test: m => m.pfTitles },
    { icon: '💥', name: 'Record Setter', kind: 'gold', rule: "Owns a league's highest single-game score of all time.", test: m => m.highGame },
    { icon: '🔥', name: 'Heater', kind: 'good', rule: 'Won eight or more games in a row in one league (streaks carry across seasons).', test: m => m.winStreak >= 8 ? m.winStreak : 0, count: v => `${v} straight` },
    { icon: '💯', name: 'Winning Machine', kind: 'good', rule: 'Career winning percentage of .600 or better over 50+ games.', test: m => (m.games >= 50 && m.winPct >= 0.6) ? m.winPct : 0, count: v => v.toFixed(3).replace(/^0/, '') },
    { icon: '🥊', name: 'Belt Holder', kind: 'good', rule: 'Has held a Title Belt (count = reigns).', test: m => m.beltReigns },
    { icon: '🛡️', name: 'Belt Legend', kind: 'gold', rule: 'Ten or more Title Belt defenses in one reign.', test: m => m.beltBest >= 10 ? m.beltBest : 0, count: v => `${v} def.` },
    { icon: '🤝', name: 'Wheeler-Dealer', kind: 'good', rule: 'Made 25 or more trades.', test: m => m.trades >= 25 ? m.trades : 0 },
    { icon: '🎖️', name: 'Veteran', kind: 'good', rule: 'Played ten or more league-seasons.', test: m => m.seasons >= 10 ? m.seasons : 0 },
    { icon: '🌎', name: 'Globetrotter', kind: 'good', rule: 'Played in four or more of these leagues.', test: m => m.leagues >= 4 ? m.leagues : 0 },
    { icon: '💔', name: 'Heartbreak Kid', kind: 'shame', rule: 'Lost five or more games by less than two points.', test: m => m.heartbreaks >= 5 ? m.heartbreaks : 0 },
    { icon: '🥶', name: 'Ice Cold', kind: 'shame', rule: 'Lost ten or more games in a row in one league (streaks carry across seasons).', test: m => m.lossStreak >= 10 ? m.lossStreak : 0, count: v => `${v} straight` },
    { icon: '💩', name: 'Sacko', kind: 'shame', rule: 'Finished last in the regular season of a finished league season.', test: m => m.sackos }
];

const BADGE_STYLES = {
    gold: 'bg-amber-500/15 border-amber-500/40 text-amber-200',
    good: 'bg-blue-500/15 border-blue-500/30 text-blue-200',
    shame: 'bg-rose-500/15 border-rose-500/30 text-rose-200'
};

// After deploying worker.js to Cloudflare, paste the Worker URL here.
const CHAT_ENDPOINT = 'https://league-chat.605tokenpodcast.workers.dev';

const DRAFT_RULE_TEXT = {
    playoff_finish: 'non-podium teams in reverse regular-season standings (worse record first, lower points for breaks ties), then the 3rd place team, runner-up and champion',
    finals: 'every team in reverse regular-season standings (worse record first, lower points for breaks ties), except the runner-up and champion, who pick last',
    standings: 'reverse regular-season standings for every team (worse record first, lower points for breaks ties)'
};

// Trades are built into rows only a page at a time: grading every trade at once took seconds on phones
const TRADES_PAGE_SIZE = 25;

// Dynasty trades are graded 3 years after the trade on a blend of the fantasy points each side's players
// (and the players its picks became) scored for the new team in that window and their dynasty value today.
// Redraft trades are graded at the end of that season on points alone.
const TRADE_GRADE_YEARS = 3;

// Points are what the trade actually delivered, so they carry more weight; value covers the years still to come
const TRADE_GRADE_POINTS_WEIGHT = 0.6;

// Rows come from each league's DRAFT HISTORY section (the syncs save every pick of every draft):
// Season, Draft (Rookie / Startup / Redraft), Round, Pick, Team / Manager (who made the pick), Player,
// Original Owner (only when the pick was someone else's), Notes (Keeper, auction price like "$12").
const DRAFT_GRADE_YEARS = 3;        // rookie and startup picks are judged on their first 3 seasons

const DRAFT_POINTS_WEIGHT = 0.6;    // once those seasons are played; the rest is dynasty value today, as for trades

// An average pick's worth added to both sides of a manager's produced / expected ratio, so one late hit
// on a single pick doesn't read as an A+ draft
const DRAFT_GRADE_SHRINK = 1;

const DRAFT_SCORE_CAP = 4;          // a pick returns at most 4x an early-round pick of its class on either measure

const DRAFT_UNGRADED_POS = /^(K|DEF|D\/ST|DST)$/;

const DRAFT_SKILL_MIN_DRAFTS = 3;   // fewer graded drafts than this: listed, not ranked

// A rookie pick is a hit when the player started 8+ games in one season in that league (for any team)
// within his first 3 seasons, and a miss when he never started more than 3 in any of them. Only classes
// whose rookie season is finished and has lineup history count.
const HIT_STARTS = 8, MISS_STARTS = 3;

const HIT_BUCKETS = [
    { label: 'Picks 1.01-1.03', test: p => p.round === 1 && p.inRound <= 3 },
    { label: 'Picks 1.04-1.06', test: p => p.round === 1 && p.inRound >= 4 && p.inRound <= 6 },
    { label: 'Picks 1.07-1.09', test: p => p.round === 1 && p.inRound >= 7 && p.inRound <= 9 },
    { label: 'Picks 1.10 and later', test: p => p.round === 1 && p.inRound >= 10 },
    { label: 'Round 2', test: p => p.round === 2 },
    { label: 'Round 3', test: p => p.round === 3 },
    { label: 'Round 4 and later', test: p => p.round >= 4 }
];

const MATCHUP_LIVE_TTL = 60 * 1000;

// Fleaflicker sends no CORS headers, so live Fleaflicker data goes through workers/fleaflicker-proxy/.
// Paste the deployed proxy URL here; leave empty to skip live Fleaflicker scores.
const FLEA_PROXY = 'https://dawn-pine-2ee2.605tokenpodcast.workers.dev';

// After deploying workers/live-scores, paste its URL here. Empty = every browser calls Sleeper/Fleaflicker itself.
const LIVE_SCORES_ENDPOINT = 'https://dynasty-live-scores.605tokenpodcast.workers.dev/';

const NAIL_BITERS = '__nailbiters__';

const NAIL_MARGIN = 5;          // a final decided by less than this is a nail-biter

const NAIL_ODDS = [0.4, 0.6];   // a live game with odds in this range is a nail-biter

const TOSSUP_ODDS = [0.45, 0.55]; // an upcoming game this even is a toss-up (pre-game odds are rarely lopsided)

const PLAYOFF_SIMS = 10000;

// Weekly lineups and waiver moves run to thousands of rows, so they stay folded until asked for
const FOLDED_LEAGUE_SECTIONS = ['lineups', 'moves'];
