/**
 * MLB Postseason booths view (SPORT-07): a season-by-round grid, 2014 onward.
 *
 * Rows are seasons, columns the rounds that appear in the data. Each cell shows the
 * outlet, the booth names (Division and League Championship split into AL and NL),
 * games, mean excitement per game and, where Ratings Reference has one, viewers.
 * A season with an incomplete
 * crew record carries its coverage percentage, and a cell with no listed crew says so.
 *
 * Each cell (or league sub-block) is a button that selects its games into the games
 * table. On phones the grid collapses to one stacked block per season (CSS only).
 * Everything is built with createElement and textContent only.
 */
import { boothLabelOf, cellKey, personName } from '../data.js';
import { externalLink } from '../../../modules/panel-parts.js';
import { makePill, makeRolePill, nameWithRoles, currentTheme } from '../../../modules/pill.js';

export const PENDING_TEXT = 'pending Retrosheet 2026';
export const NO_CREW_TEXT = 'crew not listed';
const ROUND_ORDER = ['wild_card', 'division', 'lcs', 'world_series', 'tiebreak'];
const SHORT_ROUNDS = Object.freeze({
  wild_card: 'Wild Card',
  division: 'Division',
  lcs: 'LCS',
  world_series: 'World Series',
  tiebreak: 'Tiebreak',
});

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

const refs = { ctx: null, head: null, body: null, captions: null, table: null };
let current = null;

function coveragePct(num, den) {
  return den > 0 ? Math.round((100 * num) / den) : null;
}

/** Group the postseason rows into sub-blocks keyed by cell key, merging outlets. */
function buildGrid(model) {
  const blocks = new Map();
  for (const r of model.postseason) {
    const leagueId = r.league == null ? null : model.leagues[r.league].id;
    const key = cellKey(r.season, r.round, leagueId);
    let b = blocks.get(key);
    if (!b) {
      b = {
        key, season: r.season, round: r.round, league: leagueId,
        outlets: [], outletSourceUrl: null, booths: [], games: 0, crewListed: 0,
        exciteSum: 0, exciteN: 0, viewerSum: 0, viewerN: 0,
      };
      blocks.set(key, b);
    }
    for (const idx of r.networks) {
      const net = model.networks[idx];
      if (net && !b.outlets.some((o) => o.name === net.name)) b.outlets.push({ name: net.name, family: net.family });
    }
    if (r.outlet_source_url && !b.outletSourceUrl) b.outletSourceUrl = r.outlet_source_url;
    for (const pair of r.booths) {
      if (!b.booths.some((p) => p[0] === pair[0] && p[1] === pair[1])) b.booths.push(pair);
    }
    b.games += r.games;
    b.crewListed += r.crew_listed;
    if (r.mean_excitement != null && r.excitement_n > 0) {
      b.exciteSum += r.mean_excitement * r.excitement_n;
      b.exciteN += r.excitement_n;
    }
    if (r.viewers_mean != null && r.viewers_n > 0) {
      b.viewerSum += r.viewers_mean * r.viewers_n;
      b.viewerN += r.viewers_n;
    }
  }
  return blocks;
}

function viewersText(mean) {
  return `${(mean / 1e6).toFixed(1)}M`;
}

function excitementLine(model, b) {
  if (b.exciteN > 0) {
    return `Excitement ${(b.exciteSum / b.exciteN).toFixed(2)} (${b.exciteN} ${b.exciteN === 1 ? 'game' : 'games'})`;
  }
  const f = model.freshness;
  if (f.quality_pending || (f.retrosheet_through_season != null && b.season > f.retrosheet_through_season)) {
    return PENDING_TEXT;
  }
  return 'no excitement figure';
}

function blockButton(model, b, label, picked) {
  const btn = el('button', 'mlb-cell-btn');
  btn.type = 'button';
  btn.dataset.cell = b.key;
  btn.setAttribute('aria-pressed', String(picked));
  const where = b.league ? `${b.season} ${SHORT_ROUNDS[b.round]} ${b.league}` : `${b.season} ${SHORT_ROUNDS[b.round]}`;
  btn.setAttribute('aria-label', `${where}, ${b.games} ${b.games === 1 ? 'game' : 'games'}`);
  const head = el('span', 'mlb-cell-head');
  if (label) head.append(el('span', 'mlb-cell-league', label));
  for (const o of b.outlets) head.append(makePill(o.name, o.family, currentTheme()));
  btn.append(head);

  const booths = el('span', 'mlb-cell-booths');
  if (b.booths.length) {
    for (const [pbp, analyst] of b.booths) {
      const line = el('span', 'mlb-cell-booth');
      line.append(nameWithRoles(el('span', 'booth-name', personName(model, pbp)), makeRolePill('pbp')));
      if (analyst != null) {
        line.append(el('span', 'booth-sep', ' / '), nameWithRoles(el('span', 'booth-name', personName(model, analyst)), makeRolePill('analyst')));
      }
      booths.append(line);
    }
  } else {
    booths.append(el('span', 'mlb-no-crew', NO_CREW_TEXT));
  }
  if (b.booths.length && b.crewListed < b.games) {
    booths.append(el('span', 'mlb-no-crew', `${NO_CREW_TEXT} for ${b.games - b.crewListed} of ${b.games}`));
  }
  btn.append(booths);

  const stats = el('span', 'mlb-cell-stats');
  stats.append(el('span', null, `${b.games} ${b.games === 1 ? 'game' : 'games'}`));
  const ex = el('span', b.exciteN > 0 ? null : 'mlb-pending', excitementLine(model, b));
  if (b.exciteN === 0) ex.dataset.pending = 'true';
  stats.append(ex);
  if (b.viewerN > 0) {
    stats.append(el('span', null, `Avg ${viewersText(b.viewerSum / b.viewerN)} viewers, ${b.viewerN} of ${b.games} games rated`));
  }
  btn.append(stats);

  btn.addEventListener('click', () => {
    const state = refs.ctx.getState();
    if (state.cell === b.key) refs.ctx.clearSelection();
    else refs.ctx.setState({ cell: b.key });
  });
  return btn;
}

