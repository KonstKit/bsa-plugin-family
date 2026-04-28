"""Cross-artifact (sibling-cache + cross-row) validators (v1.3.10 split).

Extracted from `governance/schemas/write_validator.py` in v1.3.10 — the
second half of the god-module decomposition (v1.3.9 carved off per-row
rules + marker validators; this release finishes the major seams).

Modules in this file:

  * `_SiblingArtifactCache` — per-validation-run cache for sibling
    canonical artifact reads. One disk read per (filename, key_column)
    tuple per validation run, regardless of how many rows reference it.
  * `_resolve_sibling_dir` — extract the sibling directory from a
    canonical-artifact path. Honors the `BSA_WORKSPACE_CWD` env-var
    workspace anchor (set by `hooks/pre_write_canonical.sh`) so
    relative paths resolve against the workspace, not the plugin repo.
  * `_apply_foreign_key_rules` — A72-specific (x-bsa-foreign-key-rules)
    Story/Claim/Source resolution + claim_source_consistency.
  * `_apply_nfr_coverage_rules` — A71-specific
    (x-bsa-nfr-coverage-rules) Then-clause Metric+Target embedding.
  * `_check_unique_columns` — shared cross-row uniqueness helper used
    by both `_apply_uniqueness_rules` and `_apply_anchor_binding_rules`.
  * `_apply_foreign_key_refs` — generic (x-bsa-foreign-key-refs)
    schema-agnostic cross-artifact FK resolution.
  * `_apply_uniqueness_rules` — generic (x-bsa-uniqueness-rules)
    schema-agnostic cross-row uniqueness enforcement.
  * `_apply_anchor_binding_rules` — A61-specific
    (x-bsa-anchor-binding-rules) FK + uniqueness bundled.

Backward compat: `write_validator.py` re-exports every public + private
name from this module so the historical caller surface stays unchanged.
The `_DISPATCHER` table + `_make_csv_validator` in `write_validator.py`
both invoke the handlers via the re-imports.

Implementation note on `_normalize_path` coupling: `_resolve_sibling_dir`
needs the same path-normalization function that `_dispatch` uses to
prevent `..`-based dispatcher bypass (H-sec-4 round-2). Rather than
duplicating it here OR introducing a circular import at module-load
time, we lazy-import it inside the function body. The lazy import is
fine because `_resolve_sibling_dir` is only called from
`_make_csv_validator` (in `write_validator.py`), which itself is only
invoked AFTER `write_validator.py` is fully loaded.

Stdlib-only at module level. The `csv` import is needed at module
level by `_SiblingArtifactCache.load`; everything else is built on
top of `re` + `pathlib.PurePosixPath`.
"""

from __future__ import annotations

import csv
import re
from pathlib import PurePosixPath


class _SiblingArtifactCache:
    """Per-validation-run cache for sibling canonical artifact reads.

    A row-level handler that needs to look up sibling artifacts (e.g.,
    every A72 row needs A50 + A59 + A70 reads) would otherwise repeat
    the same disk reads N times per write. The cache is built once per
    ``_make_csv_validator`` invocation and shared across all rows.

    Caches by ``(filename, key_column)`` because the same sibling can
    be indexed by different columns (e.g., A59 by ClaimID for FK
    resolution, A59 by SourceID for some future rule). Idempotent:
    reading a missing file returns ``None`` (handlers treat None as
    "sibling absent — emit a clear violation").
    """

    def __init__(self, base_dir: PurePosixPath):
        self.base_dir = base_dir  # POSIX form, e.g.
                                  # PurePosixPath("analysis/canonical/core_controls")
        self._cache: dict[tuple[str, str], dict[str, dict[str, str]] | None] = {}

    def load(
        self, sibling_filename: str, key_column: str,
    ) -> dict[str, dict[str, str]] | None:
        """Return ``{key_column_value: row_dict}`` for the sibling CSV,
        or ``None`` if the file doesn't exist / can't be read.

        Reads are filesystem-backed (the hook runs after siblings have
        been written). Caches the result so a 100-row A72 produces
        exactly one A70 read, not 100.
        """
        cache_key = (sibling_filename, key_column)
        if cache_key in self._cache:
            return self._cache[cache_key]
        # Resolve the sibling on the actual filesystem. ``base_dir`` was
        # extracted from a hook input path; we do NOT trust it blindly —
        # convert to a real ``Path`` to access the filesystem.
        from pathlib import Path as _Path
        sibling_path = _Path(str(self.base_dir)) / sibling_filename
        if not sibling_path.is_file():
            self._cache[cache_key] = None
            return None
        try:
            with sibling_path.open("r", encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh)
                indexed: dict[str, dict[str, str]] = {}
                for row in reader:
                    if row is None:
                        continue
                    key = (row.get(key_column) or "").strip()
                    if key:
                        indexed[key] = row
        except (OSError, UnicodeDecodeError, csv.Error):
            self._cache[cache_key] = None
            return None
        self._cache[cache_key] = indexed
        return indexed


