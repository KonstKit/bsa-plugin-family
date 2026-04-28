"""Write-time schema validator for canonical BSA artifacts (F5, Sprint 5).

Used by ``hooks/pre_write_canonical.sh`` to block PreToolUse:Write
events that would land non-conformant content in
``analysis/canonical/**`` or ``analysis/discovery/canonical/**``.

The previous hook only checked WHO was writing (BSA_WRITER env var =
bsa-orchestrator) — it never inspected WHAT was being written. As a
result, the LLM could produce schema-drifted output (camelCase marker
fields, legacy `policy_statement` ClaimType, custom StrengthTier
labels) and the hook waved it through. This module closes that gap by
dispatching by file path to the matching schema and validating the
proposed content before the write commits.

Public API:
    validate_canonical_write(path, content)  -> (ok: bool, messages: list[str])
        Decide if ``content`` is acceptable for the canonical artifact
        at ``path``. Returns (True, []) when valid, (False, [msg, ...])
        with one message per violation. ``messages`` is also useful
        when ok=True for advisory output (e.g., "no schema for this
        path; allowed by default").

    apply_edit(existing_content, old_string, new_string, replace_all=False)
        -> str
        Apply a Claude Code Edit-tool replacement to existing content
        and return the result. Raises EditError when the edit cannot
        be applied unambiguously (old_string not found / not unique
        and replace_all=False). Used by the Edit-shape branch of the
        write-validator CLI.

CLI for shell hooks:
    python3 -m governance.schemas.write_validator <path>
        Reads the file content from stdin (Claude Code PreToolUse:Write
        passes the proposed content as the body of the hook input).
        Exit codes:
          0 — write is allowed (schema match + content valid OR no
              schema matches the path).
          1 — write blocked (schema match + content invalid). stderr
              contains one line per violation.
          2 — invocation error (missing arg, malformed JSON, etc.).

Stdlib-only at module level. ``jsonschema`` is imported lazily inside
the validator dispatch (so the loader can be imported and used for
non-validating purposes — e.g., the audit-pass sequence lookup —
without paying the import cost).
"""

from __future__ import annotations

import csv
import io
import json
import posixpath
import re
import sys
from pathlib import PurePosixPath
from typing import Callable

from . import loader as _loader

# v1.3.9 — god-module decomposition (closes review finding #4). The
# six per-row rule handlers + their shared _STRICT_DATE_SHAPE constant
# live in `_per_row_rules.py` now. The four payload validators
# (marker JSON, Jira export JSON, live-API response JSON, A48 markdown)
# plus their helpers live in `_marker_validators.py`. We re-export
# everything here so the 17+ caller files (tests + scripts) that
# import via the historical
#   `from governance.schemas.write_validator import <name>`
# path continue to work without modification. The _DISPATCHER table
# below also references these via the re-imports.
from ._per_row_rules import (  # noqa: F401 (re-exports)
    _STRICT_DATE_SHAPE,
    _apply_aj_validation_rules,
    _apply_claim_type_rules,
    _apply_deferral_rules,
    _apply_invest_rules,
    _apply_measurability_rules,
    _apply_provenance_rules,
    _apply_strict_date_rules,
)
from ._marker_validators import (  # noqa: F401 (re-exports)
    _expected_stage_verdict,
    _parse_a48_string,
    _validate_a48_markdown,
    _validate_jira_export_json,
    _validate_live_api_response_json,
    _validate_marker_json,
)
# v1.3.10 — cross-artifact extraction completes the v1.3.9 god-module
# decomposition. Sibling cache + 6 cross-row handlers + _resolve_sibling_dir
# now live in `_cross_artifact.py`. Re-exported here so the dispatcher
# table + `_make_csv_validator` in this module continue to use them
# unchanged, AND the existing `tests/test_cross_artifact_validator.py`
# imports (`from governance.schemas.write_validator import _resolve_sibling_dir`)
# still resolve. `_resolve_sibling_dir` lazy-imports `_normalize_path`
# from THIS module (write_validator.py) inside its body to avoid
# module-load-time circular import.
from ._cross_artifact import (  # noqa: F401 (re-exports)
    _SiblingArtifactCache,
    _apply_anchor_binding_rules,
    _apply_foreign_key_refs,
    _apply_foreign_key_rules,
    _apply_nfr_coverage_rules,
    _apply_uniqueness_rules,
    _check_unique_columns,
    _resolve_sibling_dir,
)

