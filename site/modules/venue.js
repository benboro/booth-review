/**
 * Venue place text, shared by CFB and NFL: the map tooltips and filter chip, This weekend's
 * "Played in ..." tooltips, the ESPN+ table's inline city, the Matched games tooltip and both
 * game modals' location line. One rule for where a venue is: a US venue names its state, a
 * venue abroad names its country (spelled out with `Intl.DisplayNames`).
 *
 * Every string here is plain text; callers set it with `textContent` or `title`, never markup.
 */

/** The English name of an ISO region code, or the code itself when the runtime has none. */
export function countryName(code) {
  try {
    return new Intl.DisplayNames(['en'], { type: 'region' }).of(code) ?? code;
  } catch {
    return code;
  }
}

/** Whether a venue lies outside the United States. */
export function venueAbroad(venue) {
  return venue.country != null && venue.country !== 'US';
}

/** The state for a US venue, the country name for one abroad, or null. */
function venueRegion(venue) {
  return venueAbroad(venue) ? countryName(venue.country) : (venue.state ?? null);
}

/** "Arlington, TX" or "London, United Kingdom"; null for a missing venue or one with no city. */
export function venueCity(venue) {
  if (!venue?.city) return null;
  const where = venueRegion(venue);
  return where ? `${venue.city}, ${where}` : venue.city;
}

/** "AT&T Stadium, Arlington, TX"; the name alone when the venue has no city. */
export function venueTitle(venue) {
  const city = venueCity(venue);
  if (!city) return venue.name;
  return venue.name ? `${venue.name}, ${city}` : city;
}

/** The tooltip sentence for a neutral-site game, "Played in Arlington, TX", or null. */
export function playedInText(venue) {
  const city = venueCity(venue);
  return city ? `Played in ${city}` : null;
}
