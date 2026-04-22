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

# ---- Path → schema dispatcher ----------------------------------------

# Each entry: (regex against POSIX path, schema name, validator function).
# The first match wins. Validators take (path_str, content_str) and
# return list[str] of violation messages (empty list = valid).
# Path is included so validators can cross-check filename↔payload
# bindings (e.g., H-sec-4 marker stem↔marker_id binding); validators
# that don't need the path simply ignore it.

_DispatcherEntry = tuple[re.Pattern[str], str, Callable[[str, str], list[str]]]


def _expected_stage_verdict(marker_id: str) -> tuple[str | None, str | None]:
    """Derive the expected (stage, verdict) pair for a marker_id.

    Returns (None, None) if the marker_id shape isn't recognized
    (which should never happen when called after the schema enum has
    already validated marker_id — but we return silently for safety).
    Returns (stage, None) if stage is determined but verdict is not
    uniquely fixed by the marker_id (e.g., currently there are no
    such cases — every recognized marker_id implies a unique verdict).

    Used by the marker validator (H-sec-4) to cross-check the payload.
    The returned values are matched AGAINST the schema's stage + verdict
    enums, so unknown stages here still surface as "stage enum violation"
    via the base JSON Schema check; this function's job is only the
    marker_id→stage,verdict implication check.
    """
    # Exact-match table first (highest-priority; most specific).
    EXACT: dict[str, tuple[str, str]] = {
        "stage1.excerpts.merged": ("stage1", "MERGED"),
        "discovery.d2.claims.merged": ("d2", "MERGED"),
        "handoff.ready": ("handoff", "READY"),
        "pipeline.complete": ("pipeline", "PASS"),
        "bsa.stage1.entry.enabled": ("discovery.bridge", "READY"),
        "discovery.exit.pass": ("discovery.exit", "PASS"),
        "discovery.go": ("discovery.exit", "GO"),
        "discovery.pivot": ("discovery.exit", "PIVOT"),
        "discovery.more_research": ("discovery.exit", "MORE_RESEARCH"),
        "discovery.no_go": ("discovery.exit", "NO_GO"),
    }
    if marker_id in EXACT:
        return EXACT[marker_id]
    # Patterned matches.
    m = re.match(r"^stage([1-8])\.ready$", marker_id)
    if m:
        return f"stage{m.group(1)}", "READY"
    m = re.match(r"^stage([1-8])\..+\.pass$", marker_id)
    if m:
        return f"stage{m.group(1)}", "PASS"
    m = re.match(r"^discovery\.d([1-5])\.ready$", marker_id)
    if m:
        return f"d{m.group(1)}", "READY"
    m = re.match(r"^discovery\.d([1-5])\..+\.pass$", marker_id)
    if m:
        return f"d{m.group(1)}", "PASS"
    return None, None


