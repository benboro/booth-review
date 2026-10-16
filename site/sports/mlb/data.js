/**
 * MLB data preparation (D-02, D-04, D-22). DOM-free.
 *
 * prepareMlb(raw) turns mlb-data.json into a model; gameRow(model, i) yields
 * the row the games table and detail panel render. Missing values stay null,
 * never 0.
 */

const REQUIRED_BLOCKS = [
  'games', 'lineups', 'lookups', 'apple_booths', 'apple_summary',
  'postseason', 'postseason_seasons', 'freshness', 'constants',
];
const REQUIRED_LOOKUPS = ['clubs', 'team_names', 'networks', 'people', 'players', 'rounds', 'leagues', 'eras'];

/** Display text per contract round name; a regular-season game has none. */
export const ROUND_LABELS = Object.freeze({
  regular: '',
  wild_card: 'Wild card',
  division: 'Division series',
  lcs: 'League championship',
  world_series: 'World Series',
  tiebreak: 'Tiebreak',
});

/** Why a game has no figure, as table and panel copy (D-22). */
export const CAUSE_COPY = Object.freeze({
  pending: 'not posted yet',
  none: 'no Ratings Reference figure',
  regional: 'regional game, no figure',
  per_network: 'per-network figures only',
  ambiguous_doubleheader: 'doubleheader: figure not tied to one game',
  conflict: 'conflicting records',
  window_level: 'window-level figure',
});

const SOURCE_TAGS = Object.freeze({
  override: 'confirmed',
  506: '506',
  relay: 'relay',
  wikipedia: 'Wikipedia',
});

/** Columnar block -> array of row objects keyed by column name. */
function rowsOf(block) {
  const keys = Object.keys(block);
  const n = keys.length ? block[keys[0]].length : 0;
  const rows = new Array(n);
  for (let r = 0; r < n; r += 1) {
    const row = {};
    for (const k of keys) row[k] = block[k][r];
    rows[r] = row;
  }
  return rows;
}

/** Stable key for a postseason cell: season-round-league ('all' for a World Series). */
export function cellKey(season, round, leagueId) {
  return `${season}-${round}-${leagueId ?? 'all'}`;
}

/**
 * @param {object} raw parsed mlb-data.json
 * @returns {object} model
 */
export function prepareMlb(raw) {
  if (!raw || typeof raw !== 'object') throw new Error('MLB data is not available');
  for (const b of REQUIRED_BLOCKS) {
    if (!raw[b] || typeof raw[b] !== 'object') throw new Error('MLB data is incomplete');
  }
  for (const l of REQUIRED_LOOKUPS) {
    if (!Array.isArray(raw.lookups[l])) throw new Error('MLB data is incomplete');
  }
  const cols = raw.games;
  const n = Array.isArray(cols.season) ? cols.season.length : 0;
  const lookups = raw.lookups;

  const teamNamesByClub = new Map();
  for (const t of lookups.team_names) {
    if (!teamNamesByClub.has(t.club)) teamNamesByClub.set(t.club, []);
    teamNamesByClub.get(t.club).push(t);
  }

  // Lineup rows are contiguous per game, so one pass indexes them.
  const lineupRows = rowsOf(raw.lineups);

  const appleBooths = rowsOf(raw.apple_booths);

  const cells = new Map();
  for (const r of rowsOf(raw.postseason)) {
    const leagueId = r.league == null ? null : lookups.leagues[r.league].id;
    const key = cellKey(r.season, r.round, leagueId);
    let c = cells.get(key);
    if (!c) {
      c = { key, season: r.season, round: r.round, league: leagueId, games: [] };
      cells.set(key, c);
    }
    for (const g of r.game_list) if (!c.games.includes(g)) c.games.push(g);
  }

  // Stable ids for deep links: a booth is its play-by-play person's id, a game is its
  // date, clubs and game number. Positions shift when the data is rebuilt; these do not.
  // A duplicate id (never expected) is kept out of the maps so it cannot misdirect a link.
  const boothIndexById = new Map();
  const duplicateBooths = new Set();
  const boothIds = appleBooths.map((b, k) => {
    const id = raw.lookups.people[b.pbp].id;
    if (boothIndexById.has(id)) duplicateBooths.add(id);
    else boothIndexById.set(id, k);
    return id;
  });
  for (const id of duplicateBooths) boothIndexById.delete(id);
  const gameIndexById = new Map();
  const duplicateGames = new Set();
  const gameIds = new Array(n);
  for (let i = 0; i < n; i += 1) {
    const id = `${cols.date[i]}~${lookups.clubs[cols.away[i]].id}~${lookups.clubs[cols.home[i]].id}~${cols.game_number[i]}`;
    gameIds[i] = id;
    if (gameIndexById.has(id)) duplicateGames.add(id);
    else gameIndexById.set(id, i);
  }
  for (const id of duplicateGames) gameIndexById.delete(id);

  return {
    n,
    cols,
    lookups,
    boothIds,
    boothIndexById,
    gameIds,
    gameIndexById,
    clubs: lookups.clubs,
    networks: lookups.networks,
    people: lookups.people,
    players: lookups.players,
    eras: lookups.eras,
    leagues: lookups.leagues,
    teamNamesByClub,
    lineupRows,
    appleBooths,
    appleSummary: raw.apple_summary,
    cells,
    postseasonSeasons: rowsOf(raw.postseason_seasons),
    postseason: rowsOf(raw.postseason),
    freshness: raw.freshness,
    constants: raw.constants,
  };
}

