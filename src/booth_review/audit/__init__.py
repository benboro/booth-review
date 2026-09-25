"""D-05 completeness audit and D-06 freeze.

Everything in this package is vault-only: every fact comes from files already
cached under data/vault/raw/ and data/vault/ledger/, and nothing here ever
builds an HTTP client or sends a request.
"""

from __future__ import annotations
