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
    "- **How:** at most 2 AA requests per run, at least 3 s apart, with the project "
    "user agent and robots.txt. Each response is cached under `raw/aa/crews/2026/`.",
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


def test_crew_bullet_between_feed_watch_and_espn() -> None:
    text = _agents()
    feed = text.find("- Awful Announcing feed watch")
    crews = text.find("- Awful Announcing crew posts")
    espn = text.find("- ESPN Press Room:")
    assert 0 <= feed < crews < espn


def test_claude_md_is_symlink_to_agents() -> None:
    link = ROOT / "CLAUDE.md"
    assert link.is_symlink()
    assert link.resolve() == (ROOT / "AGENTS.md").resolve()