def _validate_marker_json(path: str, content: str) -> list[str]:
    """Parse JSON, validate against marker schema + H-sec-4 bindings.

    H-sec-4 (v1.0.2) adds three checks the schema itself can't express:

    1. **FormatChecker** — enable jsonschema FormatChecker so the
       `format: date-time` on timestamp actually enforces ISO-8601
       rather than being advisory. Pre-H-sec-4, `timestamp: "not-a-date"`
       passed validation.

    2. **Filename↔marker_id binding** — the path stem MUST equal
       `payload.marker_id`. Pre-H-sec-4, a file named
       `stage8.no_new_claims.pass.json` could contain an unrelated
       marker payload (e.g., marker_id=`stage1.ready`) and still
       satisfy pre_bash_promote.sh (which only checks filename
       presence). Now the content must match the filename.

    3. **marker_id↔(stage, verdict) binding** — each marker_id implies
       a specific stage + verdict. `stage3.citation_audit.pass` implies
       stage=stage3, verdict=PASS; `discovery.go` implies
       stage=discovery.exit, verdict=GO. The derivation table is in
       `_expected_stage_verdict`. Mismatches flagged.
    """
    import jsonschema  # lazy

    try:
        doc = json.loads(content)
    except json.JSONDecodeError as exc:
        return [f"invalid JSON: {exc}"]
    if not isinstance(doc, dict):
        return ["marker file must contain a JSON object at the top level"]
    schema = _loader.load_schema("marker")
    # H-sec-4 part 1: enable FormatChecker so format: date-time is real.
    format_checker = jsonschema.FormatChecker()
    validator = jsonschema.Draft202012Validator(schema, format_checker=format_checker)
    violations = [
        f"{'.'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path))
    ]

    # H-sec-4 part 2: filename↔marker_id binding. Only meaningful when
    # marker_id is present and valid (otherwise the schema error above
    # is the primary diagnostic; no need to layer another message).
    marker_id = doc.get("marker_id")
    if isinstance(marker_id, str) and marker_id:
        path_stem = PurePosixPath(path).stem
        if path_stem != marker_id:
            violations.append(
                f"<filename-binding>: path stem {path_stem!r} does not match "
                f"payload marker_id {marker_id!r}. A marker file MUST be named "
                f"after its marker_id so downstream tools (e.g., pre_bash_promote.sh) "
                f"cannot be fooled by filename-only presence checks."
            )
        # H-sec-4 part 3: marker_id↔(stage, verdict) binding.
        expected_stage, expected_verdict = _expected_stage_verdict(marker_id)
        actual_stage = doc.get("stage")
        actual_verdict = doc.get("verdict")
        if expected_stage and isinstance(actual_stage, str) and actual_stage != expected_stage:
            violations.append(
                f"stage: {actual_stage!r} does not match marker_id {marker_id!r} "
                f"which implies stage={expected_stage!r}"
            )
        if expected_verdict and isinstance(actual_verdict, str) and actual_verdict != expected_verdict:
            violations.append(
                f"verdict: {actual_verdict!r} does not match marker_id {marker_id!r} "
                f"which implies verdict={expected_verdict!r}"
            )
    return violations


def _validate_a48_markdown(path: str, content: str) -> list[str]:
    """Parse A48 markdown, validate normalized dict against schema.

    Path argument is accepted for uniformity with the dispatcher
    signature but not used by A48 validation.
    """
    import jsonschema  # lazy

    del path  # not used for A48 (no path-dependent bindings)
    # parse_a48 takes a Path; emulate by writing to a tmp buffer or
    # parsing inline. We re-implement the parser inline here against
    # the string to avoid filesystem touch — the regex set is the same.
    fields = _parse_a48_string(content)
    if not fields:
        return ["A48 markdown declares no recognizable fields"]
    schema = _loader.load_schema("a48")
    validator = jsonschema.Draft202012Validator(schema)
    return [
        f"{'.'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in sorted(validator.iter_errors(fields), key=lambda e: list(e.absolute_path))
    ]