def _resolve_sibling_dir(path: str) -> PurePosixPath | None:
    """Extract the sibling directory from a canonical-artifact path.

    For ``analysis/canonical/core_controls/A72_traceability_matrix.csv``
    returns ``PurePosixPath("analysis/canonical/core_controls")``. Two
    return-None cases:

    * Path doesn't fit the ``canonical/core_controls`` layout — sibling
      handlers no-op silently.
    * Path fits the layout BUT the dir doesn't exist on disk — same
      no-op. This case covers the existing unit-test pattern where a
      relative path is passed without setting up a full workspace tree;
      hook-layer cross-artifact enforcement still kicks in for any
      production write where the canonical dir is real.

    Discovery layer: ``analysis/discovery/canonical/core_controls/...``
    is also recognized.

    **Path resolution discipline (v1.1.3 round-2 hardening — Codex
    finding):** if ``path`` is relative, the validator cannot
    independently determine the user's workspace from its own CWD —
    the hook script runs the validator with the plugin-repo CWD, not
    the workspace CWD, so a naive ``Path(rel).is_dir()`` would always
    look in the plugin repo and silently miss real workspaces. Two
    workspace anchors are honored, in order:

    1. ``BSA_WORKSPACE_CWD`` env var — the hook sets this from the
       original user-shell CWD before invoking the validator. This is
       the production path.
    2. Process CWD — fallback for tests that explicitly ``monkeypatch.
       chdir(workspace)``. Production hooks always set
       ``BSA_WORKSPACE_CWD``.

    Absolute paths are used as-given. The on-disk check then runs
    against the resolved location.

    v1.3.10 split note: this function imports `_normalize_path` lazily
    from `write_validator.py` to avoid a module-load-time circular
    import. The lazy import is safe because `_resolve_sibling_dir` is
    only invoked from `_make_csv_validator` (in `write_validator.py`),
    which itself runs after `write_validator.py` is fully loaded.
    """
    import os as _os
    from pathlib import Path as _Path
    from .write_validator import _normalize_path  # lazy: avoid circular
    parent_posix = PurePosixPath(_normalize_path(path)).parent
    # Last two components must be canonical/core_controls (main or
    # discovery). Anything else returns None.
    parts = parent_posix.parts
    if len(parts) < 2:
        return None
    if parts[-2:] != ("canonical", "core_controls"):
        return None
    # Resolve to a concrete on-disk path. Absolute → use as-is; relative
    # → anchor to BSA_WORKSPACE_CWD (production hook) or process CWD
    # (tests). _Path.is_absolute handles both Unix and POSIX-form paths.
    parent_real = _Path(str(parent_posix))
    if not parent_real.is_absolute():
        anchor = _os.environ.get("BSA_WORKSPACE_CWD") or _os.getcwd()
        parent_real = _Path(anchor) / parent_real
    if not parent_real.is_dir():
        return None
    # Return the on-disk POSIX form so _SiblingArtifactCache reads from
    # the actual location, not from a CWD-relative ghost path.
    return PurePosixPath(parent_real.as_posix())


