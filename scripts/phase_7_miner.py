#!/usr/bin/env python3
"""Phase 7 L1b miner skeleton (v1.2.18).

Reads telemetry snapshots from `analysis/telemetry/run_*.json` (produced
by `scripts/phase_7_telemetry_collector.py` v1.2.4), filters them to a
rolling window, and emits a proposal bundle to
`analysis/telemetry/miner_proposals.json`.

**v1.2.18 ships the SKELETON ONLY** — the mining algorithm itself is a
stub that always returns an empty `proposals` array. Real pattern
detection / statistical-significance gating lands in a future release
once enough pilot telemetry exists. The skeleton's value is:

  1. Establishes the proposal-bundle shape (schema + writer).
  2. Wires the window-filter + telemetry-validity logic so future
     algorithm work plugs in via a single `_mine_proposals` function.
  3. Lets v1.2.19 (L2 auto-patcher) consume the bundle today using
     synthetic empty bundles for testing, ahead of the real algo.

Schema: `governance/schemas/miner_proposal.schema.json` (v1.0).

Pattern mirrors `scripts/phase_7_telemetry_collector.py` (v1.2.4) and
`scripts/freshness_audit.py` (v1.2.16):
- Stdlib-only.
- Defensive JSON reads — malformed files counted but never raise.
- Atomic JSON write via tempfile + os.replace.
- `--print-only` / `--quiet` / `--workspace` / `--telemetry-dir` /
  `--window-days` / `--today` / `--output-path` CLI flags.
- Operator-invoked. NOT canonical state. NOT in POLICY_GLOBS.

Stdlib-only.

CLI:
  scripts/phase_7_miner.py --workspace <path>
  scripts/phase_7_miner.py --workspace <path> --window-days 7
  scripts/phase_7_miner.py --workspace <path> --today 2026-04-25
  scripts/phase_7_miner.py --workspace <path> --print-only
  scripts/phase_7_miner.py --telemetry-dir tests/fixtures/telemetry/

Exit codes:
  0 — bundle generated (zero or more proposals — stub always emits 0).
  2 — invocation error (workspace not initialized, malformed flag,
      telemetry dir missing when explicitly overridden).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import date, datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SCHEMA_VERSION = "1.0"
DEFAULT_WINDOW_DAYS = 30
DEFAULT_TELEMETRY_REL = "analysis/telemetry"
DEFAULT_OUTPUT_FILENAME = "miner_proposals.json"

# Telemetry-run files match `run_*.json` per the v1.2.4 collector
# convention. Stable prefix lets the miner enumerate without
# accidentally pulling in the proposal bundle itself.
_TELEMETRY_GLOB = "run_*.json"

# Required telemetry-run top-level fields (per
# governance/schemas/telemetry_run.schema.json). We do a lightweight
# shape check rather than a full jsonschema validation to keep the
# miner stdlib-only and fast.
_TELEMETRY_REQUIRED_FIELDS = (
    "schema_version",
    "captured_at",
    "run_id",
    "plugin_version",
    "canon_policy_version",
    "kpi_observations",
    "summary",
)


# ---- Helpers --------------------------------------------------------


def _parse_captured_at(raw: str) -> date | None:
    """Parse a telemetry run's `captured_at` (ISO-8601 UTC) into a
    UTC calendar date. Returns None on malformed input.

    The collector emits `YYYY-MM-DDTHH:MM:SSZ` (no fractional / no
    offset). We accept that shape strictly; anything else returns
    None so the run gets counted as malformed.
    """
    if not isinstance(raw, str) or len(raw) < 20:
        return None
    try:
        # strptime with %Z doesn't accept 'Z' on Py3.9; strip the 'Z'
        # explicitly and treat as UTC.
        if not raw.endswith("Z"):
            return None
        parsed = datetime.strptime(raw[:-1], "%Y-%m-%dT%H:%M:%S")
        return parsed.date()
    except ValueError:
        return None


def _validate_telemetry_shape(doc: object) -> bool:
    """Lightweight shape check for a telemetry-run document. Returns
    True iff `doc` is a dict with all required top-level fields
    present AND `captured_at` + `run_id` are strings.

    This is NOT a full jsonschema validation against
    `telemetry_run.schema.json` — the miner stays stdlib-only by
    deliberately checking only the fields it consumes. Callers who
    want the full validation should run `jsonschema` against the
    snapshot before invoking the miner. A doc that passes this check
    but would fail full schema validation (e.g., a malformed
    `kpi_observations` block) is treated as in-bounds for the miner's
    window arithmetic — only `captured_at` parseability matters here,
    and that is checked separately during window filtering (failures
    there are folded back into the malformed bucket)."""
    if not isinstance(doc, dict):
        return False
    for field in _TELEMETRY_REQUIRED_FIELDS:
        if field not in doc:
            return False
    if not isinstance(doc.get("captured_at"), str):
        return False
    if not isinstance(doc.get("run_id"), str):
        return False
    return True


def _load_telemetry_runs(
    telemetry_dir: Path,
) -> tuple[list[dict], int]:
    """Load and shape-check every `run_*.json` in telemetry_dir.

    Returns (valid_docs, malformed_count). Files that don't parse as
    JSON OR whose shape fails `_validate_telemetry_shape` are counted
    as malformed; the rest are returned in the order they were
    discovered (sorted by filename for determinism)."""
    if not telemetry_dir.is_dir():
        return [], 0
    valid: list[dict] = []
    malformed = 0
    for path in sorted(telemetry_dir.glob(_TELEMETRY_GLOB)):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            malformed += 1
            continue
        if not _validate_telemetry_shape(doc):
            malformed += 1
            continue
        valid.append(doc)
    return valid, malformed


def _filter_by_window(
    runs: list[dict],
    today_utc: date,
    window_days: int,
) -> tuple[list[dict], int, int]:
    """Split valid runs into (in_window, outside_window_count, parse_failed_count).

    A run is in-window iff its `captured_at` parses to a UTC date in
    `(today_utc - window_days, today_utc]`. The lower bound is OPEN
    (strictly greater than) so a window of 30 days means "the last 30
    days, not including the date that's exactly 30 days ago" — this
    matches the standard rolling-window convention. Future-dated runs
    (captured_at > today_utc) are excluded as out-of-window — in
    production today_utc is real and a future-dated capture is a clock-
    skew bug worth isolating from the analysis but not classifying as
    "malformed data".

    Runs whose `captured_at` doesn't parse as `YYYY-MM-DDTHH:MM:SSZ`
    (e.g., `+02:00` offsets, fractional seconds, missing-Z forms) are
    classified as **malformed** — they're not "outside the window",
    they're broken inputs that the lightweight shape check let through
    because it only verified the field is a string. R1 fix: previously
    these were lumped into outside_window which misled operators
    debugging rejected timestamps. The third return value is the count
    of such parse-failed runs so the caller can fold them into the
    malformed bucket alongside JSON / shape failures."""
    in_window: list[dict] = []
    outside_window = 0
    parse_failed = 0
    for r in runs:
        captured = _parse_captured_at(r.get("captured_at", ""))
        if captured is None:
            parse_failed += 1
            continue
        delta_days = (today_utc - captured).days
        if delta_days < 0:
            outside_window += 1  # future-dated
            continue
        if delta_days >= window_days:
            outside_window += 1  # older than window
            continue
        in_window.append(r)
    return in_window, outside_window, parse_failed


def _mine_proposals(in_window_runs: list[dict]) -> list[dict]:
    """STUB algorithm (v1.2.18). Always returns [].

    Real pattern detection / statistical-significance gating lands in
    a future release once enough pilot telemetry exists. The function
    signature is the integration point: a future implementation
    consumes the in-window runs and returns 0+ proposal dicts that
    validate against `governance/schemas/miner_proposal.schema.json`
    `$defs/proposal`.

    The stub return shape is deliberate so v1.2.19 (L2 auto-patcher)
    can be developed against an empty-bundle baseline today, ahead of
    the real algorithm."""
    return []


def build_bundle(
    workspace: Path,
    *,
    telemetry_dir: Path | None = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
    today_utc: date | None = None,
) -> dict:
    """Build the full miner-proposal bundle dict (schema-conformant).

    Window default 30 days. `today_utc=None` resolves to
    datetime.now(tz=UTC).date(). `telemetry_dir=None` resolves to
    `workspace/analysis/telemetry/`.
    """
    if today_utc is None:
        today_utc = datetime.now(tz=timezone.utc).date()
    if telemetry_dir is None:
        telemetry_dir = workspace / DEFAULT_TELEMETRY_REL

    valid_runs, shape_malformed_count = _load_telemetry_runs(telemetry_dir)
    in_window, outside_window, parse_failed_count = _filter_by_window(
        valid_runs, today_utc, window_days
    )
    # R1 fix: parse-failed captured_at IS malformed input (not "outside
    # window"). Fold it into the malformed bucket so operators
    # debugging rejected timestamps see the right number.
    malformed_count = shape_malformed_count + parse_failed_count
    proposals = _mine_proposals(in_window)

    immutable_conflict_count = sum(
        1 for p in proposals if p.get("immutable_conflict") is True
    )

    generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "window": {
            "window_days": window_days,
            "today_utc": today_utc.isoformat(),
        },
        "summary": {
            "runs_total": len(valid_runs) + shape_malformed_count,
            "runs_in_window": len(in_window),
            "runs_excluded_outside_window": outside_window,
            "runs_excluded_malformed": malformed_count,
            "proposals_count": len(proposals),
            "proposals_immutable_conflict_count": immutable_conflict_count,
        },
        "proposals": proposals,
    }


# ---- Atomic write ---------------------------------------------------


def write_bundle(target_path: Path, bundle: dict) -> None:
    """Atomic JSON write (mirrors freshness_audit + telemetry collector
    pattern: tempfile in the same dir + os.replace)."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=target_path.parent,
        prefix=".miner_proposals_",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(bundle, fh, indent=2)
        os.replace(tmp, target_path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---- CLI ------------------------------------------------------------


def _parse_today_arg(s: str) -> date:
    """Parse YYYY-MM-DD strictly (mirrors freshness_audit's strict
    parser — anchored to ASCII [0-9], no Unicode-digit slip)."""
    if len(s) != 10 or s[4] != "-" or s[7] != "-":
        raise argparse.ArgumentTypeError(
            f"--today expects YYYY-MM-DD, got {s!r}"
        )
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"--today expects YYYY-MM-DD, got {s!r}: {exc}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 7 L1b miner skeleton (v1.2.18). Reads telemetry "
            "snapshots, filters by window, emits proposal bundle. "
            "Stub algorithm — always returns empty proposals; real "
            "pattern detection lands in a future release."
        ),
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help=(
            "BSA workspace root (defaults to cwd). Telemetry dir is "
            "<workspace>/analysis/telemetry/ unless overridden via "
            "--telemetry-dir."
        ),
    )
    parser.add_argument(
        "--telemetry-dir",
        type=Path,
        default=None,
        help=(
            "Override the directory the miner reads `run_*.json` from. "
            "Useful for ad-hoc fixture-based runs (e.g., "
            "`--telemetry-dir tests/fixtures/telemetry/`) without an "
            "initialized BSA workspace."
        ),
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=DEFAULT_WINDOW_DAYS,
        help=(
            f"Rolling window in days (default {DEFAULT_WINDOW_DAYS}). "
            f"Telemetry runs older than (today - window_days) are "
            f"excluded from analysis."
        ),
    )
    parser.add_argument(
        "--today",
        type=_parse_today_arg,
        default=None,
        help=(
            "Override today's UTC date (YYYY-MM-DD). Test-only knob — "
            "production runs let the miner pick "
            "datetime.now(tz=UTC).date()."
        ),
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=None,
        help=(
            f"Override the output path (default <workspace>/"
            f"{DEFAULT_TELEMETRY_REL}/{DEFAULT_OUTPUT_FILENAME})."
        ),
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Print bundle JSON to stdout instead of writing.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-summary log line.",
    )
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.window_days < 1:
        print(
            f"phase_7_miner: --window-days must be >= 1, "
            f"got {args.window_days}",
            file=sys.stderr,
        )
        return 2

    workspace = args.workspace.resolve()
    # Workspace check applies only when telemetry-dir is not explicitly
    # overridden — fixture-based runs don't need a BSA workspace.
    if args.telemetry_dir is None:
        if not (workspace / "analysis").is_dir():
            print(
                f"phase_7_miner: workspace {workspace} is not "
                f"initialized (no analysis/ directory). Run "
                f"/bsa-start first OR pass --telemetry-dir explicitly.",
                file=sys.stderr,
            )
            return 2
        telemetry_dir = workspace / DEFAULT_TELEMETRY_REL
    else:
        telemetry_dir = args.telemetry_dir.resolve()
        # R1 fix: an explicit --telemetry-dir typo previously slipped
        # through as exit 0 + empty bundle (because _load_telemetry_runs
        # treats missing dir as empty input). That's fail-open and
        # masks operator typos as "zero telemetry". When the operator
        # explicitly named a directory, validate that the directory
        # actually exists; the implicit (workspace-derived) path
        # remains permissive (an uninitialized telemetry/ subdir is a
        # legitimate "no runs captured yet" state, not a typo).
        if not telemetry_dir.is_dir():
            print(
                f"phase_7_miner: --telemetry-dir {telemetry_dir} does "
                f"not exist or is not a directory. (An implicit "
                f"workspace-derived telemetry/ that doesn't exist yet "
                f"is permissive; an explicit path that doesn't exist "
                f"is a typo and rejected.)",
                file=sys.stderr,
            )
            return 2

    bundle = build_bundle(
        workspace,
        telemetry_dir=telemetry_dir,
        window_days=args.window_days,
        today_utc=args.today,
    )

    if args.print_only:
        print(json.dumps(bundle, indent=2))
        return 0

    output_path = args.output_path or (
        workspace / DEFAULT_TELEMETRY_REL / DEFAULT_OUTPUT_FILENAME
    )
    write_bundle(output_path, bundle)

    if not args.quiet:
        s = bundle["summary"]
        w = bundle["window"]
        print(
            f"phase_7_miner: wrote {output_path}\n"
            f"  window: {w['window_days']} days ending {w['today_utc']}\n"
            f"  runs: {s['runs_total']} total / "
            f"{s['runs_in_window']} in window / "
            f"{s['runs_excluded_outside_window']} outside / "
            f"{s['runs_excluded_malformed']} malformed\n"
            f"  proposals: {s['proposals_count']} "
            f"({s['proposals_immutable_conflict_count']} immutable-conflict)\n"
            f"  NOTE: v1.2.18 ships the skeleton — algorithm is a stub "
            f"(always 0 proposals)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
