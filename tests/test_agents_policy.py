"""Lock the user-approved wording of the Awful Announcing crew-posts rule."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

APPROVED = [
    "- Awful Announcing crew posts (2026 college football season only): the scheduled "
    "job may fetch only the weekly college football announcing-schedule posts whose "
    "links the feed watch recorded in `ledger/aa_feed_watch.json`, and only through "
    "`booth-review collect aa --crews`.",
    "- **When:** it fetches a post on the Tuesday reminder run that finds it. It "
    "re-checks the post with conditional requests (ETag / Last-Modified) on the Friday "
    "18:00 and Saturday 08:00 ET runs.",
    "- **How:** at most 2 AA requests per run (the feed and the post; the robots.txt "
    "check before them is not counted), at least 3 s apart, with the project user agent "
    "and robots.txt. A request that fails is never retried. Each response is cached "
    "under `raw/aa/crews/2026/`.",
    "- **Policy check:** it needs the same AA policy check as the feed watch: done "
    "within the last 30 days, with terms confirmed. When that check is stale, or "
    "robots.txt refuses the post, the run skips the fetch and says so in the reminder. "
    "If robots.txt or the terms ban automated access, stop.",
    "- **Data and credit:** the parsed crews are private vault data. The site credits "
    "each crew to its exact post, and AA's crews come down if AA objects.",
    "- It ends with the 2026 season.",
]


def _norm(text: str) -> str:
    return " ".join(text.split())


def _agents() -> str:
    return _norm((ROOT / "AGENTS.md").read_text(encoding="utf-8"))


def test_approved_bullets_present_in_order() -> None:
    text = _agents()
    last = -1
    for sentence in APPROVED:
        pos = text.find(_norm(sentence))
        assert pos > last, sentence
        last = pos


def test_feed_watch_sentence_reworded() -> None:
    assert "itself never parses or stores a post body or crew data" in _agents()


def test_feed_watch_ledger_lists_recheck_slots() -> None:
    assert (
        _norm(
            "each week's post link or a mark that its plain reminder went out (after which "
            "that week is not checked again, so it gets one comment), the Friday and "
            "Saturday crews re-check slots already used, and each week whose Tuesday post "
            "request failed (which is not requested again)."
        )
        in _agents()
    )


def test_crew_bullet_between_feed_watch_and_espn() -> None:
    text = _agents()
    feed = text.find("- Awful Announcing feed watch")
    crews = text.find("- Awful Announcing crew posts")
    espn = text.find("- ESPN Press Room:")
    assert 0 <= feed < crews < espn


HAND_SAVED = (
    "- Awful Announcing hand-saved posts: bring weekly college football and NFL "
    "announcing-schedule posts saved in a browser into the vault with "
    "`booth-review import aa [--from <folder>] [--force]` (default folder "
    "`data/incoming/aa/`; save from the browser or copy with `cp -p` to keep each file's "
    "save time). It sends no request, imports 2026 only, and identifies each post by its "
    "canonical link and title. College football posts go to the fetch's cache path, and "
    "the Tuesday job still fetches its own copy over a hand-saved one; NFL posts go to "
    "`raw/nfl/aa/crews/2026/`. Credit every AA crew with its exact post."
)


def test_hand_saved_bullet_after_crew_posts_and_before_espn() -> None:
    text = _agents()
    crews = text.find("- Awful Announcing crew posts")
    hand = text.find(_norm(HAND_SAVED))
    espn = text.find("- ESPN Press Room:")
    assert 0 <= crews < hand < espn


def test_claude_md_is_symlink_to_agents() -> None:
    link = ROOT / "CLAUDE.md"
    assert link.is_symlink()
    assert link.resolve() == (ROOT / "AGENTS.md").resolve()