def _apply_foreign_key_rules(
    row: dict, schema: dict, row_idx: int,
    path: str, sibling_cache: _SiblingArtifactCache | None,
) -> list[str]:
    """Apply A72-style ``x-bsa-foreign-key-rules`` extension.

    v1.1.3 — closes TODO-S8-02-X-ARTIFACT-FK. Per-row hook-layer
    enforcement of foreign-key resolution + claim/source consistency.

    Rule shape (A72):
      * ``applies_to_all_rows`` (bool) — gate
      * ``story_id_resolves_in`` (str) — sibling CSV (A70_*.csv)
      * ``claim_id_resolves_in`` (str) — sibling CSV (A59_*.csv)
      * ``source_id_resolves_in`` (str) — sibling CSV (A50_*.csv)
      * ``claim_source_consistency`` (bool) — when set, the row's
          ClaimID's own SourceID (per A59) MUST equal this row's
          SourceID. Defends against phantom traces (matrix says claim
          X is sourced by Y, but A59 says claim X is sourced by Z).

    When the sibling cache is unavailable (path outside canonical
    layout), the handler no-ops silently — the row-level schema check
    still applies. When a sibling file is missing, it emits a clear
    "sibling-not-readable" violation.
    """
    ext = schema.get("x-bsa-foreign-key-rules", {})
    if not isinstance(ext, dict) or not ext.get("applies_to_all_rows"):
        return []
    if sibling_cache is None:
        # Path doesn't fit the canonical layout (e.g., test fixture
        # outside analysis/canonical/core_controls/). Skip silently —
        # tests that exercise FK semantics use a real layout.
        return []
    violations: list[str] = []

    def _check_resolution(field_name: str, ext_key: str) -> dict[str, str] | None:
        target_csv = ext.get(ext_key)
        if not target_csv:
            return None
        value = (row.get(field_name) or "").strip()
        if not value:
            return None  # blank cell — schema-level required check covers it
        sibling = sibling_cache.load(target_csv, field_name)
        if sibling is None:
            violations.append(
                f"line {row_idx} {field_name}={value!r}: sibling artifact "
                f"{target_csv} is missing or unreadable — cannot verify FK "
                f"resolution (x-bsa-foreign-key-rules)"
            )
            return None
        if value not in sibling:
            violations.append(
                f"line {row_idx} {field_name}={value!r}: does not resolve in "
                f"{target_csv} (x-bsa-foreign-key-rules → {ext_key})"
            )
            return None
        return sibling[value]

    _check_resolution("StoryID", "story_id_resolves_in")
    claim_row = _check_resolution("ClaimID", "claim_id_resolves_in")
    _check_resolution("SourceID", "source_id_resolves_in")

    # claim_source_consistency: this row's ClaimID, per its A59 entry,
    # MUST be sourced by this row's SourceID. Without this rule the
    # matrix could promise claim C-001 is sourced by S-002 while A59
    # says C-001 is sourced by S-001 — silent disagreement.
    #
    # A59.SourceID rules (governance/schemas/a59.schema.json:28):
    # * Blank → claim has no source binding (A51-routed). A blank
    #   A59.SourceID combined with a non-blank A72 SourceID is a hard
    #   contradiction: the matrix can't promise a source for a claim
    #   the source register doesn't bind. Emit a violation.
    # * Single value → equality check.
    # * Multi-source (joined by ';' or '/') → membership check; the
    #   matrix row is allowed to pick ONE of the claim's sources.
    if ext.get("claim_source_consistency") and claim_row is not None:
        a59_source_raw = (claim_row.get("SourceID") or "").strip()
        row_source = (row.get("SourceID") or "").strip()
        # Split A59.SourceID on the documented multi-source delimiters
        # (';' / '/'). Whitespace is also tolerated. Empty tokens are
        # filtered out.
        a59_sources = [
            tok for tok in re.split(r"[;/\s]+", a59_source_raw) if tok
        ]
        if not a59_sources and row_source:
            violations.append(
                f"line {row_idx}: claim/source consistency violation — "
                f"row.ClaimID={row.get('ClaimID')!r} has empty A59.SourceID "
                f"(claim is unsourced or A51-routed) but this row declares "
                f"SourceID={row_source!r} (x-bsa-foreign-key-rules → "
                f"claim_source_consistency)"
            )
        elif row_source and a59_sources and row_source not in a59_sources:
            violations.append(
                f"line {row_idx}: claim/source consistency violation — "
                f"row.ClaimID={row.get('ClaimID')!r} is sourced by "
                f"{a59_sources!r} per A59 but this row declares "
                f"SourceID={row_source!r} (x-bsa-foreign-key-rules → "
                f"claim_source_consistency)"
            )
    return violations