# ---- Path → schema dispatcher ----------------------------------------

# Each entry: (regex against POSIX path, schema name, validator function).
# The first match wins. Validators take (path_str, content_str) and
# return list[str] of violation messages (empty list = valid).
# Path is included so validators can cross-check filename↔payload
# bindings (e.g., H-sec-4 marker stem↔marker_id binding); validators
# that don't need the path simply ignore it.

_DispatcherEntry = tuple[re.Pattern[str], str, Callable[[str, str], list[str]]]




# Per-row rule handlers (extracted to `_per_row_rules.py` in v1.3.9).
# See the imports at the top of this module — every handler (plus the
# shared `_STRICT_DATE_SHAPE` regex constant) is re-exported so the
# 17+ historical callers (tests + scripts) that import via
# `from governance.schemas.write_validator import _apply_*` continue
# to work without modification. Implementation rationale (R4 ASCII-
# exact `[0-9]`, R5 no-strip-before-shape-check, R3 don't-double-
# report on shape-invalid values) lives in the docstrings + comments
# in `_per_row_rules.py`.


# Cross-artifact validators (extracted to `_cross_artifact.py` in v1.3.10).
# See the imports at the top of this module — _SiblingArtifactCache,
# _resolve_sibling_dir, and the six cross-row handlers (FK / NFR
# coverage / uniqueness / anchor-binding) are all re-exported so
# _make_csv_validator below + tests/test_cross_artifact_validator.py
# continue to find them at their historical locations.


