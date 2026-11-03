"""Which shipped FBS conferences have no logo on the site (Phase 28, user decision 2026-11-03).

The site draws each conference's logo from the ERAS map in `site/modules/conf-logos.js`; a
conference missing there shows its name as text. A new FBS conference name in the data is not
an error, so the build warns, names the conference and its seasons, and carries on.

`CONFERENCE_LOGO_NAMES` mirrors the ERAS keys as a constant, so the build never reads site
code; `tests/test_site_conf_logos.py` fails when the two differ.
"""

from __future__ import annotations

from collections.abc import Mapping, Set

CONFERENCE_LOGO_NAMES: frozenset[str] = frozenset(
    {
        "ACC",
        "American Athletic",
        "Big 12",
        "Big Ten",
        "Conference USA",
        "Mid-American",
        "Mountain West",
        "Pac-12",
        "SEC",
        "Sun Belt",
    }
)

# Not a conference with a mark: the site always shows this name as text.
FBS_INDEPENDENTS = "FBS Independents"


def missing_conference_logos(
    fbs_seasons: Mapping[str, Set[int]],
) -> list[tuple[str, tuple[int, ...]]]:
    """Each FBS conference with no logo entry, with its sorted seasons, sorted by name.

    `fbs_seasons` maps a conference name to the seasons in which an FBS team played in it.
    """
    return [
        (name, tuple(sorted(seasons)))
        for name, seasons in sorted(fbs_seasons.items())
        if name != FBS_INDEPENDENTS and name not in CONFERENCE_LOGO_NAMES
    ]