def _parse_a48_string(text: str) -> dict[str, str]:
    """In-string A48 parser — mirrors loader.parse_a48 but takes text directly."""
    fields: dict[str, str] = {}

    # Table pass.
    in_table = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.startswith("|"):
            in_table = False
            continue
        if _loader._A48_TABLE_HEADER.match(line):
            in_table = True
            continue
        if _loader._A48_TABLE_SEPARATOR.match(line):
            continue
        if in_table:
            m = _loader._A48_TABLE_ROW.match(line)
            if m:
                field, value = m.group(1), _loader._strip_value_decoration(m.group(2))
                fields.setdefault(field, value)

    # Bullet pass + nested-children handling (same logic as loader.parse_a48).
    pending_field: str | None = None
    pending_children: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if line.startswith("- "):
            if pending_field and pending_children:
                joined = "; ".join(pending_children)
                existing = fields.get(pending_field, "")
                fields[pending_field] = (
                    f"{existing}; {joined}" if existing and joined else (existing or joined)
                )
            pending_field = None
            pending_children = []
            for pattern in _loader._A48_BULLET_PATTERNS:
                m = pattern.match(line)
                if m:
                    field, value = m.group(1), _loader._strip_value_decoration(m.group(2))
                    fields.setdefault(field, value)
                    if not value:
                        pending_field = field
                    break
        elif pending_field and line.lstrip().startswith("- "):
            child = line.lstrip()[2:].strip()
            child = _loader._strip_value_decoration(child)
            if child:
                pending_children.append(child)
        elif pending_field and not line.strip():
            if pending_children:
                joined = "; ".join(pending_children)
                existing = fields.get(pending_field, "")
                fields[pending_field] = (
                    f"{existing}; {joined}" if existing and joined else (existing or joined)
                )
            pending_field = None
            pending_children = []
    if pending_field and pending_children:
        joined = "; ".join(pending_children)
        existing = fields.get(pending_field, "")
        fields[pending_field] = (
            f"{existing}; {joined}" if existing and joined else (existing or joined)
        )
    return fields


def _apply_claim_type_rules(row: dict, schema: dict, row_idx: int) -> list[str]:
    """Apply A59-style ``x-bsa-claim-type-rules`` extension against a row.

    The per-row JSON Schema catches shape-level violations (unknown
    ClaimType enum value, malformed field patterns) but cannot express
    the cross-field rules INV-01 + INV-07 declare:

    * ``ClaimType=direct``    → ExcerptID non-empty OR A51Ref non-empty.
    * ``ClaimType=inference`` → same rule as direct (INV-01 scope).
    * ``ClaimType=analyst_judgment`` → JustificationRationale non-empty
      (A51Ref irrelevant here; INV-07 carries the provenance instead).

    Returns one message per violation. Empty-list means no cross-field
    issue for this row.

    Scope: Sprint-5 v1.0.2 C2 fix. The rule reader is generic enough
    to apply to any schema that declares ``x-bsa-claim-type-rules``
    with the same shape (``ClaimType`` keys → dict with
    ``requires_non_empty`` list + optional ``or_a51ref_set`` bool).
    """
    rules = schema.get("x-bsa-claim-type-rules", {})
    # v1.0.4+1 polish: defensive isinstance guard. A malformed schema
    # could have `x-bsa-claim-type-rules: "please enforce"` (truthy
    # non-dict) — the bare truthiness check would pass and the
    # downstream `.get(...)` would AttributeError. Treat malformed
    # shapes as no-op (silently skip the cross-field check); the
    # JSON Schema layer will not flag the extension shape itself
    # because $-extensions are advisory to JSON Schema validators.
    if not isinstance(rules, dict) or not rules:
        return []
    claim_type = (row.get("ClaimType") or "").strip()
    rule = rules.get(claim_type)
    if not isinstance(rule, dict):
        # Unknown ClaimType value — JSON Schema already flags it; no
        # duplicate violation here.
        return []
    requires = rule.get("requires_non_empty", [])
    or_a51 = bool(rule.get("or_a51ref_set", False))
    a51_ref = (row.get("A51Ref") or "").strip()
    violations: list[str] = []
    for field in requires:
        if (row.get(field) or "").strip():
            continue
        if or_a51 and a51_ref:
            continue  # A51Ref alternative satisfies the OR branch.
        reason = f"{field} is empty"
        if or_a51:
            reason += " AND A51Ref is empty"
        violations.append(
            f"line {row_idx} ClaimType={claim_type!r}: {reason} "
            f"(x-bsa-claim-type-rules → requires_non_empty={requires}"
            + (f", or_a51ref_set=true" if or_a51 else "")
            + ")"
        )
    return violations