/** Club display name and short code in a season (the span containing it, else the latest). */
export function clubName(model, club, season) {
  const list = model.teamNamesByClub.get(club) || [];
  const hit = list.find((t) =>
    (t.season_start == null || t.season_start <= season) && (t.season_end == null || t.season_end >= season));
  const t = hit ?? list[list.length - 1];
  return t ? { name: t.name, short: t.short } : { name: model.clubs[club].name, short: model.clubs[club].name };
}

export function personName(model, idx) {
  return idx == null ? null : model.people[idx].name;
}

/** 'Name / Name' for a booth pair of person indexes. */
export function boothLabelOf(model, pbp, analyst) {
  const a = personName(model, pbp);
  const b = personName(model, analyst);
  return b == null ? a : `${a} / ${b}`;
}

/** Cell heading: '2019 League championship, NL'. */
export function cellLabel(cell) {
  const round = ROUND_LABELS[cell.round] || 'Regular season';
  return cell.league ? `${cell.season} ${round}, ${cell.league}` : `${cell.season} ${round}`;
}

/** '12.0M' or null when unrated. */
export function viewersText(viewers) {
  return viewers == null ? null : `${(viewers / 1e6).toFixed(1)}M`;
}

/** Source tag for the table's Crew column, or null. */
export function crewSourceTag(source) {
  return source == null ? null : SOURCE_TAGS[source] ?? null;
}

function lineupSide(model, row) {
  const out = { away: { pitcher: null, batters: [] }, home: { pitcher: null, batters: [] } };
  if (row.lineup_status !== 'present' || row.lineup_start == null || row.lineup_end == null) return out;
  for (let k = row.lineup_start; k <= row.lineup_end; k += 1) {
    const r = model.lineupRows[k];
    if (!r || (r.side !== 'away' && r.side !== 'home')) continue;
    const entry = {
      slot: r.slot,
      name: model.players[r.player].name,
      position: r.position,
      uncertain: !!r.starter_uncertain,
    };
    if (r.slot === 0) out[r.side].pitcher = entry;
    else out[r.side].batters.push(entry);
  }
  for (const side of [out.away, out.home]) side.batters.sort((a, b) => a.slot - b.slot);
  return out;
}

/**
 * The row for game `i`, shared by the games table and the detail panel.
 * @param {object} model
 * @param {number} i
 */
export function gameRow(model, i) {
  const c = model.cols;
  const season = c.season[i];
  const away = clubName(model, c.away[i], season);
  const home = clubName(model, c.home[i], season);
  const net = c.network[i] == null ? null : model.networks[c.network[i]];
  const row = {
    lineup_status: c.lineup_status[i],
    lineup_start: c.lineup_start[i],
    lineup_end: c.lineup_end[i],
  };
  const viewers = c.viewers[i] ?? null;
  const eraIdx = c.era[i];
  const era = viewers != null && eraIdx != null ? model.eras[eraIdx] : null;
  const leagueIdx = c.series_league[i];
  return {
    i,
    season,
    date: c.date[i],
    away: away.name,
    home: home.name,
    awayShort: away.short,
    homeShort: home.short,
    round: c.round[i],
    roundLabel: ROUND_LABELS[c.round[i]] ?? '',
    seriesLeague: leagueIdx == null ? null : model.leagues[leagueIdx].id,
    seriesGame: c.series_game[i] ?? null,
    network: net ? net.name : null,
    networkFamily: net ? net.family ?? null : null,
    networkSource: net ? c.network_source[i] ?? null : null,
    networkSourceUrl: net ? c.network_source_url[i] ?? null : null,
    crew: (c.crew[i] || []).map((m) => ({ name: model.people[m.person].name, role: m.role })),
    crewSource: c.crew_source[i] ?? null,
    crewSourceUrl: c.crew_source_url[i] ?? null,
    pressUrl: c.press_url[i] ?? null,
    pressName: c.press_name[i] ?? null,
    excitement: c.wp_excitement[i] ?? null,
    viewers,
    viewersLabel: c.viewership_label[i] ?? null,
    scope: viewers != null ? c.scope[i] ?? null : null,
    cause: viewers != null ? null : c.cause[i] ?? null,
    era: era ? era.label : null,
    eraUrl: era ? era.source_url ?? null : null,
    rrUrl: c.rr_url[i] ?? null,
    sourceUrl: c.source_url[i] ?? null,
    lineupStatus: row.lineup_status,
    lineups: lineupSide(model, row),
  };
}
