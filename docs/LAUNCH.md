# Launch Checklist

The site went live on 2026-10-17 by setting the vault workflow's `PUBLISH_ENABLED`
variable to `true` with `DEPLOY_REPO=benboro/benboro.github.io`; setting it back to
`false` stops further deploys. 506 Sports
was asked about reuse and has not replied, so launch does not wait on it; if 506 objects,
its crews and networks come off the site. The 2021–2024 figures from Sports Media
Watch, The TV Ratings Guide, Awful Announcing and ESPN Press Room, and ESPN Press
Room's backup crews, are used on the same terms: credited with a link, and taken down
if a site objects (see the takedown notes under Operating
notes). Before launch the scheduled job collected and
built but deployed nothing.

The data repo is private and is only called "the private data repo" here. The dry-run
target is "a private scratch copy of the user site". A checked line carries a pass date
and either a test pointer (`tests/<file>.py::<test>`) or an `evidence:` note.
`tests/test_launch_doc.py` keeps this file honest: pointers must exist, every line is checked now
that the site is live, and no private repo name may appear.

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
- [x] 2026-10-05 Deploy: the workflow's deploy steps require `PUBLISH_ENABLED` to be exactly `true` (a case-sensitive shell compare; `True` or `TRUE` keep publishing off). `tests/test_vault_workflow.py::test_publish_gate_is_exactly_true`
- [x] 2026-10-05 Publishing off, end to end: an update run then deploy changes nothing. `tests/test_job_update_drills.py::test_publishing_off_deploys_nothing_end_to_end`

### Attribution

- [x] 2026-10-05 Each plotted row with a Ratings Reference headline keeps its record URLs, and every plotted row keeps the headline's original source URL in the site data. `tests/test_launch_checks.py::test_plotted_rows_keep_rr_record_urls_and_headline_source_url`
- [x] 2026-10-05 The detail panel links both Ratings Reference records. `tests/e2e/test_site_panel_table.py::test_click_dot_opens_panel_with_both_rr_record_links`
- [x] 2026-10-05 A missing source URL shows as text, not a dead link. `tests/e2e/test_site_panel_table.py::test_open_panel_hook_shows_source_and_506_link_variants`
- [x] 2026-10-13 A Sports Media Watch figure ships without Ratings Reference record links. `tests/test_build_site_data.py::test_second_source_headline_drops_rr_record_links`
- [x] 2026-10-13 A Sports Media Watch figure is credited to Sports Media Watch with a link to its season page, and the panel says it is not listed on Ratings Reference. `tests/e2e/test_site_second_source.py::test_smw_panel_credit_lines`
- [x] 2026-10-05 Footer carries the CFBD credit and the CC BY 4.0 link. `tests/test_site_pages.py::test_footer_html_has_credit_line_once_and_nav_and_credit_links`
- [x] 2026-10-05 Footer carries the "modified" notice and freshness date. `tests/e2e/test_site_static.py::test_footer_credits_freshness_and_nav`

### In-season job drills

- [x] 2026-10-05 Remove-state drill: missing state fails loudly, with no requests made. `tests/test_job_update_drills.py::test_remove_state_drill_fails_loudly_without_requests`
- [x] 2026-10-05 Key-plant drill: a planted key fails the run hard and deploys nothing. `tests/test_job_update_drills.py::test_key_plant_drill_fails_hard_and_deploys_nothing`
- [x] 2026-10-05 Logs hold counts only: no names, query strings, or keys. `tests/test_job_update_drills.py::test_update_run_logs_are_count_only`; Ratings Reference record ids masked in the fetch line: `tests/test_transport_client.py::test_fetch_log_masks_ratingsref_record_ids_and_query_strings`
- [x] 2026-10-05 CFBD budget: the remaining call count is logged at the start and end of each update run. `tests/test_job_runner.py::test_update_run_logs_cfbd_remaining_at_start_and_end`
- [x] 2026-10-05 Tests run network-blocked. `tests/test_network_blocked.py::test_unmocked_client_is_blocked_by_pytest_socket`
- [x] 2026-10-05 Catch-up logic after a skipped slot (unit level; the live drill stays below). evidence: `tests/test_job_catchup.py`
- [x] 2026-10-05 Live publishing-off run of the scheduled workflow. evidence: dispatched run built 1 site (3491 telecasts, 29 files), both deploy steps skipped, target unchanged, 5 CFBD calls
- [x] 2026-10-05 Deploy drill against a private scratch copy of the user site, with before and after proof that nothing outside `booth-review/` changed. evidence: 1 deploy commit, 29 changed paths, 0 outside `booth-review/`, outside-tree hash equal before and after, the target's Pages workflow triggered by the push
- [x] 2026-10-08 Catch-up drill after a skipped main slot, closing AUTO-01. evidence: missed 1, last_success advanced, 5 CFBD season files refreshed, RR new 0, rebuilt and deployed (files 32), outside tree unchanged
- [x] 2026-10-12 Publishing dry run, Sunday: built-data counts match expectations. evidence: first Sunday run finished 14:44 ET (main slot dropped by cron), finals +55 for 55 scored weekend games, 1 deploy commit with 0 paths outside `booth-review/`; RR listed 0 weekend telecasts that day, so none to plot
- [x] 2026-10-15 Publishing dry run, Wednesday: viewership counts match, and CFBD monthly use is well under 1,000. evidence: Wednesday run started 22:22 ET (before the Thursday 16:00 ET last backup), 34 of 34 weekend RR-listed telecasts plotted, 41 job-tagged CFBD calls this month (959 remaining), 0 manual dispatches in the window
- [x] 2026-10-17 Variables reset to `PUBLISH_ENABLED=false` and `DEPLOY_REPO=benboro/benboro.github.io` after the drills. evidence: both read back after the reset, and the dry-run target's outside-`booth-review/` tree hash equal to its seed after 5 deploy commits
- [x] 2026-10-12 NFL scratch-repo deploy drill (999.5 D-21; NFL only, the CFB flip does not wait for it, D-18): one dispatched run on v0.8.0 with `NFL_SITE_ENABLED=true` deployed `site-data.json` and `nfl-data.json` under `booth-review/` (files 54), nothing outside `booth-review/` changed, and the key check passed. evidence: run log lines `cfbd key check: passed`, `nfl site: 3229 games`, `deploy: published bundle 09cacaca2aa7 (files 54)`, `outside booth-review unchanged: yes`; the deployed bundle's NFL views load with no console errors
- [x] 2026-10-17 Map release: `JOB_REF` bumped to a release with the map, one dispatched scratch deploy with outside `booth-review/` unchanged, variables reset. evidence: `JOB_REF` v0.12.1; the dispatched run logged `cfbd key check: passed`, `deploy: published bundle 2383cc9d3388 (files 56)` with the map modules, and `outside booth-review unchanged: yes`; the target's outside tree hash equals its seed; both variables read back as `PUBLISH_ENABLED=false` and `DEPLOY_REPO=benboro/benboro.github.io`
- [x] 2026-10-17 Launch: set the `PUBLISH_ENABLED` variable to `true` (506 Sports was asked and has not replied; launch does not wait on it). evidence: `NFL_SITE_ENABLED=false` set first (college football only), `DEPLOY_REPO=benboro/benboro.github.io`, `JOB_REF` v0.12.1; one dispatched run logged `cfbd key check: passed`, `deploy: published bundle 8f5ea09653e8 (files 39)` and `outside booth-review unchanged: yes`; the target's deploy commit touched only `booth-review/` paths, its Pages workflow succeeded, and the page and `site-data.json` load (200)