def _apply_measurability_rules(row: dict, schema: dict, row_idx: int) -> list[str]:
    """Apply A62-style ``x-bsa-measurability-rules`` extension against a row.

    v1.0.3 polish — C2 pattern applied to A62 NFR register (Phase 3).

    The per-row JSON Schema catches NFRCategory enum violations and
    empty-string guards on TestabilityNotes, but cannot express INV-09:
    measurable NFR categories (performance / availability / scalability)
    MUST either carry a concrete Metric + Target pair OR be routed
    through A51 as an explicit decision_needed. Without executable
    enforcement, an LLM can emit

        NFR-PERF-001,performance,"Fast please.",C-042,quantitative,,,"load test",level-1,,

    where Metric and Target are blank and no A51Ref guards the gap —
    the NFR is aspirational, not a requirement.

    Returns one message per violation. Empty list means no cross-field
    issue for this row.
    """
    ext = schema.get("x-bsa-measurability-rules", {})
    # v1.0.4+1 polish: see _apply_claim_type_rules for rationale.
    if not isinstance(ext, dict) or not ext:
        return []
    required_categories = ext.get(
        "quantitative_categories_requiring_metric_and_target", []
    )
    if not required_categories:
        return []
    category = (row.get("NFRCategory") or "").strip()
    if category not in required_categories:
        return []
    metric = (row.get("Metric") or "").strip()
    target = (row.get("Target") or "").strip()
    a51_ref = (row.get("A51Ref") or "").strip()
    # Valid shapes: (Metric AND Target both filled) OR A51Ref filled
    # (explicit decision_needed for the gap).
    if metric and target:
        return []
    if a51_ref:
        return []
    return [
        f"line {row_idx} NFRCategory={category!r}: requires non-empty Metric AND Target, "
        f"OR non-empty A51Ref routing the measurability gap. "
        f"Got Metric={metric!r}, Target={target!r}, A51Ref={a51_ref!r}. "
        f"(x-bsa-measurability-rules → "
        f"quantitative_categories_requiring_metric_and_target={required_categories})"
    ]


def _apply_provenance_rules(row: dict, schema: dict, row_idx: int) -> list[str]:
    """Apply A70-style ``x-bsa-provenance-rules`` extension against a row.

    v1.0.3 polish — C2 pattern applied to A70 story register (Phase 3).

    Rule shape: ``at_least_one_of_non_empty`` list names fields that
    must have at least one non-empty value among them. For A70, this
    is INV-08 (story provenance): SourceClaimIDs OR RelatedNFRIDs
    must be non-empty so every story traces back to a claim or NFR.
    Without executable enforcement, an LLM can emit stories authored
    from thin air with both provenance fields empty.

    Generic: any schema declaring ``x-bsa-provenance-rules`` with an
    ``at_least_one_of_non_empty`` list gets the same treatment.
    """
    ext = schema.get("x-bsa-provenance-rules", {})
    # v1.0.4+1 polish: see _apply_claim_type_rules for rationale.
    if not isinstance(ext, dict) or not ext:
        return []
    any_of = ext.get("at_least_one_of_non_empty", [])
    if not any_of:
        return []
    filled = [f for f in any_of if (row.get(f) or "").strip()]
    if filled:
        return []
    return [
        f"line {row_idx}: all of {any_of} are empty — "
        f"at least one must be non-empty "
        f"(x-bsa-provenance-rules → at_least_one_of_non_empty)"
    ]


