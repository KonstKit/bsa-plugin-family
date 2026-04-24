#!/usr/bin/env python3
"""Phase 7 telemetry collector skeleton (v1.2.4, P1+P2).

Captures one snapshot of the workspace's KPI observations + writes
to `analysis/telemetry/run_<run_id>.json`. Per-snapshot file conforms
to `governance/schemas/telemetry_run.schema.json` (P1 / v1.2.4 ships
the schema; P2 / v1.2.4 ships this collector).

NOT canonical state. NOT F5-validated. NOT in POLICY_GLOBS. The
collector is observation-only — it never modifies canonical artifacts,
never proposes tunable changes (that's L1 / future), never auto-fires
(operator-invoked).

KPIs captured today (v1.2.4):
  * KPI-001 weighted: sum(ClaimStrength for direct claims with bound
    SourceID+ExcerptID) / count(direct claims). Target ≥ 0.75 per
    skills/bsa-evidence-intake/references/reliability_tier_spec.md.
  * KPI-006: |A70 stories with at least one direct A72 row| /
    |A70 stories|. Target ≥ 0.90 per skills/bsa-traceability-matrix/SKILL.md.

Optional captures:
  * `validator_observations` — per-validator pass/fail/warn counts.
    v1.2.4 doesn't auto-populate (the validator output isn't structured
    in a way the collector can scan); future Phase 7 L1 work will add
    a marker-emission convention so the collector can read counts
    deterministically.
  * `threshold_trigger_counts` — count of times each tunable threshold
    fired. v1.2.4 ships the field shape; populating it is L1 work.

Future Phase 7 L1 work (v1.2.x+) will:
  * Aggregate snapshots across N runs.
  * Detect tunable-knob drift (e.g., KPI-001 consistently at 0.82
    when target is 0.75 → tighten target).
  * Emit tuning-patch proposals against config/tunables.yaml.

Stdlib-only.

CLI:
  scripts/phase_7_telemetry_collector.py --workspace <path>
  scripts/phase_7_telemetry_collector.py --workspace <path> \\
      --run-id my-pilot-run-2026-04
  scripts/phase_7_telemetry_collector.py --workspace <path> \\
      --output-path custom/path/telemetry.json

Exit codes:
  0 — snapshot captured (zero or more KPI values; null values OK
      when the upstream artifact is absent).
  2 — invocation error (missing workspace, malformed canonical CSV,
      etc.).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

SCHEMA_VERSION = "1.0"
DEFAULT_OUTPUT_DIR = "analysis/telemetry"

# Canonical artifact paths (mirror a72_incremental_diff conventions).
A50_REL = "analysis/canonical/core_controls/A50_source_register.csv"
A59_REL = "analysis/canonical/core_controls/A59_claim_register.csv"
A70_REL = "analysis/canonical/core_controls/A70_story_register.csv"
A72_REL = "analysis/canonical/core_controls/A72_traceability_matrix.csv"

# KPI defaults (read from canonical references; v1.2.4 hardcodes the
# documented v1.1.x values to avoid coupling the collector to the
# tunables.yaml inventory at runtime).
KPI_001_TARGET = 0.75
KPI_006_TARGET = 0.90


@dataclass
class KPIObservation:
    value: float | None
    target: float
    comparison: str
    status: str  # at_target | below_target | n/a
    numerator: float | int | None = None
    denominator: float | int | None = None

    def to_dict(self) -> dict:
        out: dict = {
            "value": self.value, "target": self.target,
            "comparison": self.comparison, "status": self.status,
        }
        if self.numerator is not None:
            out["numerator"] = self.numerator
        if self.denominator is not None:
            out["denominator"] = self.denominator
        return out


# ---- KPI computation -------------------------------------------------


def _read_csv_rows(path: Path) -> list[dict]:
    """Defensive CSV read — returns [] if missing/malformed."""
    if not path.is_file():
        return []
    try:
        with path.open(newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    except (OSError, csv.Error):
        return []


def _safe_float(s: str) -> float | None:
    try:
        return float(s.strip()) if s and s.strip() else None
    except (ValueError, AttributeError):
        return None


def compute_kpi_001_weighted(workspace: Path) -> KPIObservation:
    """KPI-001 weighted formula (post-Sprint-3):
        KPI-001 = sum(ClaimStrength for direct claims with
                      bound SourceID+ExcerptID) /
                  count(all direct claims)
    Per skills/bsa-evidence-intake/references/reliability_tier_spec.md
    line 142. Target >= 0.75.

    Returns null value when A59 is absent (pre-Stage-1 run)."""
    rows = _read_csv_rows(workspace / A59_REL)
    if not rows:
        return KPIObservation(
            value=None, target=KPI_001_TARGET, comparison=">=",
            status="n/a",
        )
    direct_rows = [r for r in rows if (r.get("ClaimType") or "").strip() == "direct"]
    if not direct_rows:
        # No direct claims → KPI-001 is mathematically n/a.
        return KPIObservation(
            value=None, target=KPI_001_TARGET, comparison=">=",
            status="n/a", numerator=0, denominator=0,
        )
    numerator = 0.0
    for r in direct_rows:
        source_id = (r.get("SourceID") or "").strip()
        excerpt_id = (r.get("ExcerptID") or "").strip()
        if source_id and excerpt_id:
            cs = _safe_float(r.get("ClaimStrength", ""))
            if cs is not None:
                numerator += cs
    denominator = len(direct_rows)
    value = numerator / denominator if denominator else 0.0
    return KPIObservation(
        value=round(value, 4),
        target=KPI_001_TARGET,
        comparison=">=",
        status="at_target" if value >= KPI_001_TARGET else "below_target",
        numerator=round(numerator, 4),
        denominator=denominator,
    )


def compute_kpi_006_story_coverage(workspace: Path) -> KPIObservation:
    """KPI-006 (Phase-3) — story-to-claim coverage ratio:
        KPI-006 = |A70 stories with at least one direct A72 row| /
                  |A70 stories|
    Per skills/bsa-traceability-matrix/SKILL.md line 71. Target >= 0.90.

    Returns null when either A70 or A72 is absent."""
    a70 = _read_csv_rows(workspace / A70_REL)
    a72 = _read_csv_rows(workspace / A72_REL)
    # v1.2.4 round-1 (Codex CRITICAL): KPI-006 requires BOTH A70 + A72
    # to be readable. Earlier impl only guarded on A70 — when A72 was
    # missing but A70 existed, direct_story_ids was {} and the
    # ratio fell through as `value=0.0, status=below_target`,
    # falsely signalling that the workspace failed coverage when the
    # actual fact is that the upstream traceability artifact wasn't
    # built yet. Now both inputs gate the n/a verdict.
    if not a70 or not a72:
        return KPIObservation(
            value=None, target=KPI_006_TARGET, comparison=">=",
            status="n/a",
        )
    # Stories with at least one direct A72 row.
    direct_story_ids = {
        (r.get("StoryID") or "").strip()
        for r in a72
        if (r.get("LinkType") or "").strip() == "direct"
        and (r.get("StoryID") or "").strip()
    }
    a70_story_ids = {
        (r.get("StoryID") or "").strip()
        for r in a70 if (r.get("StoryID") or "").strip()
    }
    if not a70_story_ids:
        return KPIObservation(
            value=None, target=KPI_006_TARGET, comparison=">=",
            status="n/a", numerator=0, denominator=0,
        )
    covered = a70_story_ids & direct_story_ids
    value = len(covered) / len(a70_story_ids)
    return KPIObservation(
        value=round(value, 4),
        target=KPI_006_TARGET,
        comparison=">=",
        status="at_target" if value >= KPI_006_TARGET else "below_target",
        numerator=len(covered),
        denominator=len(a70_story_ids),
    )


# ---- Helpers ---------------------------------------------------------


def _read_plugin_version() -> tuple[str, str]:
    """Returns (manifest_version, canon_policy_version_full)."""
    manifest_path = REPO_ROOT / ".claude-plugin" / "plugin.json"
    if not manifest_path.is_file():
        return ("0.0.0", "0.0.0")
    try:
        doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ("0.0.0", "0.0.0")
    version = str(doc.get("version", "0.0.0"))
    canon = doc.get("canonPolicyVersion", {})
    canon_full = (
        f"{canon.get('semver', '0.0.0')}+hash:{canon.get('hash_prefix', '00000000')}"
        if isinstance(canon, dict) else "0.0.0"
    )
    return (version, canon_full)


def _generate_run_id() -> str:
    """Auto-generate a run_id when --run-id is not supplied:
    timestamp + 8-char hash of process seed."""
    ts = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    seed = hashlib.sha256(
        f"{time.time_ns()}".encode("utf-8")
    ).hexdigest()[:8]
    return f"run-{ts}-{seed}"


# ---- Snapshot --------------------------------------------------------


def collect_snapshot(
    workspace: Path,
    run_id: str,
    workspace_path_override: str | None = None,
) -> dict:
    """Build the full telemetry-run snapshot dict (schema-conformant)."""
    plugin_version, canon_policy_version = _read_plugin_version()
    captured_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    kpi_001 = compute_kpi_001_weighted(workspace)
    kpi_006 = compute_kpi_006_story_coverage(workspace)
    kpi_observations = {
        "kpi_001_weighted_coverage": kpi_001.to_dict(),
        "kpi_006_story_coverage": kpi_006.to_dict(),
    }

    kpis_captured = len(kpi_observations)
    kpis_at_target = sum(
        1 for k in (kpi_001, kpi_006) if k.status == "at_target"
    )
    kpis_below_target = sum(
        1 for k in (kpi_001, kpi_006) if k.status == "below_target"
    )

    snapshot: dict = {
        "schema_version": SCHEMA_VERSION,
        "captured_at": captured_at,
        "run_id": run_id,
        "plugin_version": plugin_version,
        "canon_policy_version": canon_policy_version,
        "kpi_observations": kpi_observations,
        "summary": {
            "kpis_captured": kpis_captured,
            "kpis_at_target": kpis_at_target,
            "kpis_below_target": kpis_below_target,
        },
    }
    if workspace_path_override is not None:
        snapshot["workspace_path"] = workspace_path_override
    return snapshot


# ---- Atomic write ----------------------------------------------------


def write_snapshot(target_path: Path, snapshot: dict) -> None:
    """Atomic write: tmpfile in same dir + os.replace (matches v1.2.2
    a72_incremental_diff atomicity contract)."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    import tempfile, os
    fd, tmp = tempfile.mkstemp(
        dir=target_path.parent, prefix=".telemetry_run_", suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, indent=2)
        os.replace(tmp, target_path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---- CLI -------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 7 telemetry collector (v1.2.4, P1+P2)",
    )
    parser.add_argument(
        "--workspace", type=Path, default=Path.cwd(),
        help="BSA workspace root (defaults to cwd)",
    )
    parser.add_argument(
        "--run-id", type=str, default=None,
        help="Operator-supplied run identifier (default: auto-generated "
             "from UTC timestamp + 8-char hash). Lowercase alphanumeric "
             "+ hyphen + underscore; 8-64 chars.",
    )
    parser.add_argument(
        "--output-path", type=Path, default=None,
        help="Override output path (default: <workspace>/"
             f"{DEFAULT_OUTPUT_DIR}/run_<run_id>.json).",
    )
    parser.add_argument(
        "--workspace-path-override", type=str, default=None,
        help="Optional `workspace_path` value to record in the snapshot. "
             "Operator-controlled — elide for privacy in regulated runs.",
    )
    parser.add_argument(
        "--print-only", action="store_true",
        help="Print snapshot to stdout instead of writing to disk.",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress per-KPI progress + path-written log.",
    )
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    workspace = args.workspace.resolve()
    if not (workspace / "analysis").is_dir():
        print(
            f"phase_7_telemetry_collector: workspace {workspace} is not "
            f"initialized (no analysis/ directory). Run /bsa-start first.",
            file=sys.stderr,
        )
        return 2

    run_id = args.run_id or _generate_run_id()
    if not re.fullmatch(r"[a-z0-9_\-]{8,64}", run_id):
        print(
            f"phase_7_telemetry_collector: --run-id {run_id!r} does not "
            f"match the schema pattern (lowercase alphanumeric + hyphen "
            f"+ underscore; 8-64 chars).",
            file=sys.stderr,
        )
        return 2

    snapshot = collect_snapshot(
        workspace, run_id, workspace_path_override=args.workspace_path_override,
    )

    if args.print_only:
        print(json.dumps(snapshot, indent=2))
        return 0

    output_path = args.output_path
    if output_path is None:
        output_path = workspace / DEFAULT_OUTPUT_DIR / f"run_{run_id}.json"
    write_snapshot(output_path, snapshot)

    if not args.quiet:
        kpi_001 = snapshot["kpi_observations"]["kpi_001_weighted_coverage"]
        kpi_006 = snapshot["kpi_observations"]["kpi_006_story_coverage"]
        summary = snapshot["summary"]
        print(
            f"phase_7_telemetry_collector: wrote {output_path}\n"
            f"  KPI-001 weighted coverage: value={kpi_001['value']} "
            f"target>={kpi_001['target']} status={kpi_001['status']}\n"
            f"  KPI-006 story coverage:    value={kpi_006['value']} "
            f"target>={kpi_006['target']} status={kpi_006['status']}\n"
            f"  Summary: {summary['kpis_at_target']}/{summary['kpis_captured']} "
            f"KPIs at target ({summary['kpis_below_target']} below)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
