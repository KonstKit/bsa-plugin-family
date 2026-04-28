"""Per-row validation handlers for canonical CSV schemas (v1.3.9 split).

Extracted from `governance/schemas/write_validator.py` in v1.3.9 — the
god-module decomposition closes review finding #4. All six handlers
share the same signature `(row: dict, schema: dict, row_idx: int) ->
list[str]` and are invoked once per data row by `_make_csv_validator`
in `write_validator.py`.

Each handler implements a single `x-bsa-*-rules` schema extension:

  * `_apply_strict_date_rules`         → x-bsa-strict-date-rules     (v1.2.16)
  * `_apply_claim_type_rules`          → x-bsa-claim-type-rules      (v1.0.2 C2)
  * `_apply_measurability_rules`       → x-bsa-measurability-rules   (v1.0.3)
  * `_apply_provenance_rules`          → x-bsa-provenance-rules      (v1.0.3)
  * `_apply_deferral_rules`            → x-bsa-deferral-rules        (Sprint 8 US-S8-01)
  * `_apply_invest_rules`              → x-bsa-invest-rules          (v1.0.3)

Defensive isinstance guards on every extension dict (v1.0.4+1 polish):
malformed extension shapes (`x-bsa-claim-type-rules: "please enforce"`)
no-op silently rather than AttributeError. JSON Schema layer doesn't
validate extension SHAPES (only payload conformance against the
declared schema), so each handler is responsible for its own input
sanity.

Stdlib-only at module level. `datetime` is imported lazily inside
`_apply_strict_date_rules`.

Backward compat: `write_validator.py` re-exports every public name from
this module so the 17+ caller files (tests + scripts) that import
`from governance.schemas.write_validator import _apply_*` continue to
work unchanged.
"""

from __future__ import annotations

import re

# Strict-date rules (v1.2.16 R2).
#
# Module-level constant that the strict-date handler shares with the
# JSON Schema layer's pattern regex; both ASCII-exact YYYY-MM-DD. The
# property's regex catches shape-invalid values (whitespace padding,
# Unicode digits, slashes); this constant catches the SAME shape so
# the handler can short-circuit on values the schema would reject and
# avoid double-reporting.
_STRICT_DATE_SHAPE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def _apply_strict_date_rules(row: dict, schema: dict, row_idx: int) -> list[str]:
    """Apply ``x-bsa-strict-date-rules`` extension (v1.2.16 R2) against a row.

    For each column listed in ``columns``, if the cell is non-empty AND
    not the literal string ``unknown`` AND matches the YYYY-MM-DD shape
    regex, parse it strictly via ``datetime.strptime('%Y-%m-%d')``.
    Emits a violation when the value matches the shape but is not a
    real calendar date (e.g. ``2025-02-30``, ``2025-13-99``).

    Skips:
      * empty string / ``unknown`` — gradual-backfill / cannot-assess
        sentinels (per the schema's property description; freshness
        audit treats them as ``n/a``).
      * shape-invalid values (e.g. ``not-a-date``, ``2025/08/10``) —
        the property's own pattern regex catches these first; emitting
        a second violation here would be redundant noise (R3 fix).

    Generic over schemas: any future schema that adds a date-typed
    column with the same gradual-backfill semantics can opt in by
    declaring ``x-bsa-strict-date-rules.columns: [...]``.
    """
    rules = schema.get("x-bsa-strict-date-rules", {})
    if not isinstance(rules, dict) or not rules:
        return []
    columns = rules.get("columns", [])
    if not isinstance(columns, list):
        return []
    from datetime import datetime as _dt
    violations: list[str] = []
    for col in columns:
        raw = row.get(col)
        if raw is None:
            continue
        # R5 fix: do NOT strip whitespace before the shape check —
        # strip would let `" 2025-02-30 "` (rejected by schema regex
        # for whitespace) reach the handler and produce a redundant
        # second violation. The schema's pattern is anchored ASCII
        # exact; the handler must mirror that reach precisely. Empty
        # / `unknown` skips below use the raw value too so semantics
        # match the schema's literal alternatives.
        val = raw
        if not val or val == "unknown":
            continue
        if not _STRICT_DATE_SHAPE.match(val):
            # Shape-invalid — leave it to the property's regex pattern
            # to flag (avoid double violations on the same cell).
            # Also covers whitespace-padded values, Unicode digits,
            # and case variants of `unknown` — all of which the
            # schema's pattern rejects on its own.
            continue
        try:
            _dt.strptime(val, "%Y-%m-%d").date()
        except ValueError:
            violations.append(
                f"line {row_idx} {col}: invalid calendar date "
                f"{val!r} (regex shape passes but date does not exist)"
            )
    return violations


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
