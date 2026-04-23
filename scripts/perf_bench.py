#!/usr/bin/env python3
"""Performance benchmark harness for the BSA plugin family (v1.1.13, Section F).

Measures hot-path latencies + records a baseline + checks for regressions.
Stdlib-only (matches scripts/security_audit.py + scripts/privacy_scan.py).

Five benchmark categories:

  1. **F5 dispatcher** — `governance.schemas.write_validator._dispatch`
     (per-call regex scan over the dispatcher table). Hot path because
     it fires on EVERY canonical write. Two sub-benchmarks: matching
     path (A59 CSV) + non-matching path (random worker output).

  2. **F5 full validation** — `validate_canonical_write` end-to-end
     on a representative A59 CSV body (~10 rows from project_0001).
     Includes regex match + dispatch + CSV parse + per-row rule fire.

  3. **canon hash** — `scripts/compute_canon_hash.py` end-to-end.
     POLICY_GLOBS scan + sha256 over policy state. Fires per release.

  4. **fixture_runner** — `scripts/fixture_runner.py --all --mode=validate`
     end-to-end. 8 fixtures × intra-fixture invariant checks.
     Fires per CI run (fixture-runner job).

  5. **privacy_scan + security_audit** — both repository-scale scans
     (~436 files each). Run sequentially as a combined "CI scan
     budget" benchmark — fires per CI run (privacy + security jobs).

Each benchmark records p50/p95/p99/min/max/mean across N iterations
(default 30 for fast benches, configurable per-category for slower
ones to keep total wall time <60s).

CLI:
  scripts/perf_bench.py                          # run all + print table
  scripts/perf_bench.py --report=docs/perf_baseline.md   # write doc
  scripts/perf_bench.py --check                  # diff against baseline
  scripts/perf_bench.py --quiet                  # suppress per-bench logs
  scripts/perf_bench.py --category=dispatcher    # run a single bench
  scripts/perf_bench.py --json                   # machine-readable output

Exit codes:
  0 — all benches completed (and on `--check`, no regressions)
  1 — `--check` detected at least one regression > REGRESSION_THRESHOLD
  2 — invocation error (missing baseline doc, malformed args, etc.)

Regression policy:
  * `--check` compares the current p95 against the baseline p95.
  * Threshold: 2.0× (any p95 that's 2x or more above baseline fails).
  * Rationale: avoids noise-driven false positives (system load,
    GC pauses, etc.) while still catching real regressions like
    O(n) → O(n²) drift.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Default iterations per category — picked so total wall time stays <60s
# on a developer laptop. Slower benches get fewer iterations.
DEFAULT_ITERATIONS = {
    "dispatcher": 5000,           # ~µs per call
    "validate_canonical_write": 1000,  # ~ms per call
    "canon_hash": 30,             # ~50ms per call
    "fixture_runner": 10,         # ~100ms per call
    "ci_scan_budget": 5,          # ~800ms per call (privacy + security)
}

# Regression detection threshold — any p95 ≥ baseline × this factor fails.
REGRESSION_THRESHOLD = 2.0

# Where the committed baseline lives.
BASELINE_DOC = REPO_ROOT / "docs" / "perf_baseline.md"


# ---- Bench result types -----------------------------------------------


@dataclass(frozen=True)
class BenchResult:
    """One benchmark's per-iteration measurements + summary stats."""

    name: str
    iterations: int
    samples_ms: tuple[float, ...]

    @property
    def p50(self) -> float:
        return statistics.median(self.samples_ms)

    @property
    def p95(self) -> float:
        return _percentile(self.samples_ms, 0.95)

    @property
    def p99(self) -> float:
        return _percentile(self.samples_ms, 0.99)

    @property
    def mean(self) -> float:
        return statistics.fmean(self.samples_ms)

    @property
    def min(self) -> float:
        return min(self.samples_ms)

    @property
    def max(self) -> float:
        return max(self.samples_ms)


