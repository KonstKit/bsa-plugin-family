"""BSA canonical-artifact schemas (F4 foundation, Sprint 5).

This package is the single source of truth for schema discovery. Both
offline validators (``scripts/validate_*.py``) and write-time hooks
(``hooks/pre_write_canonical.sh``) MUST access schemas via
``governance.schemas.loader`` rather than reading the ``.schema.json``
files directly — the loader handles caching, not-found errors, and
future schema-version resolution in one place.

See ``governance/schemas/loader.py`` for the public API.
"""
