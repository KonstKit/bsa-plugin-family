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
        # Phase-3 terminal markers (Sprint 9 US-S9-01..05). Don't fit
        # the `^phase3\.([a-z_]+)\.pass$` patterned-match because
        # neither ends in `.pass`; both get explicit EXACT entries.
        "phase3.backlog_exported": ("phase3.backlog", "PASS"),
        "pipeline.phase3.complete": ("phase3.complete", "PASS"),
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
    # Phase-3 markers (Sprint 6+, US-S8-01 round-3 fix). For
    # `phase3.<sub>.pass`, the implied stage is `phase3.<sub>` (the
    # marker.schema.json stage enum carries phase3.nfr / phase3.story
    # / phase3.test_scenario). Pre-fix, these markers passed H-sec-4
    # without stage/verdict binding, so e.g.
    # phase3.test_scenario.pass.json could carry stage="stage1",
    # verdict="READY" and the H-sec-4 check would say nothing —
    # only the schema-enum check flagged stage drift.
    m = re.match(r"^phase3\.([a-z_]+)\.pass$", marker_id)
    if m:
        return f"phase3.{m.group(1)}", "PASS"
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


def _validate_jira_export_json(path: str, content: str) -> list[str]:
    """Parse Jira export JSON + validate against backlog_export_jira schema.

    Sprint 9 US-S9-01. The export is structured (top-level object with
    discriminator + issues array), not row-by-row CSV, so it gets its
    own validator instead of `_make_csv_validator`. Schema enforces
    the discriminator (`export_format` must be exactly 'jira'), the
    Jira REST v3 issue shape, and the BSA provenance block on every
    issue. Path argument is accepted for dispatcher signature but
    not used (no path-dependent bindings)."""
    import jsonschema  # lazy

    del path  # not used for export JSON
    try:
        doc = json.loads(content)
    except json.JSONDecodeError as exc:
        return [f"<json>: invalid JSON — {exc}"]
    schema = _loader.load_schema("backlog_export_jira")
    validator = jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    )
    return [
        f"{'.'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path))
    ]