function roundsPresent(model) {
  const have = new Set(model.postseason.map((r) => r.round));
  return ROUND_ORDER.filter((r) => r !== 'tiebreak' || have.has('tiebreak'));
}

export function mount(container, ctx) {
  refs.ctx = ctx;
  const wrap = el('div', 'mlb-grid-wrap');
  const table = el('table', 'games-table mlb-grid');
  table.appendChild(el('caption', 'visually-hidden', 'Postseason booths by season and round'));
  refs.head = el('tr');
  const thead = el('thead');
  thead.appendChild(refs.head);
  refs.body = el('tbody');
  table.append(thead, refs.body);
  wrap.appendChild(table);
  refs.table = table;
  refs.captions = el('div', 'nfl-captions');
  container.append(wrap, refs.captions);
}

export function render(ctx) {
  const { model } = ctx;
  const state = ctx.getState();
  const rounds = roundsPresent(model);
  const blocks = buildGrid(model);
  const bar = model.constants.coverage_bar;

  const heads = [el('th', 'mlb-season-col', 'Season'), ...rounds.map((r) => el('th', null, SHORT_ROUNDS[r]))];
  heads.forEach((th) => { th.scope = 'col'; });
  refs.head.replaceChildren(...heads);

  const seasons = [...model.postseasonSeasons].sort((a, b) => a.season - b.season);
  const rows = [];
  const summary = [];
  for (const s of seasons) {
    const tr = el('tr');
    tr.dataset.season = String(s.season);
    const th = el('th', 'mlb-season-col');
    th.scope = 'row';
    th.append(el('span', 'mlb-season', String(s.season)));
    const pct = coveragePct(s.coverage_num, s.coverage_den);
    // Counts come from the builder's season table: every postseason game of the season.
    const cov = el(
      'span',
      'mlb-season-coverage',
      pct == null ? '' : `Crews listed for ${s.coverage_num} of ${s.coverage_den} postseason games (${pct}%)`,
    );
    const low = s.coverage_den > 0 && s.coverage_num / s.coverage_den < bar;
    if (low) cov.dataset.low = 'true';
    th.append(cov);
    const wikiUrl = [...blocks.values()].find((b) => b.season === s.season && b.outletSourceUrl)?.outletSourceUrl;
    const credit = wikiUrl ? externalLink(wikiUrl, `Outlets: Wikipedia ${s.season} postseason (CC BY-SA 4.0) ↗`) : null;
    if (credit) {
      credit.className = 'mlb-season-credit';
      th.append(credit);
    }
    tr.appendChild(th);
    for (const r of rounds) {
      const td = el('td', 'mlb-cell');
      td.dataset.round = r;
      const here = [...blocks.values()].filter((b) => b.season === s.season && b.round === r);
      if (!here.length) {
        td.classList.add('mlb-cell-empty');
        td.append(el('span', 'mlb-cell-label', SHORT_ROUNDS[r]), el('span', 'mlb-empty-mark', '—'));
      } else {
        td.append(el('span', 'mlb-cell-label', SHORT_ROUNDS[r]));
        here.sort((x, y) => String(x.league).localeCompare(String(y.league)));
        const split = here.length > 1 || here[0].league != null;
        for (const b of here) {
          td.append(blockButton(model, b, split ? b.league : null, state.cell === b.key));
          summary.push({
            key: b.key, season: b.season, round: b.round, league: b.league, games: b.games,
            outlets: b.outlets.map((o) => o.name), outletSourceUrl: b.outletSourceUrl,
            booths: b.booths.map(([p, a]) => boothLabelOf(model, p, a)),
            crewListed: b.crewListed, excitementN: b.exciteN,
            excitement: b.exciteN ? b.exciteSum / b.exciteN : null,
            viewersN: b.viewerN, pending: b.exciteN === 0 && excitementLine(model, b) === PENDING_TEXT,
          });
        }
      }
      tr.appendChild(td);
    }
    rows.push(tr);
  }
  refs.body.replaceChildren(...rows);

  refs.captions.replaceChildren(
    el('p', 'caption', 'Excitement is the mean per game from win probability, a tendency, not proof.'),
    el('p', 'caption', `Season percentages count every postseason game of the season, including games with no outlet listed; a cell counts only the games it shows. Seasons with crews listed for fewer than ${Math.round(bar * 100)}% of those games are marked; their booths are partial.`),
  );
  current = { model, state, summary, seasons: seasons.map((s) => s.season), rounds };
}

export function resize() {}

export function testModel() {
  if (!current) return { view: 'postseason', seasons: [], rounds: [], cells: [] };
  return {
    view: 'postseason',
    seasons: current.seasons,
    rounds: current.rounds,
    cells: current.summary,
    picked: current.state.cell,
  };
}
