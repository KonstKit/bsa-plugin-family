"""Marker / Jira-export / live-API-response / A48 validators (v1.3.9 split).

Extracted from `governance/schemas/write_validator.py` in v1.3.9 — the
god-module decomposition closes review finding #4. The four validators
in this module dispatch on file path via the table in `write_validator.py`'s
`_DISPATCHER`:

  * `_validate_marker_json`            → `analysis/{,discovery/}runtime/ready/*.json`
  * `_validate_jira_export_json`       → `analysis/handoff/backlog_export_jira.json`
  * `_validate_live_api_response_json` → `analysis/handoff/live_api_response_*.json`
  * `_validate_a48_markdown`           → `analysis/canonical/core_controls/A48_*.md`

Plus two helpers used by the marker validator:

  * `_expected_stage_verdict(marker_id)` — derives the (stage, verdict)
    pair implied by a marker_id (H-sec-4 binding check).
  * `_parse_a48_string(text)` — in-string A48 parser mirroring
    `loader.parse_a48` (file-IO-free for hook-time validation).

`jsonschema` is imported lazily inside each validator so the module
can be imported by callers that only need the helpers without paying
the jsonschema-import cost.

Backward compat: `write_validator.py` re-exports every public name
from this module so the historical caller surface stays unchanged.
"""

from __future__ import annotations

import json
import re
from pathlib import PurePosixPath

from . import loader as _loader


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