def _validate_live_api_response_json(path: str, content: str) -> list[str]:
    """Parse live_api_response.json + validate against live_api_response schema.

    Section C v1.1.6, closes TODO-S9-LIVE-API. The response file is
    structured (top-level object with platform discriminator + per-row
    results array), not row-by-row CSV. Schema enforces the platform
    enum, idempotency_key shape, summary cardinality, and security pin
    that no token-shaped strings appear. Mirrors the Jira-export
    validator pattern."""
    import jsonschema  # lazy

    del path  # not used for response JSON
    try:
        doc = json.loads(content)
    except json.JSONDecodeError as exc:
        return [f"<json>: invalid JSON — {exc}"]
    schema = _loader.load_schema("live_api_response")
    validator = jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    )
    violations = [
        f"{'.'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path))
    ]
    # Cross-field invariant: summary.total == created + skipped + failed.
    # Catches arithmetic drift the schema can't easily express via JSON
    # Schema alone (would need conditionals).
    if isinstance(doc, dict) and isinstance(doc.get("summary"), dict):
        s = doc["summary"]
        if all(isinstance(s.get(k), int) for k in ("total", "created", "skipped", "failed")):
            if s["total"] != s["created"] + s["skipped"] + s["failed"]:
                violations.append(
                    f"summary: total ({s['total']}) != created+skipped+failed "
                    f"({s['created']}+{s['skipped']}+{s['failed']}={s['created']+s['skipped']+s['failed']})"
                )
    # Cross-field invariant: results[].status=created MUST carry platform_id.
    if isinstance(doc, dict) and isinstance(doc.get("results"), list):
        for idx, row in enumerate(doc["results"]):
            if not isinstance(row, dict):
                continue
            if row.get("status") == "created" and not (row.get("platform_id") or "").strip():
                violations.append(
                    f"results[{idx}]: status='created' requires non-empty platform_id"
                )
            if row.get("status") == "failed" and not (row.get("last_error") or "").strip():
                violations.append(
                    f"results[{idx}]: status='failed' requires non-empty last_error"
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


def _apply_deferral_rules(row: dict, schema: dict, row_idx: int) -> list[str]:
    """Apply A71-style ``x-bsa-deferral-rules`` extension against a row.

    Sprint 8 US-S8-01 — generalizes the v1.0.3 INVEST-A51 coupling
    pattern (`_apply_invest_rules`) to a configurable status-field
    + deferred-value pair. For A71:

    * field = ``AutomationStatus``
    * deferred value = ``"deferred"``
    * when row[field] == deferred → A51Ref MUST be non-empty.

    The handler reads the rule's ``requires_a51_when_status`` value
    (a string — the specific deferred-state identifier) and the
    ``status_field`` (defaults to a stable per-schema convention; A71
    declares it implicitly via the rule shape). For A71 the
    status_field is hard-coded to ``AutomationStatus`` because the
    schema declaration carries no other plausible field; a future
    schema could add ``"status_field": "..."`` to the rule dict to
    override.

    Defensive isinstance guard (v1.0.4+1 polish pattern): malformed
    extension shape no-ops silently.
    """
    ext = schema.get("x-bsa-deferral-rules", {})
    if not isinstance(ext, dict):
        return []
    deferred_value = ext.get("requires_a51_when_status")
    if not deferred_value:
        return []
    # Status field defaults to AutomationStatus (the only A71 use-site
    # at Sprint 8). Future schemas can override via "status_field".
    status_field = ext.get("status_field", "AutomationStatus")
    status = (row.get(status_field) or "").strip()
    if status != deferred_value:
        return []
    a51_ref = (row.get("A51Ref") or "").strip()
    if a51_ref:
        return []
    return [
        f"line {row_idx} {status_field}={status!r}: A51Ref is empty — "
        f"{deferred_value!r}-state rows MUST co-populate A51Ref so the "
        f"deferral decision is tracked "
        f"(x-bsa-deferral-rules → requires_a51_when_status={deferred_value!r})"
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


# ---- Cross-artifact validators (v1.1.3) -------------------------------
#
# Per-row handlers above only see the row + the schema — they cannot
# reach sibling artifacts. The two handlers below extend the C2 pattern
# to cross-artifact rules: A72 foreign-key resolution + claim/source
# consistency (TODO-S8-02-X-ARTIFACT-FK closed) and A71 NFR-coverage
# enforcement (TODO-S8-01-X-ARTIFACT-NFR-COVERAGE closed). Both rules
# were documentary at the schema layer through v1.1.2 because F5 had
# no sibling-read capability; v1.1.3 adds ``_SiblingArtifactCache`` so
# the handlers can resolve sibling rows at hook time.


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
    """
    import os as _os
    from pathlib import Path as _Path
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
              "optional_when_blank": false,
              "rationale": "Every excerpt must trace to a registered source."
            },
            {
              "column": "SourceClaimIDs",
              "table": "A59_claim_register.csv",
              "target_column": "ClaimID",
              "multi": true,
              "optional_when_blank": true,
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
      A62.SourceClaimIDs / A70.RelatedNFRIDs.
    * ``optional_when_blank`` (optional, default ``false``) — when
      ``true``, a blank cell skips the FK check for that row (the
      schema's required-field check still applies separately). Used
      for fields like A59.SourceID that are non-blank only when
      ``ClaimType in {direct, inference}``.

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
        optional = bool(fk.get("optional_when_blank", False))

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
                # Blank cell — skip regardless of optional_when_blank.
                # The optional flag gates what the handler does when
                # the cell IS blank; here we simply note that a blank
                # FK can't resolve, and the schema's required-field
                # check (or the per-row rules like _apply_claim_type_
                # rules) handles the "must be non-blank" case.
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
        expected = schema["x-bsa-csv-columns-order"]["order"]
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