def _apply_nfr_coverage_rules(
    row: dict, schema: dict, row_idx: int,
    path: str, sibling_cache: _SiblingArtifactCache | None,
) -> list[str]:
    """Apply A71-style ``x-bsa-nfr-coverage-rules`` extension.

    v1.1.3 — closes TODO-S8-01-X-ARTIFACT-NFR-COVERAGE. Per-row
    hook-layer enforcement of NFR Metric+Target embedding in the
    Then-clause when ``RelatedNFRID`` is non-empty.

    Rule semantics (per the schema description):
      * Literal Target match — the A62 row's ``Target`` string MUST
        appear verbatim as a substring of the row's ``Then`` clause.
      * Metric reference — the Then-clause MUST mention at least one
        significant word from the A62 row's ``Metric``. Paraphrase OK
        per the schema rationale; "significant" is length≥3 and not in
        a small stopword list. The relaxed match is intentional: the
        rule is anti-aspiration ("agent gets paged" instead of an
        actual measurement), not anti-paraphrase.

    When ``RelatedNFRID`` is empty (functional scenario), the handler
    no-ops. When the sibling A62 is missing, it emits a clear
    "sibling-not-readable" violation. When ``RelatedNFRID`` doesn't
    resolve in A62, it emits a clear "FK violation" too — same shape
    as the FK handler so operators see one rule family.
    """
    ext = schema.get("x-bsa-nfr-coverage-rules", {})
    if not isinstance(ext, dict):
        return []
    if not ext.get("requires_then_embeds_metric_and_target_when_nfr_set"):
        return []
    if sibling_cache is None:
        return []
    related_nfr = (row.get("RelatedNFRID") or "").strip()
    if not related_nfr:
        return []
    a62_filename = ext.get("nfr_register_filename", "A62_nfr_register.csv")
    a62_rows = sibling_cache.load(a62_filename, "NFRID")
    if a62_rows is None:
        return [(
            f"line {row_idx} RelatedNFRID={related_nfr!r}: sibling artifact "
            f"{a62_filename} is missing or unreadable — cannot verify NFR "
            f"coverage (x-bsa-nfr-coverage-rules)"
        )]
    if related_nfr not in a62_rows:
        return [(
            f"line {row_idx} RelatedNFRID={related_nfr!r}: does not resolve "
            f"in {a62_filename} (x-bsa-nfr-coverage-rules)"
        )]
    nfr_row = a62_rows[related_nfr]
    metric = (nfr_row.get("Metric") or "").strip()
    target = (nfr_row.get("Target") or "").strip()
    then_clause = (row.get("Then") or "").strip()
    violations: list[str] = []
    # Literal Target substring check — the assertion threshold MUST be
    # in the test's observable outcome.
    if target and target not in then_clause:
        violations.append(
            f"line {row_idx}: Then-clause does not embed literal Target "
            f"{target!r} from A62[{related_nfr}] (x-bsa-nfr-coverage-rules → "
            f"requires_then_embeds_metric_and_target_when_nfr_set)"
        )
    # Relaxed Metric reference — at least one significant word, matched
    # at WORD BOUNDARIES so trivial substring overlaps don't false-pass
    # ("page" must not match "paged"; "rate" must not match "iterate").
    # Codex v1.1.3 round-1 finding: substring matching let `latency`
    # spuriously match `latencyish`, so a Then-clause with no real
    # metric reference could slip through.
    if metric:
        stopwords = {"the", "and", "for", "per", "with", "from", "into", "over"}
        words = [
            w.lower() for w in re.split(r"[^a-zA-Z0-9]+", metric)
            if len(w) >= 3 and w.lower() not in stopwords
        ]
        if words:
            then_lower = then_clause.lower()
            # \b is the regex word boundary. We escape each candidate
            # word so any regex metachar in Metric (unlikely for sane
            # NFR metrics, but still) is matched literally.
            matched = any(
                re.search(r"\b" + re.escape(w) + r"\b", then_lower)
                for w in words
            )
            if not matched:
                violations.append(
                    f"line {row_idx}: Then-clause does not reference any "
                    f"significant word from Metric {metric!r} of "
                    f"A62[{related_nfr}] (x-bsa-nfr-coverage-rules → "
                    f"requires_then_embeds_metric_and_target_when_nfr_set)"
                )
    return violations