def _make_csv_validator(schema_name: str) -> Callable[[str, str], list[str]]:
    """Build a CSV-row validator for the named schema.

    Validation order per row:
      1. Column-set sanity (set equality against x-bsa-csv-columns-order).
      2. JSON Schema shape check (every field matches pattern/enum/etc.).
      3. Cross-field x-bsa-*-rules (v1.0.2 C2): currently
         x-bsa-claim-type-rules for A59 (INV-01 + INV-07 executable
         enforcement). Documentary-only invariants become mechanical.

    Cross-row x-bsa-*-rules (v1.2.8 C3 — A61):
      4. After the per-row loop, x-bsa-anchor-binding-rules is invoked
         ONCE with the full row list to enforce cross-row invariants
         (FK resolution + column uniqueness). Schemas that don't
         declare the extension no-op silently — same C2-shaped
         pattern.

    Path argument is accepted for uniformity with the dispatcher
    signature but not used by CSV validators (per-row checks are
    path-independent; future path-aware CSV rules can reuse the slot).
    """

    def _validate(path: str, content: str) -> list[str]:
        import jsonschema  # lazy

        schema = _loader.load_schema(schema_name)
        col_extension = schema["x-bsa-csv-columns-order"]
        expected = col_extension["order"]
        # v1.2.16: optional_order lists additive columns that MAY appear
        # in the CSV without being required. Backward-compatible default.
        optional = col_extension.get("optional_order", [])
        validator = jsonschema.Draft202012Validator(schema)
        # Build the sibling-artifact cache once per validation run.
        # ``None`` when the path is outside the canonical layout — the
        # cross-artifact handlers detect that and no-op silently.
        sibling_dir = _resolve_sibling_dir(path)
        sibling_cache = _SiblingArtifactCache(sibling_dir) if sibling_dir else None
        violations: list[str] = []
        # Collect rows so cross-row handlers (v1.2.8 — A61's
        # x-bsa-anchor-binding-rules) can scan the whole file after
        # the per-row loop. Per-row handlers still see one row at a
        # time inside the loop.
        all_rows: list[dict] = []
        try:
            reader = csv.DictReader(io.StringIO(content))
            actual = set(reader.fieldnames or [])
            expected_set = set(expected)
            optional_set = set(optional)
            allowed_set = expected_set | optional_set
            missing = sorted(expected_set - actual)
            extra = sorted(actual - allowed_set)
            if missing or extra:
                if missing:
                    violations.append(f"<columns>: missing required columns: {missing}")
                if extra:
                    violations.append(f"<columns>: unexpected columns: {extra}")
                # Continue to row-level even on column mismatch — many
                # missing cells will surface meaningful per-row errors too.
            for row_idx, row in enumerate(reader, start=2):  # +2 for header
                # Drop the None key DictReader inserts on column-mismatched rows.
                row = {k: v for k, v in row.items() if k is not None}
                all_rows.append(row)
                for err in sorted(validator.iter_errors(row), key=lambda e: list(e.absolute_path)):
                    field = ".".join(str(p) for p in err.absolute_path) or "<row>"
                    violations.append(f"line {row_idx} {field}: {err.message}")
                # Cross-field extension rules (per-row, no sibling reads).
                # Each helper no-ops when the schema doesn't declare its
                # extension, so this pass is schema-agnostic: new schemas
                # that adopt an existing extension shape get enforcement
                # for free.
                #   x-bsa-claim-type-rules (A59): INV-01 + INV-07
                #   x-bsa-measurability-rules (A62, v1.0.3): INV-09 seed
                #   x-bsa-provenance-rules (A70, v1.0.3): INV-08 seed
                #   x-bsa-invest-rules (A70, v1.0.3): INVEST-A51 coupling
                #   x-bsa-deferral-rules (A71, Sprint 8): generalized
                #     status+A51 coupling — any deferred row must
                #     route through A51.
                # All five follow the C2 pattern: read extension,
                # apply per-row, emit line-numbered message on failure.
                violations.extend(_apply_claim_type_rules(row, schema, row_idx))
                violations.extend(_apply_measurability_rules(row, schema, row_idx))
                violations.extend(_apply_provenance_rules(row, schema, row_idx))
                violations.extend(_apply_invest_rules(row, schema, row_idx))
                violations.extend(_apply_deferral_rules(row, schema, row_idx))
                #   x-bsa-strict-date-rules (A50, v1.2.16 R2):
                #     non-empty/non-'unknown' values in listed columns
                #     must parse as real calendar dates (closes the
                #     shape-vs-calendar gap on EffectiveDate).
                violations.extend(_apply_strict_date_rules(row, schema, row_idx))
                #   x-bsa-aj-validation-rules (A63, v1.4.0):
                #     ValidationStatus=peer_reviewed → PeerReviewerID +
                #     PeerReviewedAt non-empty; ValidationStatus=rejected
                #     → Notes (rationale) non-empty.
                violations.extend(_apply_aj_validation_rules(row, schema, row_idx))
                # Cross-artifact extension rules (v1.1.3, sibling reads).
                # Same C2 pattern but with path + sibling_cache so the
                # handler can resolve A50/A59/A62/A70 entries at hook time.
                #   x-bsa-foreign-key-rules (A72): TODO-S8-02-X-ARTIFACT-FK
                #     closed — StoryID/ClaimID/SourceID resolution +
                #     claim_source_consistency.
                #   x-bsa-nfr-coverage-rules (A71): TODO-S8-01-X-ARTIFACT
                #     -NFR-COVERAGE closed — Then-clause embeds the
                #     A62 row's literal Target + Metric reference.
                violations.extend(_apply_foreign_key_rules(
                    row, schema, row_idx, path, sibling_cache,
                ))
                violations.extend(_apply_nfr_coverage_rules(
                    row, schema, row_idx, path, sibling_cache,
                ))
            # Cross-row extension rules. Invoked ONCE after the per-
            # row loop because the rules need the full row list, not
            # one row at a time. Schemas that don't declare an
            # extension no-op silently — same C2-shaped pattern as
            # the per-row handlers above.
            #   * x-bsa-anchor-binding-rules (v1.2.8 — A61):
            #     FK SourceClaimID → A59.ClaimID + AnchorID uniqueness.
            #   * x-bsa-uniqueness-rules (v1.2.10 — generic):
            #     schema-agnostic cross-row column uniqueness.
            violations.extend(_apply_anchor_binding_rules(
                all_rows, schema, path, sibling_cache,
            ))
            violations.extend(_apply_uniqueness_rules(
                all_rows, schema, path, sibling_cache,
            ))
            #   * x-bsa-foreign-key-refs (v1.2.13 — generic):
            #     schema-agnostic cross-artifact FK resolution.
            #     Parallel to A72's a-specific x-bsa-foreign-key-rules;
            #     most canonical schemas use the new generic one.
            violations.extend(_apply_foreign_key_refs(
                all_rows, schema, path, sibling_cache,
            ))
        except csv.Error as exc:
            violations.append(f"CSV parse error: {exc}")
        return violations

    return _validate