def _apply_invest_rules(row: dict, schema: dict, row_idx: int) -> list[str]:
    """Apply A70-style ``x-bsa-invest-rules`` extension against a row.

    v1.0.3 polish — C2 pattern applied to A70 story register (Phase 3).

    Rule shape: ``requires_a51_when_status_not_pass`` bool. When set,
    any row whose ``INVESTStatus`` is not exactly ``pass`` MUST carry
    a non-empty ``A51Ref`` so the deferred-INVEST decision / action is
    tracked in the register rather than silently stuck. Documentary
    pre-v1.0.3; executable now.

    If ``INVESTStatus`` is empty or not in the enum (malformed row),
    JSON Schema catches that upstream; this handler bails silently.
    """
    ext = schema.get("x-bsa-invest-rules", {})
    # v1.0.4+1 polish: see _apply_claim_type_rules for rationale.
    if not isinstance(ext, dict) or not ext.get("requires_a51_when_status_not_pass"):
        return []
    status = (row.get("INVESTStatus") or "").strip()
    if not status or status == "pass":
        return []  # pass or missing — other handlers / JSON Schema cover the empty case
    a51_ref = (row.get("A51Ref") or "").strip()
    if a51_ref:
        return []
    return [
        f"line {row_idx} INVESTStatus={status!r}: A51Ref is empty — "
        f"INVEST-deferred rows MUST co-populate A51Ref so the decision path is tracked "
        f"(x-bsa-invest-rules → requires_a51_when_status_not_pass)"
    ]


def _make_csv_validator(schema_name: str) -> Callable[[str, str], list[str]]:
    """Build a CSV-row validator for the named schema.

    Validation order per row:
      1. Column-set sanity (set equality against x-bsa-csv-columns-order).
      2. JSON Schema shape check (every field matches pattern/enum/etc.).
      3. Cross-field x-bsa-*-rules (v1.0.2 C2): currently
         x-bsa-claim-type-rules for A59 (INV-01 + INV-07 executable
         enforcement). Documentary-only invariants become mechanical.

    Path argument is accepted for uniformity with the dispatcher
    signature but not used by CSV validators (per-row checks are
    path-independent; future path-aware CSV rules can reuse the slot).
    """

    def _validate(path: str, content: str) -> list[str]:
        import jsonschema  # lazy
        del path  # not used for CSV validation in this iteration

        schema = _loader.load_schema(schema_name)
        expected = schema["x-bsa-csv-columns-order"]["order"]
        validator = jsonschema.Draft202012Validator(schema)
        violations: list[str] = []
        try:
            reader = csv.DictReader(io.StringIO(content))
            actual = set(reader.fieldnames or [])
            expected_set = set(expected)
            if actual != expected_set:
                missing = sorted(expected_set - actual)
                extra = sorted(actual - expected_set)
                if missing:
                    violations.append(f"<columns>: missing required columns: {missing}")
                if extra:
                    violations.append(f"<columns>: unexpected columns: {extra}")
                # Continue to row-level even on column mismatch — many
                # missing cells will surface meaningful per-row errors too.
            for row_idx, row in enumerate(reader, start=2):  # +2 for header
                # Drop the None key DictReader inserts on column-mismatched rows.
                row = {k: v for k, v in row.items() if k is not None}
                for err in sorted(validator.iter_errors(row), key=lambda e: list(e.absolute_path)):
                    field = ".".join(str(p) for p in err.absolute_path) or "<row>"
                    violations.append(f"line {row_idx} {field}: {err.message}")
                # Cross-field extension rules. Each helper no-ops
                # when the schema doesn't declare its extension, so
                # this pass is schema-agnostic: new schemas that adopt
                # an existing extension shape get enforcement for free.
                #   x-bsa-claim-type-rules (A59): INV-01 + INV-07
                #   x-bsa-measurability-rules (A62, v1.0.3): INV-09 seed
                #   x-bsa-provenance-rules (A70, v1.0.3): INV-08 seed
                #   x-bsa-invest-rules (A70, v1.0.3): INVEST-A51 coupling
                # All four follow the C2 pattern: read extension,
                # apply per-row, emit line-numbered message on failure.
                violations.extend(_apply_claim_type_rules(row, schema, row_idx))
                violations.extend(_apply_measurability_rules(row, schema, row_idx))
                violations.extend(_apply_provenance_rules(row, schema, row_idx))
                violations.extend(_apply_invest_rules(row, schema, row_idx))
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
