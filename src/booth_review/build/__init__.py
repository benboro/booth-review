"""The build layer: a deterministic full rebuild of the processed tables from
data already cached under data/vault/raw/ and the public data/reference/
tables. Nothing here ever fetches (T-01-51); every fact comes from files the
collectors already wrote. Outputs are Parquet under data/vault/processed/
(D-12) plus CSV review/diagnostic files where a human needs to read one.
"""

from __future__ import annotations