# Path patterns are matched against the POSIX-form path (forward
# slashes). Order matters — first match wins, so put more-specific
# patterns first.
_DISPATCHER: list[_DispatcherEntry] = [
    # Markers (main + discovery).
    (
        re.compile(r"(?:^|/)analysis/(?:discovery/)?runtime/ready/[a-z0-9._]+\.json$"),
        "marker",
        _validate_marker_json,
    ),
    # A48 (markdown, both core_controls locations).
    (
        re.compile(r"(?:^|/)analysis/(?:discovery/)?canonical/core_controls/A48_[a-z_]+\.md$"),
        "a48",
        _validate_a48_markdown,
    ),
    # A50 / A51 / A58 / A59 / A60 (CSV, both core_controls locations).
    (
        re.compile(r"(?:^|/)analysis/(?:discovery/)?canonical/core_controls/A50_[a-z_]+\.csv$"),
        "a50",
        _make_csv_validator("a50"),
    ),
    (
        re.compile(r"(?:^|/)analysis/(?:discovery/)?canonical/core_controls/A51_[a-z_]+\.csv$"),
        "a51",
        _make_csv_validator("a51"),
    ),
    (
        re.compile(r"(?:^|/)analysis/(?:discovery/)?canonical/core_controls/A58_[a-z_]+\.csv$"),
        "a58",
        _make_csv_validator("a58"),
    ),
    (
        re.compile(r"(?:^|/)analysis/(?:discovery/)?canonical/core_controls/A59_[a-z_]+\.csv$"),
        "a59",
        _make_csv_validator("a59"),
    ),
    (
        re.compile(r"(?:^|/)analysis/(?:discovery/)?canonical/core_controls/A60_[a-z_]+\.csv$"),
        "a60",
        _make_csv_validator("a60"),
    ),
    # Sidecar bridge layer (v1.2.7 schema formalization): A61 anchor
    # map. Pre-v1.2.7 A61 was hand-rolled per fixture (the v1.2.6
    # sidecar-e2e fixture documented this as forward-looking). Schema
    # at governance/schemas/a61.schema.json. Required column shape:
    # AnchorID + AnchorKind + SourceClaimID (FK into A59) + Label +
    # Notes. Foreign-key enforcement via _SiblingArtifactCache lands
    # in a follow-up release; v1.2.7 ships the row-shape gate only.
    (
        re.compile(r"(?:^|/)analysis/(?:discovery/)?canonical/core_controls/A61_[a-z_]+\.csv$"),
        "a61",
        _make_csv_validator("a61"),
    ),
    # Phase 3 (Sprint 6+): A62 NFR register.
    (
        re.compile(r"(?:^|/)analysis/(?:discovery/)?canonical/core_controls/A62_[a-z_]+\.csv$"),
        "a62",
        _make_csv_validator("a62"),
    ),
    # Phase 3 (Sprint 7+): A70 story register.
    (
        re.compile(r"(?:^|/)analysis/(?:discovery/)?canonical/core_controls/A70_[a-z_]+\.csv$"),
        "a70",
        _make_csv_validator("a70"),
    ),
    # Phase 3 (Sprint 8 US-S8-01): A71 test scenario register.
    (
        re.compile(r"(?:^|/)analysis/(?:discovery/)?canonical/core_controls/A71_[a-z_]+\.csv$"),
        "a71",
        _make_csv_validator("a71"),
    ),
    # Phase 3 (Sprint 8 US-S8-02): A72 traceability matrix.
    (
        re.compile(r"(?:^|/)analysis/(?:discovery/)?canonical/core_controls/A72_[a-z_]+\.csv$"),
        "a72",
        _make_csv_validator("a72"),
    ),
    # v1.4.0: A63 analyst-judgment register (closes review #3.3).
    # Tracks every A59 ClaimType=analyst_judgment row with hard-to-fake
    # metadata (AnalystID + EmittedAt + UpstreamClaimRefs +
    # ValidationStatus). The bsa-no-new-claims-auditor cross-references
    # A59 vs A63 to ensure every AJ claim has a corresponding A63 row
    # with ValidationStatus != 'rejected' before letting H1/H4 packets
    # carry the [AJ:C-xxx] tag through.
    (
        re.compile(r"(?:^|/)analysis/(?:discovery/)?canonical/core_controls/A63_[a-z_]+\.csv$"),
        "a63",
        _make_csv_validator("a63"),
    ),
    # Phase 3 (Sprint 9 US-S9-01..03): bsa-backlog-bridge exports.
    # First F5 dispatcher entries under analysis/handoff/ rather than
    # canonical/. Exports are derived terminal output (not promoted
    # canonical state); we still gate them at write time so a
    # malformed export — wrong field name, missing provenance, broken
    # platform shape — fails the write rather than landing as a
    # silent half-export the consumer's tool would reject.
    (
        re.compile(r"(?:^|/)analysis/handoff/backlog_export_jira\.json$"),
        "backlog_export_jira",
        _validate_jira_export_json,
    ),
    (
        re.compile(r"(?:^|/)analysis/handoff/backlog_export_linear\.csv$"),
        "backlog_export_linear",
        _make_csv_validator("backlog_export_linear"),
    ),
    (
        re.compile(r"(?:^|/)analysis/handoff/backlog_export_generic\.csv$"),
        "backlog_export_generic",
        _make_csv_validator("backlog_export_generic"),
    ),
    # Phase 3 (Sprint 9 v1.1.4 polish): GitHub Projects v2 export.
    # Closes TODO-S9-03-GITHUB-PROJECTS — operator-side `gh` script
    # (or GitHub Actions workflow) consumes this CSV to gh issue create
    # + gh project item-create + gh project item-edit per row.
    (
        re.compile(r"(?:^|/)analysis/handoff/backlog_export_github\.csv$"),
        "backlog_export_github",
        _make_csv_validator("backlog_export_github"),
    ),
    # Phase 3 (Section C v1.1.6): live API response state files.
    # Closes TODO-S9-LIVE-API. scripts/backlog_live_apply.py POSTs each
    # exported row to the live platform API (Jira REST / Linear GraphQL /
    # GitHub REST) and writes a per-platform state file as the per-row
    # outcome record (idempotency state + platform IDs + retry counts).
    # F5-validated so a malformed response file fails the write rather
    # than landing as corrupt state. Tokens are NEVER persisted.
    #
    # v1.1.6 round-1 (Codex): per-platform filenames are the contract;
    # a shared live_api_response.json would let a sequential
    # Jira→Linear→GitHub run skip the later platforms via stale
    # cross-platform idempotency hits. Pattern: live_api_response_<plat>.json
    # where <plat> ∈ {jira, linear, github}.
    (
        re.compile(r"(?:^|/)analysis/handoff/live_api_response_(?:jira|linear|github)\.json$"),
        "live_api_response",
        _validate_live_api_response_json,
    ),
]