def _percentile(samples: tuple[float, ...], q: float) -> float:
    """Compute the q-th percentile (q in [0,1]) using the nearest-rank
    method, exactly as defined in NIST/SEMATECH e-Handbook §1.3.5.6.

    Algorithm (per NIST):
      1. n = ceil(q * N)
      2. return sorted_samples[n - 1]

    Stdlib's `statistics.quantiles(n=100)` works but is overkill for one
    quantile + uses linear interpolation (different result on small N).
    Nearest-rank is unbiased for this use case (we just want a stable
    high-percentile estimate, not a smoothed estimate).

    v1.1.13 round-1 (Codex): the earlier impl used
    `int(round(q * N + 0.5)) - 1` which is off-by-one whenever q*N is
    an integer (Python's banker's rounding pushes round(95.5) → 96
    on N=100, q=0.95, returning index 95 = sample 96 instead of the
    correct index 94 = sample 95). The all-same-value test fixture
    masked this. Now matches NIST exactly.
    """
    if not samples:
        raise ValueError("cannot compute percentile of empty sample")
    if not 0.0 <= q <= 1.0:
        raise ValueError(f"q must be in [0, 1], got {q!r}")
    sorted_samples = sorted(samples)
    n = len(sorted_samples)
    # NIST nearest-rank: rank = ceil(q * N), 1-indexed → 0-indexed -1.
    # Special case: q=0 → rank=0 (1-indexed) is invalid; clamp to first.
    rank_1indexed = max(1, math.ceil(q * n))
    rank_0indexed = min(rank_1indexed - 1, n - 1)
    return sorted_samples[rank_0indexed]


# ---- Bench primitives -------------------------------------------------


def _time_callable_ms(fn: Callable[[], Any], iterations: int) -> tuple[float, ...]:
    """Run `fn` `iterations` times, return per-iteration wall time in ms.

    Uses time.perf_counter_ns for the highest-resolution monotonic clock
    available. Discards the first iteration as warm-up (Python imports,
    JIT-like first-pass effects, file-cache warmup).
    """
    if iterations < 2:
        raise ValueError("iterations must be >= 2 (one warmup + one measurement)")
    samples: list[float] = []
    # Warmup
    fn()
    for _ in range(iterations):
        t0 = time.perf_counter_ns()
        fn()
        t1 = time.perf_counter_ns()
        samples.append((t1 - t0) / 1_000_000.0)
    return tuple(samples)


# ---- Bench category implementations -----------------------------------


def bench_dispatcher(iterations: int) -> tuple[BenchResult, BenchResult]:
    """F5 dispatcher latency on matching + non-matching paths."""
    from governance.schemas.write_validator import _dispatch
    matching_path = "analysis/canonical/core_controls/A59_claim_register.csv"
    non_matching_path = "analysis/proposals/draft.md"

    def match() -> None:
        _dispatch(matching_path)

    def non_match() -> None:
        _dispatch(non_matching_path)

    return (
        BenchResult(
            name="F5 dispatch (matching path)",
            iterations=iterations,
            samples_ms=_time_callable_ms(match, iterations),
        ),
        BenchResult(
            name="F5 dispatch (non-matching path)",
            iterations=iterations,
            samples_ms=_time_callable_ms(non_match, iterations),
        ),
    )


def bench_validate_canonical_write(iterations: int) -> BenchResult:
    """End-to-end `validate_canonical_write` on a representative A59 body."""
    from governance.schemas.write_validator import validate_canonical_write
    a59_path = (
        REPO_ROOT
        / "fixtures"
        / "golden"
        / "project_0001"
        / "expected_outputs"
        / "canonical"
        / "core_controls"
        / "A59_claim_register.csv"
    )
    body = a59_path.read_text(encoding="utf-8")
    target_path = "analysis/canonical/core_controls/A59_claim_register.csv"

    def call() -> None:
        validate_canonical_write(target_path, body)

    return BenchResult(
        name="validate_canonical_write (A59, ~10 rows)",
        iterations=iterations,
        samples_ms=_time_callable_ms(call, iterations),
    )


def bench_canon_hash(iterations: int) -> BenchResult:
    """End-to-end `compute_canon_hash.py` execution time."""
    script = REPO_ROOT / "scripts" / "compute_canon_hash.py"

    def call() -> None:
        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            cwd=str(REPO_ROOT),
            check=True,
            timeout=30,
        )
        if not result.stdout:
            raise RuntimeError("compute_canon_hash.py produced no output")

    return BenchResult(
        name="compute_canon_hash.py (full POLICY_GLOBS)",
        iterations=iterations,
        samples_ms=_time_callable_ms(call, iterations),
    )


