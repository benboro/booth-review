// Effective-mode resolver for the NFL views (Phase 15). The stored preference (the URL
// always encodes it) is never written here: a pick that cuts inside a shipped aggregate
// only forces Raw/Viewers for display, and these functions return the reason sentence.

/** The Raw reason copy (UI-SPEC, "Mode controls and the Raw reason bar"). */
export const REASONS = Object.freeze({
  crewsTeam:
    'Showing Raw: a Team pick cuts inside each booth’s season, and adjusted values are shipped only for whole booth seasons. Clear the Team pick to see Adjusted again.',
  crewsSubset:
    'Showing Raw: this filter cuts inside each booth’s season. Clear it to see Adjusted again.',
  viewershipCategory:
    'Showing Raw: Category picks do not line up with the viewership categories, so residuals are off. Clear the Category pick to see Residual again.',
  viewershipSubset:
    'Showing Raw: this filter cuts inside each category’s season. Clear it to see Residual again.',
});

const has = (list) => Array.isArray(list) && list.length > 0;

/**
 * Crews mode. Team and Category picks, and an Announcers pick classified 'subset'
 * (see picks.js classifyAnnouncers), force Raw; Seasons, Booths and a PBP-voice
 * ('rowfilter') Announcers pick are row filters and never do.
 */
export function crewsMode(state, { announcers = 'none' } = {}) {
  const stored = state.adjusted ? 'adjusted' : 'raw';
  if (stored === 'raw') return { stored, effective: 'raw', forced: false, reason: null };
  if (has(state.teams)) {
    return { stored, effective: 'raw', forced: true, reason: REASONS.crewsTeam };
  }
  if (has(state.cats) || announcers === 'subset') {
    return { stored, effective: 'raw', forced: true, reason: REASONS.crewsSubset };
  }
  return { stored, effective: 'adjusted', forced: false, reason: null };
}

/**
 * Viewership mode (Residual vs Viewers). A Category pick wins over the other reason;
 * Team, Announcers and Booths picks cut inside each category season.
 */
export function viewershipMode(state) {
  const stored = state.viewY === 'resid' ? 'resid' : 'mean';
  if (stored === 'mean') return { stored, effective: 'mean', forced: false, reason: null };
  if (has(state.cats)) {
    return { stored, effective: 'mean', forced: true, reason: REASONS.viewershipCategory };
  }
  if (has(state.teams) || has(state.people) || has(state.booths)) {
    return { stored, effective: 'mean', forced: true, reason: REASONS.viewershipSubset };
  }
  return { stored, effective: 'resid', forced: false, reason: null };
}