def _check_unique_columns(
    rows: list[dict],
    unique_columns: object,
    ext_name: str,
) -> list[str]:
    """Shared cross-row uniqueness-check (v1.2.10).

    Emits a ``line N <column>=<value>: duplicate value (first seen on
    line M) — <ext_name> → unique_columns`` violation for each
    occurrence-after-first of a duplicate value in any column listed
    in ``unique_columns``. Empty / blank-after-strip cells are
    skipped — the schema-level required + minLength check covers them
    (avoids double-reporting on a single missing cell).

    ``unique_columns`` is validated defensively: non-list values
    no-op (empty violations list); list items that aren't non-empty
    strings are skipped (no crash, no silent no-op for the whole
    extension). ``ext_name`` is the extension block name used in the
    violation message (e.g., ``x-bsa-anchor-binding-rules`` for A61;
    ``x-bsa-uniqueness-rules`` for the generic extension).

    Pre-v1.2.10 this logic was inlined in :func:`_apply_anchor_binding_rules`.
    v1.2.10 extracts it so the new generic :func:`_apply_uniqueness_rules`
    + the existing A61 handler can both call the same implementation.
    Behavior for A61 is byte-identical pre/post-refactor
    (``test_executable_anchor_binding_duplicate_anchor_id_rejected`` +
    siblings regression-pin this).
    """
    violations: list[str] = []
    if not isinstance(unique_columns, list):
        return violations
    for column in unique_columns:
        if not isinstance(column, str) or not column:
            continue
        seen: dict[str, int] = {}  # value → first row line where it was seen
        for row_idx, row in enumerate(rows, start=2):  # +2 for header
            value = (row.get(column) or "").strip()
            if not value:
                # Blank cell — schema-level required + minLength check
                # covers it. Don't emit a uniqueness violation that
                # would noise on top.
                continue
            if value in seen:
                violations.append(
                    f"line {row_idx} {column}={value!r}: duplicate value "
                    f"(first seen on line {seen[value]}) — "
                    f"{ext_name} → unique_columns"
                )
            else:
                seen[value] = row_idx
    return violations