def _normalize_path(path: str) -> str:
    """Canonicalize a path for dispatcher matching.

    Collapses ``..`` / ``.`` segments syntactically (not via filesystem
    resolution) and returns the POSIX form. Prevents path-traversal
    bypass of the dispatcher regexes — e.g.,
    ``analysis/runtime/ready/../ready/stage8.no_new_claims.pass.json``
    would not match `analysis/(?:discovery/)?runtime/ready/...$` on the
    raw string, so the dispatcher would return None and the write
    would pass through unchecked. After normalization the path
    collapses to ``analysis/runtime/ready/stage8.no_new_claims.pass.json``
    and is correctly dispatched to the marker validator.

    H-sec-4 round-2 hardening (Codex finding).
    """
    # posixpath.normpath handles ../ segments without touching the
    # filesystem. We pre-normalize backslashes to forward slashes so
    # Windows-style paths also collapse consistently.
    return posixpath.normpath(path.replace("\\", "/"))


def _dispatch(path: str) -> tuple[str, Callable[[str, str], list[str]]] | None:
    """Find the schema name + validator for the given path, or None.

    Path is normalized before matching so ``..``-based traversal can't
    slip past the dispatcher regex.
    """
    norm = _normalize_path(path)
    for pattern, schema_name, validator_fn in _DISPATCHER:
        if pattern.search(norm):
            return schema_name, validator_fn
    return None