def bench_fixture_runner(iterations: int) -> BenchResult:
    """End-to-end `fixture_runner.py --all --mode=validate` execution time."""
    script = REPO_ROOT / "scripts" / "fixture_runner.py"

    def call() -> None:
        result = subprocess.run(
            [sys.executable, str(script), "--all", "--mode=validate"],
            capture_output=True,
            cwd=str(REPO_ROOT),
            check=True,
            timeout=60,
        )
        if b"finding(s) total" not in result.stdout:
            raise RuntimeError(
                f"fixture_runner.py output unexpected: {result.stdout!r}"
            )

    return BenchResult(
        name="fixture_runner.py --all --mode=validate (8 fixtures)",
        iterations=iterations,
        samples_ms=_time_callable_ms(call, iterations),
    )


def bench_ci_scan_budget(iterations: int) -> BenchResult:
    """Combined privacy_scan + security_audit (per CI run total)."""
    privacy = REPO_ROOT / "scripts" / "privacy_scan.py"
    security = REPO_ROOT / "scripts" / "security_audit.py"

    def call() -> None:
        # privacy_scan.py writes to docs/privacy_audit.md as a side
        # effect — re-running it is idempotent (same output every time).
        # Suppress stdout to keep test logs clean.
        subprocess.run(
            [sys.executable, str(privacy)],
            capture_output=True,
            cwd=str(REPO_ROOT),
            check=True,
            timeout=60,
        )
        # security_audit returns nonzero on findings; we expect the
        # repo to be clean per the CI security-audit job. If something
        # changes, the bench surfaces the discrepancy via timeout/error
        # rather than silently masking it.
        subprocess.run(
            [sys.executable, str(security), "--repo-root", str(REPO_ROOT), "--quiet"],
            capture_output=True,
            cwd=str(REPO_ROOT),
            check=True,
            timeout=60,
        )

    return BenchResult(
        name="privacy_scan + security_audit (CI scan budget)",
        iterations=iterations,
        samples_ms=_time_callable_ms(call, iterations),
    )


# ---- Reporting --------------------------------------------------------


def format_table(results: list[BenchResult]) -> str:
    """Markdown-formatted results table."""
    header = (
        "| Benchmark | Iter | p50 (ms) | p95 (ms) | p99 (ms) | min (ms) | max (ms) | mean (ms) |\n"
        "|---|---:|---:|---:|---:|---:|---:|---:|\n"
    )
    rows = "\n".join(
        f"| {r.name} | {r.iterations} | {r.p50:.4f} | {r.p95:.4f} | "
        f"{r.p99:.4f} | {r.min:.4f} | {r.max:.4f} | {r.mean:.4f} |"
        for r in results
    )
    return header + rows + "\n"


def format_baseline_doc(results: list[BenchResult]) -> str:
    """Full baseline doc body (markdown). Used by `--report=...`."""
    intro = (
        "# Performance Baseline\n\n"
        "Auto-generated by `scripts/perf_bench.py`. Records per-category\n"
        "p50 / p95 / p99 / min / max / mean wall-clock latencies for the\n"
        "five hot-path categories the BSA plugin family ships. Re-run\n"
        "via `python3 scripts/perf_bench.py --report=docs/perf_baseline.md`.\n\n"
        "**Regression policy** (`scripts/perf_bench.py --check`):\n"
        f"any benchmark whose current p95 is ≥ {REGRESSION_THRESHOLD}× the\n"
        "baseline p95 fails the check. The threshold is intentionally\n"
        "loose to avoid noise-driven false positives (system load, GC\n"
        "pauses, file-cache state) while still catching real algorithmic\n"
        "regressions (O(n) → O(n²)).\n\n"
        "**Numbers ARE machine-dependent.** The committed baseline reflects\n"
        "the maintainer's laptop (Apple Silicon, macOS). CI runs on GitHub\n"
        "Actions Linux runners, which are typically 1.5–3× slower per\n"
        "operation. The 2× regression threshold accommodates this.\n\n"
    )
    return intro + "## Latencies\n\n" + format_table(results) + (
        "\n## Categories\n\n"
        "1. **F5 dispatcher** — `_dispatch()` per-call regex scan over the\n"
        "   `_DISPATCHER` table. Fires on EVERY canonical write. The\n"
        "   matching-path bench scans through the table until a regex\n"
        "   matches; the non-matching-path bench scans the entire table\n"
        "   without matching (worst case).\n"
        "2. **validate_canonical_write** — full F5 validation pipeline\n"
        "   on a representative A59 CSV (~10 rows). Fires on every\n"
        "   canonical-CSV write.\n"
        "3. **canon hash** — full `compute_canon_hash.py` run. Fires per\n"
        "   release + per CI run (canon-hash job). Includes Python startup.\n"
        "4. **fixture_runner** — full `fixture_runner.py --all --mode=validate`\n"
        "   run over 8 fixtures. Fires per CI run (fixture-runner job).\n"
        "5. **CI scan budget** — combined `privacy_scan.py` +\n"
        "   `security_audit.py`. Fires per CI run (privacy + security jobs).\n"
    )


