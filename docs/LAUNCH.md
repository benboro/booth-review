# Launch Checklist

The site goes live by setting the vault workflow's `PUBLISH_ENABLED` variable to `true`
with `DEPLOY_REPO=benboro/benboro.github.io`. Nothing else changes at launch. Launch
also waits on 506 Sports' approval. Until then the scheduled job collects and builds
but deploys nothing.

The data repo is private and is only called "the private data repo" here. The dry-run
target is "a private scratch copy of the user site". A checked line carries a pass date
and either a test pointer (`tests/<file>.py::<test>`) or an `evidence:` note.
`tests/test_launch_doc.py` keeps this file honest: pointers must exist, every unchecked
line except the last must say "pending", and no private repo name may appear.

## Checklist

### Data quality

- [x] 2026-10-05 Join rate over 95%, plus a 50-match precision sample. evidence: `docs/known-gaps.md` (join coverage counts) and the Phase 3 precision sample (50 of 50 correct).
- [x] 2026-10-05 Dedupe: merged Ratings Reference records keep both record URLs. `tests/test_build_telecasts.py::test_duplicate_rr_records_merge_into_one_telecast`
- [x] 2026-10-05 Dedupe: telecast ids are unique across the frame. `tests/test_build_telecasts.py::test_telecast_id_is_unique_across_the_frame`
- [x] 2026-10-05 Dedupe: no two plotted dots share a game and primary network. `tests/test_launch_checks.py::test_plotted_telecasts_unique_on_game_and_primary_network`
- [x] 2026-10-05 Headline figure: the headline selector ignores peak audience. `tests/test_resolve_headline.py::test_select_headline_ignores_peak_audience`
- [x] 2026-10-05 Headline figure: every headline viewership row in a build is an average audience. `tests/test_launch_checks.py::test_headline_viewership_rows_are_all_avg_audience`
- [x] 2026-10-05 Headline figure: preliminary headlines older than 10 days are listed in a build report (`interim/review_preliminary_headlines.csv`, ids only). `tests/test_build_preliminary_report.py::test_twelve_day_old_preliminary_headline_is_listed`
- [x] 2026-10-05 Headline figure: a preliminary headline under 10 days old is not listed. `tests/test_build_preliminary_report.py::test_nine_day_old_preliminary_headline_is_not_listed`
- [x] 2026-10-05 Person filter: Golic and Golic Jr. stay distinct. `tests/test_build_people_links.py::test_golic_and_golic_jr_stay_distinct_under_the_person_filter`
- [x] 2026-10-05 Person filter: Cris and Jac Collinsworth stay distinct. `tests/test_build_people_links.py::test_cris_and_jac_collinsworth_stay_distinct_under_the_person_filter`
- [x] 2026-10-05 Person filter: overlapping telecasts raise a conflict for review. `tests/test_people_review.py::test_propose_decision_different_when_appearances_overlap`
- [x] 2026-10-05 DST: a November kickoff uses the EST offset and an October one EDT. `tests/test_launch_checks.py::test_november_kickoff_uses_est_offset`

### Publishing and deploy

- [x] 2026-10-05 Publishing: ignore rules keep data out of the repo. `tests/test_gitignore.py::test_ignored_paths_in_real_repo`
- [x] 2026-10-05 Publishing: reference and processed allowances stay tracked. `tests/test_gitignore.py::test_not_ignored_paths_in_real_repo`
- [x] 2026-10-05 Publishing: tests hold no scraped fixtures (every HTML fixture is marked synthetic, no browser-saved page). `tests/test_launch_checks.py::test_fixture_pages_are_marked_synthetic`
- [x] 2026-10-05 Deploy touches only `booth-review/` in the target. `tests/test_deploy_publish.py::test_deploy_touches_only_booth_review`
- [x] 2026-10-05 Deploy: PUBLISH_ENABLED defaults to false and deploys nothing. `tests/test_deploy_publish.py::test_publishing_disabled_deploys_nothing`
- [x] 2026-10-05 Deploy: the workflow's deploy steps require `PUBLISH_ENABLED` to be exactly `true`. `tests/test_vault_workflow.py::test_deploy_steps_gated_on_publish_enabled_true`
- [x] 2026-10-05 Publishing off, end to end: an update run then deploy changes nothing. `tests/test_job_update_drills.py::test_publishing_off_deploys_nothing_end_to_end`

### Attribution

