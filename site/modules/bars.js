/**
 * Bars and Butterfly counting core (SITE-33..36, D-01..D-18). DOM-free;
 * imports only from ./select.js. Every value is a count of rated telecasts
 * (D-01): this module never reads `viewers` and no model carries one.
 *
 * Games counted are exactly those passing every filter, narrowed to the
 * person-matched games when someone is selected (D-02). Crew matching goes
 * only through select.js's `personOnGame`. Rows sort by count descending,
 * ties by bare name (D-03); announcer rows share one list labeled
 * `Name · PBP`/`Analyst`/`PBP/Analyst` (D-04). The butterfly (D-05..D-09)
 * mirrors the Bars rows for exactly two schools or two announcers.
 * `chartContext` decides which tabs apply and the Group-by (D-07, D-11) and
 * `drillPatch` builds the setState patch for a row/segment click (D-18).
 */



/** Rows shown before "show all" (D-03). */
export const TOP_N = 15;

/** Row key for games whose conference is unknown (D-15). */
export const NO_CONFERENCE_KEY = 'c:__none__';

/** Role tags appended to announcer labels (D-04). */
export const ROLE_TAGS = { pbp: 'PBP', analyst: 'Analyst', unknown: 'Other' };

const ROLE_ORDER = ['pbp', 'analyst', 'unknown'];

/**
 * Which bar tabs apply, and the Group-by choice (D-07, D-11, D-13).
 * `state.group` keeps the raw preference; the resolved value is returned.
 * @param {object} _data - a `prepareData` result (unused).
 * @param {object} state
 * @returns {object}
 */
export function chartContext(_data, state) {
  const announcersApply = state.school.length > 0;
  const teamsApply = state.networks !== null || state.people.length > 0;
  const preferTeams = state.group === 'teams';
  const groupChoice = announcersApply && teamsApply;
  let group = 'teams';
  if (groupChoice) group = preferTeams ? 'teams' : 'announcers';
  else if (announcersApply) group = 'announcers';

  const twoSchools = state.school.length === 2;
  const twoPeople = state.people.length === 2;
  const butterflyGroupChoice = twoSchools && twoPeople;
  let butterflyGroup = 'teams';
  if (butterflyGroupChoice) butterflyGroup = preferTeams ? 'teams' : 'announcers';
  else if (twoSchools) butterflyGroup = 'announcers';

  return {
    barsEnabled: announcersApply || teamsApply,
    groupChoice,
    group,
    butterflyEnabled: twoSchools || twoPeople,
    butterflyGroupChoice,
    butterflyGroup,
  };
}