def _apply_foreign_key_refs(
    rows: list[dict], schema: dict, path: str,
    sibling_cache: _SiblingArtifactCache | None,
) -> list[str]:
    """Apply the generic ``x-bsa-foreign-key-refs`` extension (v1.2.13).

    Schema-agnostic cross-artifact foreign-key resolution for any
    canonical CSV schema. Parallel to the earlier, A72-specific
    ``x-bsa-foreign-key-rules`` extension (which hard-codes
    StoryID/ClaimID/SourceID field names + the ``claim_source_consistency``
    rule) — the new extension handles the common FK-resolution case
    that most schemas need.

    Extension shape::

        "x-bsa-foreign-key-refs": {
          "_comment": "EXECUTABLE at F5 hook layer as of v1.2.13 ...",
          "applies_to_all_rows": true,
          "foreign_keys": [
            {
              "column": "SourceID",
              "table": "A50_source_register.csv",
              "target_column": "SourceID",
              "multi": false,
              "rationale": "Every excerpt must trace to a registered source."
            },
            {
              "column": "SourceClaimIDs",
              "table": "A59_claim_register.csv",
              "target_column": "ClaimID",
              "multi": true,
              "rationale": "Stories trace to direct claims via SourceClaimIDs OR route through A51Ref."
            }
          ]
        }

    Per-FK fields:

    * ``column`` — name of the column in THIS schema's row that holds
      the FK value(s).
    * ``table`` — filename of the sibling canonical CSV (e.g.,
      ``A50_source_register.csv``).
    * ``target_column`` — column in the sibling CSV that the FK
      value must resolve to.
    * ``multi`` (optional, default ``false``) — when ``true``, the
      column value is split on ``[;/\\s]+`` into multiple tokens +
      each token is resolved independently. Matches the convention
      used by the existing A72 FK handler + A70.SourceClaimIDs /
      A62.SourceClaimIDs / A70.RelatedNFRIDs. v1.2.14 hotfix audit:
      every FK whose row-shape pattern allows ``;`` / ``/`` joined
      IDs MUST set ``multi: true`` — otherwise multi-value rows are
      false-positive-rejected as orphan FKs (regression v1.2.13
      shipped + Codex retroactive review caught).
    * **v1.2.14**: the prior ``optional_when_blank`` field was
      removed from the contract. The handler ALWAYS skips blank
      cells regardless of any flag — the schema-level required-
      field check fires separately for required cells, and optional
      cells naturally pass with a blank value. The flag was
      documentary-only (handler never read it); v1.2.14 cleans up
      the contract to describe only the actual runtime behavior.

    Same fail-CLOSED partial-config behavior as the v1.2.8 A61
    anchor-binding handler: a FK entry missing ``column``,
    ``table``, or ``target_column`` (or with wrong types) emits a
    ``<schema config>`` violation rather than silently skipping.

    Same fail-soft sibling-cache behavior as other cross-artifact
    handlers: ``sibling_cache is None`` (outside canonical layout)
    no-ops silently; sibling-missing emits a per-row
    ``sibling-not-readable`` violation for every row with a
    non-blank FK value.

    Same ``applies_to_all_rows`` gate as the other extensions.
    """
    ext = schema.get("x-bsa-foreign-key-refs", {})
    if not isinstance(ext, dict) or not ext.get("applies_to_all_rows"):
        return []
    fks = ext.get("foreign_keys")
    if not isinstance(fks, list) or not fks:
        return []

    violations: list[str] = []
    for fk_idx, fk in enumerate(fks):
        if not isinstance(fk, dict):
            violations.append(
                f"<schema config>: x-bsa-foreign-key-refs.foreign_keys[{fk_idx}] "
                f"must be an object — got {type(fk).__name__}"
            )
            continue
        column = fk.get("column")
        table = fk.get("table")
        target_column = fk.get("target_column")
        # Fail-CLOSED on partial config (v1.2.8 pattern).
        missing = [
            k for k, v in (
                ("column", column), ("table", table),
                ("target_column", target_column),
            )
            if not v or not isinstance(v, str)
        ]
        if missing:
            violations.append(
                f"<schema config>: x-bsa-foreign-key-refs.foreign_keys[{fk_idx}] "
                f"missing or non-string key(s): {', '.join(missing)} — "
                f"fail-CLOSED to surface schema misconfig rather than "
                f"silently skipping FK resolution"
            )
            continue
        multi = bool(fk.get("multi", False))
        # NOTE (v1.2.14): the prior `optional_when_blank` flag is
        # gone. Handler always skips blank cells; the schema-level
        # required-field check fires separately for required cells.

        if sibling_cache is None:
            # Path doesn't fit the canonical layout (test fixture
            # outside analysis/canonical/core_controls/). Skip
            # silently — same convention as A72's handler. Tests
            # that exercise FK resolution use a real layout.
            continue

        sibling = sibling_cache.load(table, target_column)
        if sibling is None:
            # Sibling file missing / unreadable. One violation per
            # row with a non-blank value (operator sees full scope).
            for row_idx, row in enumerate(rows, start=2):  # +2 for header
                raw = (row.get(column) or "").strip()
                if not raw:
                    continue  # nothing to resolve
                violations.append(
                    f"line {row_idx} {column}={raw!r}: sibling artifact "
                    f"{table} is missing or unreadable — cannot verify "
                    f"FK resolution (x-bsa-foreign-key-refs → {column})"
                )
            continue

        for row_idx, row in enumerate(rows, start=2):
            raw = (row.get(column) or "").strip()
            if not raw:
                # Blank cell — skip. The schema-level required check
                # fires separately for required cells (and per-row
                # rules like _apply_claim_type_rules cover the
                # "must be non-blank for direct/inference" cases on
                # A59). Optional-blank cells naturally pass.
                continue
            # Multi-valued: split on the documented delimiters
            # (matches the A72 handler's convention). Single-valued:
            # treat the whole raw string as one token.
            values = (
                [v for v in re.split(r"[;/\s]+", raw) if v]
                if multi else [raw]
            )
            for v in values:
                if v not in sibling:
                    violations.append(
                        f"line {row_idx} {column}={v!r}: does not resolve "
                        f"in {table}.{target_column} "
                        f"(x-bsa-foreign-key-refs → {column})"
                    )
    return violations


