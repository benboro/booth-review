#!/usr/bin/env bash
# release-job.sh: tag a clean, pushed main and pin the vault's JOB_REF to it (D-04).
#
# Usage: ops/release-job.sh [--dry-run] vX.Y.Z
#
# A reference-fix batch is a patch bump: edit `version` in pyproject.toml, run
# `uv lock`, update the literal in tests/test_vault_workflow.py, open a PR,
# merge it, then run this script from the merged main. It refuses unless the
# worktree is clean, the branch is main, HEAD equals origin/main, and the tag
# matches pyproject's version. The vault repo is read from data/vault's origin
# at run time; it is never written down or printed.
#
# Rollback: `gh variable set JOB_REF --repo <vault> --body <previous tag>`.
set -euo pipefail

die() {
  echo "error: $*" >&2
  exit 1
}

dry_run=false
tag=""
for arg in "$@"; do
  case "$arg" in
    --dry-run) dry_run=true ;;
    -*) die "unknown option: $arg" ;;
    *)
      [ -z "$tag" ] || die "usage: ops/release-job.sh [--dry-run] vX.Y.Z"
      tag="$arg"
      ;;
  esac
done
[ -n "$tag" ] || die "usage: ops/release-job.sh [--dry-run] vX.Y.Z"
printf '%s' "$tag" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+$' || die "tag must look like vX.Y.Z"

cd "$(git rev-parse --show-toplevel)"

git diff --quiet && git diff --cached --quiet || die "worktree is not clean"
[ "$(git rev-parse --abbrev-ref HEAD)" = "main" ] || die "not on main"
git fetch --quiet origin main --tags
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || die "HEAD differs from origin/main"

version=$(sed -n 's/^version = "\([0-9][0-9.]*\)"$/\1/p' pyproject.toml | head -n 1)
[ "$version" = "${tag#v}" ] || die "tag does not match the pyproject version"

if git rev-parse -q --verify "refs/tags/$tag" >/dev/null; then
  die "tag already exists locally"
fi
if [ -n "$(git ls-remote --tags origin "refs/tags/$tag")" ]; then
  die "tag already exists on origin"
fi

[ -d data/vault ] || die "data/vault is missing"
url=$(git -C data/vault remote get-url origin 2>/dev/null) || die "data/vault has no origin"
slug=$(printf '%s' "$url" | sed -nE 's#.*github\.com[:/]([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)$#\1#p')
slug="${slug%.git}"
[ -n "$slug" ] || die "could not parse the vault origin URL"

short=$(git rev-parse --short HEAD)
if [ "$dry_run" = "true" ]; then
  echo "would tag $tag at $short"
  echo "would set JOB_REF to $tag on the vault repo"
  exit 0
fi

git tag -a "$tag" -m "release $tag"
git push origin "$tag"
gh variable set JOB_REF --repo "$slug" --body "$tag"
# `gh variable list --json` rather than `gh variable get`, which gh 2.45 lacks.
current=$(gh variable list --repo "$slug" --json name,value --jq '.[] | select(.name == "JOB_REF") | .value')
[ "$current" = "$tag" ] || die "JOB_REF verification failed"
echo "JOB_REF set to $tag"