## Observations

- Time zone: at the first Sunday main slot after the 2026-11-01 fall-back, confirm the `schedule.timezone` setting keeps the run at 10:00 ET (it must not shift an hour).
- Cron delays: scheduled runs can start late. Read "by Sunday night" as the Sunday main slot or its backups, and "by Wednesday" as the Wednesday slot or the Thursday-morning backups.

## Operating notes

- `NFL_SITE_ENABLED`: only the exact lowercase `true` turns on the NFL switch and `nfl-data.json`; any other value keeps the site CFB-only. Set it only after `JOB_REF` points at a release that includes 999.5. With it on, the switch ships only with a valid `nfl-data.json`. The site gets one from the vault's copy when the CFB site is built; failing that, from the file the NFL block builds later in the same run; failing that, at deploy, from the live copy on the target (validated and key-checked; the deploy then adds the switch and the NFL views to the CFB-only site). A run with none of these deploys CFB alone without the switch. A job run whose site still has no switch after the NFL block raises "nfl site data: no valid file this run, NFL switch off unless the deploy carries the live copy", which makes the run exit 4. The deploy carries the live copy only into a site whose `index.html` lists NFL in its sports meta or, with the flag on, that it turns NFL on for, so the target never holds an `nfl-data.json` that no page loads. A run that cannot refresh the NFL file keeps the vault's last good copy.
- Variables: `PUBLISH_ENABLED`, `DEPLOY_REPO`, `JOB_REF`. Publishing turns on only when `PUBLISH_ENABLED` is exactly `true` (lowercase); any other value, `True` included, keeps it off. Secrets: `CFBD_API_KEY`, `DEPLOY_KEY_PROD`, `DEPLOY_KEY_SCRATCH`. Deploy keys are repo-scoped, one per target; the workflow picks the production key only when `DEPLOY_REPO` is `benboro/benboro.github.io`.
- Rollout order: set `JOB_REF` to the new tag before installing a workflow that passes new flags.
- Releasing a reference fix: patch-bump `version` in `pyproject.toml`, run `uv lock`, update the version literal in the workflow test, open a PR, merge, then run `ops/release-job.sh vX.Y.Z` from the merged main.
- Rollback: set `JOB_REF` to the previous tag.
- Clearing a blocked build: after `git -C data/vault pull --rebase`, run `booth-review build --accept-baseline` locally, then push the vault.
- The staleness check runs only when a run happens. The manual fallback is `gh workflow run`.
- If a drill run is missing, dispatch it again; concurrency keeps one pending run.
- Deploy commits record the bundle hash in their message.
- Taking down Sports Media Watch: remove `raw/smw/<season>/` from the vault for each season, commit and push the vault, and rebuild. The rated counts drop, so if the regression guard blocks the build, accept the new baseline with `booth-review build --accept-baseline`. Its games go back to the "No public rating" strip (`docs/sources/smw.md`).
- Taking down The TV Ratings Guide or Awful Announcing: remove `raw/tvrg/` or `raw/aa/` from the vault, commit and push the vault, and rebuild. If the regression guard blocks the build, accept the new baseline with `booth-review build --accept-baseline` (`docs/sources/tvrg.md`, `docs/sources/aa.md`).
- Taking down ESPN Press Room: remove `raw/espnpr/<season>/` from the vault for each season, commit and push the vault, and rebuild. Backup crews go back to "Crew not listed" and its figures come off the site. Crew overrides in `crew_overrides.csv` that cite an ESPN Press Room release need another public source or removal (`docs/sources/espnpr.md`).
- There is no `.nojekyll` file: the user site's Pages workflow does not run Jekyll.