def _apply_uniqueness_rules(
    rows: list[dict], schema: dict, path: str,
    sibling_cache: _SiblingArtifactCache | None,
) -> list[str]:
    """Apply the generic ``x-bsa-uniqueness-rules`` extension (v1.2.10).

    Schema-agnostic cross-row uniqueness enforcement. Any schema can
    declare:

    .. code-block:: json

        "x-bsa-uniqueness-rules": {
            "applies_to_all_rows": true,
            "unique_columns": ["ColumnName1", "ColumnName2"],
            "_comment": "..."
        }

    The handler reads the extension, delegates to
    :func:`_check_unique_columns`, and emits line-numbered violations
    for any duplicate-after-first value in any listed column.

    **Deliberately independent of A61's ``x-bsa-anchor-binding-rules``.**
    A schema can declare EITHER extension (or both). A61 declares
    ``x-bsa-anchor-binding-rules`` for historical + semantic-coupling
    reasons (the FK + uniqueness rules are bundled under one
    "anchor-binding" concept); new schemas SHOULD declare
    ``x-bsa-uniqueness-rules`` directly when only cross-row
    uniqueness is needed.

    Same ``sibling_cache`` signature as the other cross-row handlers,
    but uniqueness is self-contained — no sibling reads are needed.
    The arg is kept for uniform handler-calling.
    """
    ext = schema.get("x-bsa-uniqueness-rules", {})
    if not isinstance(ext, dict) or not ext.get("applies_to_all_rows"):
        return []
    return _check_unique_columns(
        rows, ext.get("unique_columns"), "x-bsa-uniqueness-rules",
    )


