"""Release pre-flight: every crew override must target a plotted main telecast.

`apply_crew_overrides` refuses an override whose (cfbd_game_id, network_id) is
not a plotted main telecast, which fails the scheduled job's build. The loader
and the synthetic-fixture tests cannot see that, so `ops/release-job.sh` runs
`booth-review audit overrides --release` against the vault's last build before
it tags. In release mode the vault must match its origin and the build's
telecasts table must be the committed one, so the check sees what the job's
build will see. Output is count-and-line-number only; no cell is echoed.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from booth_review.build.crew_overrides import load_crew_overrides
from booth_review.errors import ReferenceTableError

TELECASTS = Path("processed") / "telecasts.parquet"
OVERRIDES_FILE = "crew_overrides.csv"
# Loader messages that cite a line carry only fixed text after it; any other
# reference error (a header mismatch quotes the header row) is replaced.
_SAFE_LOADER_MESSAGE = re.compile(rf"^{re.escape(OVERRIDES_FILE)}: line \d+: [^\n]*$")


@dataclass(frozen=True)
class OverrideCheck:
    telecasts: int  # override telecasts checked
    unplotted_lines: tuple[int, ...]  # crew_overrides.csv first line of each unplotted one


def check_overrides_plotted(reference_dir: Path, telecasts_path: Path) -> OverrideCheck:
    """Compare crew_overrides.csv keys with the plotted main telecasts in a
    build's telecasts.parquet. Raises FileNotFoundError when the table is missing."""
    overrides = load_crew_overrides(reference_dir)
    if not telecasts_path.is_file():
        raise FileNotFoundError(telecasts_path.name)
    plotted = (
        pl.read_parquet(telecasts_path, columns=["game_id", "network_id", "feed_type", "plotted"])
        .filter((pl.col("feed_type") == "main") & pl.col("plotted").fill_null(False))
        .select("game_id", "network_id")
    )
    keys = set(plotted.iter_rows())
    unplotted = tuple(
        sorted(override.line for key, override in overrides.items() if key not in keys)
    )
    return OverrideCheck(telecasts=len(overrides), unplotted_lines=unplotted)


def safe_loader_message(error: ReferenceTableError) -> str:
    """The loader's message when it is a fixed, line-numbered one; else a fixed line."""
    text = str(error)
    if _SAFE_LOADER_MESSAGE.match(text):
        return text
    return f"{OVERRIDES_FILE}: could not be read (missing, empty, or wrong header)"


def _git(vault: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(vault), *args], capture_output=True, text=True, check=False
    )


def release_problems(vault: Path, reference_dir: Path) -> list[str]:
    """What stops a release check from seeing the job's inputs, as fixed messages.

    The vault must fetch, match its upstream, and hold a tracked telecasts
    table unchanged from HEAD (a local `build --no-commit` rewrites it in
    place); crew_overrides.csv must exist, since the loader reads a missing
    file as no overrides."""
    if not (reference_dir / OVERRIDES_FILE).is_file():
        return [f"{OVERRIDES_FILE} is missing from the reference directory"]
    if _git(vault, "rev-parse", "--git-dir").returncode != 0:
        return ["the vault is not a git working copy"]
    if _git(vault, "fetch", "--quiet", "origin").returncode != 0:
        return ["could not fetch the vault"]
    head = _git(vault, "rev-parse", "HEAD")
    upstream = _git(vault, "rev-parse", "@{u}")
    if upstream.returncode != 0:
        return ["the vault branch has no upstream"]
    problems: list[str] = []
    if head.returncode != 0 or head.stdout.strip() != upstream.stdout.strip():
        problems.append("the vault differs from its origin; run git -C data/vault pull --rebase")
    if _git(vault, "ls-files", "--error-unmatch", str(TELECASTS)).returncode != 0:
        problems.append("the vault's telecasts table is not committed")
    elif _git(vault, "diff", "--quiet", "HEAD", "--", str(TELECASTS)).returncode != 0:
        problems.append(
            "the vault's telecasts table differs from its last commit (a local build?); "
            "restore it with git -C data/vault checkout -- processed/telecasts.parquet"
        )
    return problems