def parse_baseline_doc(body: str) -> dict[str, dict[str, float]]:
    """Parse a baseline doc back into a {bench_name: {p50, p95, ...}} dict.

    Used by `--check` to compare current results against the committed
    baseline. Skips the header row + non-table content.
    """
    out: dict[str, dict[str, float]] = {}
    in_table = False
    for line in body.splitlines():
        if line.startswith("| Benchmark |"):
            in_table = True
            continue
        if in_table and line.startswith("|---"):
            continue
        if in_table and line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 8:
                in_table = False
                continue
            try:
                out[cells[0]] = {
                    "iter": float(cells[1]),
                    "p50": float(cells[2]),
                    "p95": float(cells[3]),
                    "p99": float(cells[4]),
                    "min": float(cells[5]),
                    "max": float(cells[6]),
                    "mean": float(cells[7]),
                }
            except ValueError:
                in_table = False
                continue
        elif in_table:
            in_table = False
    return out


# ---- CLI --------------------------------------------------------------


def run_bench(category: str, iterations: int) -> list[BenchResult]:
    """Run one category, return result(s). Some categories return >1 result."""
    if category == "dispatcher":
        return list(bench_dispatcher(iterations))
    if category == "validate_canonical_write":
        return [bench_validate_canonical_write(iterations)]
    if category == "canon_hash":
        return [bench_canon_hash(iterations)]
    if category == "fixture_runner":
        return [bench_fixture_runner(iterations)]
    if category == "ci_scan_budget":
        return [bench_ci_scan_budget(iterations)]
    raise ValueError(f"unknown category: {category}")


def run_all_benches(
    categories: list[str], iterations_override: dict[str, int], quiet: bool
) -> list[BenchResult]:
    """Run all requested categories sequentially. Order matters for stable
    results (fastest first to warm up the file cache + module imports)."""
    results: list[BenchResult] = []
    for category in categories:
        iterations = iterations_override.get(category, DEFAULT_ITERATIONS[category])
        if not quiet:
            print(f"  Running {category} ({iterations} iter)...", file=sys.stderr)
        t0 = time.perf_counter()
        cat_results = run_bench(category, iterations)
        elapsed = time.perf_counter() - t0
        if not quiet:
            for r in cat_results:
                print(
                    f"    {r.name}: p50={r.p50:.4f}ms  p95={r.p95:.4f}ms  "
                    f"(took {elapsed:.2f}s)",
                    file=sys.stderr,
                )
        results.extend(cat_results)
    return results


def _safe_relative_to_repo(p: Path) -> str:
    """Return p relative to REPO_ROOT if possible, otherwise the absolute
    str(p). Pathlib's relative_to() raises on non-subpaths, which would
    crash --check on operator-supplied --baseline-path values outside
    the repo (e.g., during a CI dry-run with a snapshot baseline)."""
    try:
        return str(p.relative_to(REPO_ROOT))
    except ValueError:
        return str(p)