def _apply_anchor_binding_rules(
    rows: list[dict], schema: dict, path: str,
    sibling_cache: _SiblingArtifactCache | None,
) -> list[str]:
    """Apply A61's ``x-bsa-anchor-binding-rules`` extension (v1.2.8).

    Closes the two cross-row deferrals from v1.2.7:

    * **FK resolution**: every ``A61.SourceClaimID`` MUST resolve to an
      existing row in the sibling artifact named under
      ``source_claim_id_resolves_in.table`` (typically
      ``A59_claim_register.csv``), keyed by
      ``source_claim_id_resolves_in.column`` (typically ``ClaimID``).
      Orphan SourceClaimIDs would let A61 promise diagram bindings
      for claims A59 has never seen — defeats the trace-chain
      invariant.
    * **AnchorID uniqueness**: every column listed in
      ``unique_columns`` MUST be unique across ALL rows in the file.
      Duplicate AnchorIDs would let two distinct claims silently
      project to the same diagram element.

    Unlike :func:`_apply_foreign_key_rules` (A72-specific, per-row),
    this handler takes the FULL row list because uniqueness is a
    cross-row property. The per-row JSON Schema check + the per-row
    extensions still run in the per-row loop above; this handler is
    invoked ONCE per write after the loop.

    Same fail-soft cache contract as the A72 handler: when the
    sibling cache is unavailable (path outside the canonical
    layout), the FK check no-ops silently; when a sibling file is
    missing, the FK check emits a clear "sibling-not-readable"
    violation. The uniqueness check NEVER no-ops — it's a self-
    contained cross-row check that requires no sibling reads.
    """
    ext = schema.get("x-bsa-anchor-binding-rules", {})
    if not isinstance(ext, dict) or not ext.get("applies_to_all_rows"):
        return []
    violations: list[str] = []

    # ---- FK resolution -------------------------------------------
    # Fail-CLOSED on partial config: if the schema declares
    # `source_claim_id_resolves_in` but omits `table` or `column`, that
    # is a SCHEMA-LEVEL bug — silently skipping enforcement (as an
    # earlier draft did) hides the misconfig. Codex v1.2.8 round-1
    # critical: emit a `<schema config>` violation that surfaces at
    # the F5 hook layer just like any other rejection.
    fk_spec = ext.get("source_claim_id_resolves_in")
    if fk_spec is not None and not isinstance(fk_spec, dict):
        violations.append(
            "<schema config>: x-bsa-anchor-binding-rules."
            "source_claim_id_resolves_in must be an object — "
            f"got {type(fk_spec).__name__}"
        )
    elif isinstance(fk_spec, dict):
        table = fk_spec.get("table")
        column = fk_spec.get("column")
        missing_keys = [
            k for k in ("table", "column")
            if not fk_spec.get(k) or not isinstance(fk_spec.get(k), str)
        ]
        if missing_keys:
            violations.append(
                "<schema config>: x-bsa-anchor-binding-rules."
                "source_claim_id_resolves_in missing or non-string "
                f"key(s): {', '.join(missing_keys)} — fail-CLOSED to "
                f"surface schema misconfig at the F5 hook layer "
                f"rather than silently skipping FK enforcement"
            )
        else:
            target_csv = table
            target_column = column
            if sibling_cache is None:
                # Sibling cache unavailable — typically because the
                # path didn't resolve to the canonical layout. Skip
                # silently (per-row schema check still applies via
                # the per-row loop above). Same convention as
                # _apply_foreign_key_rules.
                pass
            else:
                sibling = sibling_cache.load(target_csv, target_column)
                if sibling is None:
                    # Sibling file missing or unreadable. One
                    # violation per affected row so the operator sees
                    # the full scope (mirrors A72's per-row
                    # "sibling-not-readable" style).
                    for row_idx, row in enumerate(rows, start=2):  # +2 for header
                        value = (row.get("SourceClaimID") or "").strip()
                        if not value:
                            # Blank cell — schema-level required check covers it.
                            continue
                        violations.append(
                            f"line {row_idx} SourceClaimID={value!r}: sibling "
                            f"artifact {target_csv} is missing or unreadable — "
                            f"cannot verify FK resolution "
                            f"(x-bsa-anchor-binding-rules → "
                            f"source_claim_id_resolves_in)"
                        )
                else:
                    for row_idx, row in enumerate(rows, start=2):
                        value = (row.get("SourceClaimID") or "").strip()
                        if not value:
                            continue  # schema-level required check covers it
                        if value not in sibling:
                            violations.append(
                                f"line {row_idx} SourceClaimID={value!r}: does "
                                f"not resolve in {target_csv}.{target_column} "
                                f"(x-bsa-anchor-binding-rules → "
                                f"source_claim_id_resolves_in)"
                            )

    # ---- AnchorID uniqueness (cross-row) ------------------------
    # v1.2.10 refactor: delegate to the shared _check_unique_columns
    # helper so both this A61-specific extension AND the new generic
    # x-bsa-uniqueness-rules extension apply the same column-uniqueness
    # semantics. The ext_name arg keeps the violation message source-
    # attributed to x-bsa-anchor-binding-rules (so A61 operators see
    # the A61-specific block name in failures, not the generic one).
    violations.extend(_check_unique_columns(
        rows, ext.get("unique_columns"), "x-bsa-anchor-binding-rules",
    ))

    return violations
