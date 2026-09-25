"""Support code for the scheduled collect-only job (AUTO-01).

This package holds the pure, offline-testable pieces the job's runner
(Plan 06) composes: the ET schedule and catch-up window calculator
(`catchup.py`), the 2026 506 gap finder (`gaps506.py`), and the count-only
attention-issue body builder (`attention.py`). Nothing here sends a network
request; the job orchestration itself, and the rebuild/deploy steps that
follow a successful collection, are Phase 5 scope, not this package.
"""

from __future__ import annotations