def check_against_baseline(
    results: list[BenchResult], baseline_path: Path
) -> tuple[bool, list[str]]:
    """Compare current results to baseline. Returns (passed, messages).

    Failure modes (any one returns False):
      * baseline doc is missing
      * baseline doc parses empty (no table rows)
      * a current bench is NOT in the baseline (was the bench renamed
        or the baseline never re-recorded after a list change?)
      * a baseline bench is NOT in the current results (was a bench
        accidentally removed from the harness?)
      * any current p95 is ≥ REGRESSION_THRESHOLD × baseline p95

    v1.1.13 round-1 (Codex): an earlier draft made the rename / removal
    cases warning-only, which let CI go green while the comparison was
    silently no-ops. Now they hard-fail — operators must explicitly
    re-record the baseline (`--report=docs/perf_baseline.md`) when the
    bench list changes, which is the safer default.
    """
    if not baseline_path.is_file():
        rel = _safe_relative_to_repo(baseline_path)
        return False, [
            f"baseline doc missing: {baseline_path}. "
            f"Run `python3 scripts/perf_bench.py --report={rel}` "
            f"to create it."
        ]
    baseline = parse_baseline_doc(baseline_path.read_text(encoding="utf-8"))
    if not baseline:
        return False, [f"baseline doc {baseline_path} parsed empty (no table rows)"]
    msgs: list[str] = []
    failed = False
    current_names = {r.name for r in results}
    baseline_names = set(baseline.keys())

    # Rename / removal detection — strict (hard-fail).
    only_in_current = current_names - baseline_names
    only_in_baseline = baseline_names - current_names
    for name in sorted(only_in_current):
        failed = True
        msgs.append(
            f"  ✗ {name}: NOT in baseline (was the bench renamed or "
            f"added without re-recording?). Re-run with --report to "
            f"refresh the baseline."
        )
    for name in sorted(only_in_baseline):
        failed = True
        msgs.append(
            f"  ✗ {name}: in baseline but NOT in current run (was the "
            f"bench removed from the harness?). Re-run with --report "
            f"to refresh the baseline."
        )

    # Per-bench p95 comparison.
    for r in results:
        if r.name not in baseline:
            continue  # already accounted for above
        bp95 = baseline[r.name]["p95"]
        ratio = r.p95 / bp95 if bp95 > 0 else float("inf")
        if ratio >= REGRESSION_THRESHOLD:
            failed = True
            msgs.append(
                f"  ✗ {r.name}: p95 {r.p95:.4f}ms vs baseline {bp95:.4f}ms "
                f"(×{ratio:.2f}, threshold ×{REGRESSION_THRESHOLD})"
            )
        else:
            msgs.append(
                f"  ✓ {r.name}: p95 {r.p95:.4f}ms vs baseline {bp95:.4f}ms "
                f"(×{ratio:.2f})"
            )
    return not failed, msgs


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Performance benchmark harness for BSA plugin family"
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="Write a markdown baseline doc to this path (overwrites)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=f"Compare current results against {BASELINE_DOC.relative_to(REPO_ROOT)} "
        f"(fail if any p95 is ≥ {REGRESSION_THRESHOLD}× baseline p95)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-bench progress logs (still prints final table)",
    )
    parser.add_argument(
        "--category",
        choices=tuple(DEFAULT_ITERATIONS.keys()),
        help="Run a single category (default: all)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of a markdown table",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        help="Override iterations for ALL categories (default: per-category)",
    )
    parser.add_argument(
        "--baseline-path",
        type=Path,
        default=BASELINE_DOC,
        help=f"Path to the baseline doc (default: {BASELINE_DOC.relative_to(REPO_ROOT)})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    categories = (
        [args.category] if args.category else list(DEFAULT_ITERATIONS.keys())
    )
    iterations_override: dict[str, int] = {}
    if args.iterations is not None:
        if args.iterations < 2:
            print("--iterations must be >= 2", file=sys.stderr)
            return 2
        iterations_override = {c: args.iterations for c in categories}

    results = run_all_benches(categories, iterations_override, args.quiet)

    if args.json:
        out = [
            {
                "name": r.name,
                "iterations": r.iterations,
                "p50_ms": r.p50,
                "p95_ms": r.p95,
                "p99_ms": r.p99,
                "min_ms": r.min,
                "max_ms": r.max,
                "mean_ms": r.mean,
            }
            for r in results
        ]
        print(json.dumps(out, indent=2))
    elif args.report is not None:
        body = format_baseline_doc(results)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(body, encoding="utf-8")
        print(f"Wrote baseline doc to {args.report}", file=sys.stderr)
        # Also emit the table so the operator can eyeball it without
        # opening the file.
        print(format_table(results))
    else:
        print(format_table(results))

    if args.check:
        passed, msgs = check_against_baseline(results, args.baseline_path)
        print("\n## Regression check\n", file=sys.stderr)
        for m in msgs:
            print(m, file=sys.stderr)
        if not passed:
            print(
                f"\nFAIL: at least one bench regressed ≥ ×{REGRESSION_THRESHOLD}.",
                file=sys.stderr,
            )
            return 1
        print("\nPASS: no regressions detected.", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