# ---- Public API -------------------------------------------------------


def validate_canonical_write(path: str, content: str) -> tuple[bool, list[str]]:
    """Decide whether ``content`` may be written to the canonical artifact at ``path``.

    Returns a tuple ``(ok, messages)``.

    * ``ok=True`` and empty messages → unconditional pass (no schema
      matches the path; nothing to validate).
    * ``ok=True`` and one info message → schema matched, content validated,
      no violations. The info message names the matched schema.
    * ``ok=False`` and non-empty messages → schema matched, content rejected.
      Each message is one violation, formatted as
      ``"<location>: <reason>"``.
    """
    dispatch = _dispatch(path)
    if dispatch is None:
        return True, []
    schema_name, validator_fn = dispatch
    # Pass the normalized path to the validator so filename-binding
    # checks (e.g., H-sec-4 marker stem↔marker_id) see the collapsed
    # form — otherwise a `..`-containing path would make the stem
    # extraction inconsistent with what the dispatcher matched.
    normalized = _normalize_path(path)
    violations = validator_fn(normalized, content)
    if violations:
        return False, violations
    return True, [f"matched {schema_name}.schema.json — content valid"]


def list_known_paths() -> list[str]:
    """Diagnostic: list the path-pattern strings the dispatcher knows about."""
    return [pattern.pattern for pattern, _, _ in _DISPATCHER]


# ---- Edit-tool support (F5 extension) ---------------------------------


class EditError(ValueError):
    """Raised when an Edit-tool replacement cannot be applied unambiguously."""


def apply_edit(
    existing_content: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> str:
    """Apply a Claude Code Edit-tool replacement and return the resulting content.

    Mirrors the Edit-tool semantics exactly:
      - When ``replace_all=False``, ``old_string`` MUST occur exactly
        once in ``existing_content``. Zero matches → EditError;
        multiple matches → EditError (would be ambiguous).
      - When ``replace_all=True``, every occurrence of ``old_string``
        is replaced with ``new_string``.

    The validator uses this to simulate the post-edit file content
    BEFORE the actual edit commits — so schema violations land at the
    hook layer, not as broken canonical files.
    """
    if old_string == new_string:
        raise EditError("old_string and new_string are identical (no-op edit)")
    if old_string == "":
        raise EditError("old_string must be non-empty")
    if replace_all:
        if old_string not in existing_content:
            raise EditError(
                f"old_string not found in existing content (replace_all=True)"
            )
        return existing_content.replace(old_string, new_string)
    # replace_all=False: require exactly one occurrence.
    occurrences = existing_content.count(old_string)
    if occurrences == 0:
        raise EditError("old_string not found in existing content")
    if occurrences > 1:
        raise EditError(
            f"old_string occurs {occurrences} times — ambiguous; "
            "use replace_all=True or supply more surrounding context"
        )
    return existing_content.replace(old_string, new_string, 1)


# ---- CLI for shell hooks ----------------------------------------------


def _main(argv: list[str]) -> int:
    if len(argv) != 1:
        sys.stderr.write(
            "usage: python3 -m governance.schemas.write_validator <target-path>\n"
            "  Reads the proposed content from stdin.\n"
            "  Exit 0 = allow; 1 = block (violations on stderr); 2 = invocation error.\n"
        )
        return 2
    path = argv[0]
    content = sys.stdin.read()
    ok, messages = validate_canonical_write(path, content)
    if ok:
        # Print the advisory note (if any) to stderr so it's visible
        # in hook logs without polluting stdout.
        for msg in messages:
            sys.stderr.write(f"[write-validator] {msg}\n")
        return 0
    # Block with structured stderr.
    sys.stderr.write(
        f"[write-validator] BLOCKED: schema validation failed for {path}\n"
    )
    for msg in messages:
        sys.stderr.write(f"  - {msg}\n")
    sys.stderr.write(
        "\nThe proposed content does not match the schema for this canonical\n"
        "artifact (governance/schemas/). Fix the violations above, then retry\n"
        "the write. To inspect the schema directly:\n"
        f"  python3 -m governance.schemas.loader load {path!r}\n"
    )
    return 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