- [x] 2026-10-05 Each plotted row keeps its Ratings Reference record URLs and the headline's original source URL in the site data. `tests/test_launch_checks.py::test_plotted_rows_keep_rr_record_urls_and_headline_source_url`
- [x] 2026-10-05 The detail panel links both Ratings Reference records. `tests/e2e/test_site_panel_table.py::test_click_dot_opens_panel_with_both_rr_record_links`
- [x] 2026-10-05 A missing source URL shows as text, not a dead link. `tests/e2e/test_site_panel_table.py::test_open_panel_hook_shows_source_and_506_link_variants`
- [x] 2026-10-05 Footer carries the CFBD credit and the CC BY 4.0 link. `tests/test_site_pages.py::test_footer_html_has_credit_line_once_and_nav_and_credit_links`
- [x] 2026-10-05 Footer carries the "modified" notice and freshness date. `tests/e2e/test_site_static.py::test_footer_credits_freshness_and_nav`

### In-season job drills

- [x] 2026-10-05 Remove-state drill: missing state fails loudly, with no requests made. `tests/test_job_update_drills.py::test_remove_state_drill_fails_loudly_without_requests`
- [x] 2026-10-05 Key-plant drill: a planted key fails the run hard and deploys nothing. `tests/test_job_update_drills.py::test_key_plant_drill_fails_hard_and_deploys_nothing`
- [x] 2026-10-05 Logs hold counts only: no names, query strings, or keys. `tests/test_job_update_drills.py::test_update_run_logs_are_count_only`; Ratings Reference record ids masked in the fetch line: `tests/test_transport_client.py::test_fetch_log_masks_ratingsref_record_ids_and_query_strings`
- [x] 2026-10-05 CFBD budget: the remaining call count is logged at the start and end of each update run. `tests/test_job_runner.py::test_update_run_logs_cfbd_remaining_at_start_and_end`
- [x] 2026-10-05 Tests run network-blocked. `tests/test_network_blocked.py::test_unmocked_client_is_blocked_by_pytest_socket`
- [x] 2026-10-05 Catch-up logic after a skipped slot (unit level; the live drill stays below). evidence: `tests/test_job_catchup.py`
- [ ] Live publishing-off run of the scheduled workflow: pending (Plan 10)
- [ ] Deploy drill against a private scratch copy of the user site, with before and after proof that nothing outside `booth-review/` changed: pending (Plan 11)
- [ ] Catch-up drill after a skipped main slot, closing AUTO-01: pending (Plan 12)
- [ ] Publishing dry run, Sunday: built-data counts match expectations: pending (Plan 13)
- [ ] Publishing dry run, Wednesday: viewership counts match, and CFBD monthly use is well under 1,000: pending (Plan 14)
- [ ] Variables reset to `PUBLISH_ENABLED=false` and `DEPLOY_REPO=benboro/benboro.github.io` after the drills: pending (Plan 14)
- [ ] Launch: set the `PUBLISH_ENABLED` variable to `true` (after 506 Sports' approval)

## Observations

- Time zone: at the first Sunday main slot after the 2026-11-01 fall-back, confirm the `schedule.timezone` setting keeps the run at 10:00 ET (it must not shift an hour).
- Cron delays: scheduled runs can start late. Read "by Sunday night" as the Sunday main slot or its backups, and "by Wednesday" as the Wednesday slot or the Thursday-morning backups.

## Operating notes

- Variables: `PUBLISH_ENABLED`, `DEPLOY_REPO`, `JOB_REF`. Secrets: `CFBD_API_KEY`, `DEPLOY_KEY_PROD`, `DEPLOY_KEY_SCRATCH`. Deploy keys are repo-scoped, one per target; the workflow picks the production key only when `DEPLOY_REPO` is `benboro/benboro.github.io`.
- Rollout order: set `JOB_REF` to the new tag before installing a workflow that passes new flags.
- Releasing a reference fix: patch-bump `version` in `pyproject.toml`, run `uv lock`, update the version literal in the workflow test, open a PR, merge, then run `ops/release-job.sh vX.Y.Z` from the merged main.
- Rollback: set `JOB_REF` to the previous tag.
- Clearing a blocked build: after `git -C data/vault pull --rebase`, run `booth-review build --accept-baseline` locally, then push the vault.
- The staleness check runs only when a run happens. The manual fallback is `gh workflow run`.
- If a drill run is missing, dispatch it again; concurrency keeps one pending run.
- Deploy commits record the bundle hash in their message.
- There is no `.nojekyll` file: the user site's Pages workflow does not run Jekyll.
