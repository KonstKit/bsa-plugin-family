"""Tests for `scripts/perf_bench.py` (v1.1.13, Section F).

Pins the perf-bench harness's contract:

  * `_percentile` math is correct on small samples (edge cases that
    nearest-rank gets right but which a naive linear-interpolation
    implementation could mis-handle)
  * `BenchResult` properties (p50/p95/p99/min/max/mean) compute on
    the recorded samples, NOT a re-measured value
  * `format_table` + `format_baseline_doc` round-trip cleanly through
    `parse_baseline_doc` (catches any markdown drift between the
    writer and the reader — failure here would silently break
    `--check` against a freshly-written baseline)
  * Fast benches (`bench_dispatcher`, `bench_validate_canonical_write`)
    are end-to-end runnable with a tiny iteration count
  * `check_against_baseline` PASS + FAIL + missing-entry + missing-doc
    paths
  * The committed `docs/perf_baseline.md` parses cleanly and contains
    a row for every category (catches the case where someone bumps
    the bench list but forgets to re-record the baseline)

The slow benches (canon_hash, fixture_runner, ci_scan_budget) are
NOT run end-to-end in pytest — they shell to subprocesses and would
add ~5s per test invocation. They're covered by the standalone
`python3 scripts/perf_bench.py --check` job in CI instead.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PERF_BENCH_PATH = REPO_ROOT / "scripts" / "perf_bench.py"
BASELINE_DOC = REPO_ROOT / "docs" / "perf_baseline.md"


@pytest.fixture(scope="module")
def perf_bench():
    """Load `scripts/perf_bench.py` as a module (per the security_audit
    pattern other tests in this repo use)."""
    spec = importlib.util.spec_from_file_location("perf_bench", PERF_BENCH_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---- _percentile math -----------------------------------------------


def test_percentile_single_sample(perf_bench) -> None:
    """Nearest-rank on a single-element sample returns that element
    for any quantile (no interpolation, no IndexError)."""
    assert perf_bench._percentile((1.0,), 0.0) == 1.0
    assert perf_bench._percentile((1.0,), 0.5) == 1.0
    assert perf_bench._percentile((1.0,), 0.95) == 1.0
    assert perf_bench._percentile((1.0,), 1.0) == 1.0


def test_percentile_p50_odd(perf_bench) -> None:
    """p50 on a 5-element sample picks the middle element."""
    samples = (1.0, 2.0, 3.0, 4.0, 5.0)
    assert perf_bench._percentile(samples, 0.5) == 3.0


def test_percentile_p95_clamps_to_max(perf_bench) -> None:
    """p95 on a 10-element sample picks the 10th (largest) element
    via nearest-rank — confirms we don't fall off the end."""
    samples = tuple(float(i) for i in range(1, 11))
    # nearest-rank: ceil(0.95 * 10) = 10, index 9
    assert perf_bench._percentile(samples, 0.95) == 10.0


def test_percentile_p95_on_n100_matches_nist(perf_bench) -> None:
    """v1.1.13 round-1 critical: nearest-rank on N=100 samples 1..100
    must return 95.0 for p95 (the NIST reference). The round-1 impl
    used round(q*N + 0.5) - 1 + Python's banker's rounding which
    returned 96.0 — the all-same-value test fixture masked it."""
    samples = tuple(float(i) for i in range(1, 101))
    assert perf_bench._percentile(samples, 0.95) == 95.0
    assert perf_bench._percentile(samples, 0.99) == 99.0
    assert perf_bench._percentile(samples, 0.50) == 50.0


def test_percentile_q_zero(perf_bench) -> None:
    """q=0 → smallest sample (the special case the rank=ceil formula
    needs to clamp; the raw formula gives 0-indexed -1 otherwise)."""
    samples = tuple(float(i) for i in range(1, 11))
    assert perf_bench._percentile(samples, 0.0) == 1.0


def test_percentile_q_out_of_range(perf_bench) -> None:
    samples = (1.0, 2.0, 3.0)
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        perf_bench._percentile(samples, -0.1)
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        perf_bench._percentile(samples, 1.1)


def test_percentile_empty_raises(perf_bench) -> None:
    with pytest.raises(ValueError, match="empty sample"):
        perf_bench._percentile((), 0.5)


# ---- BenchResult properties ----------------------------------------


def test_bench_result_properties(perf_bench) -> None:
    samples = (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0)
    r = perf_bench.BenchResult(name="x", iterations=10, samples_ms=samples)
    assert r.iterations == 10
    assert r.min == 1.0
    assert r.max == 10.0
    assert r.mean == pytest.approx(5.5)
    assert r.p50 == pytest.approx(5.5)  # statistics.median for even N
    # nearest-rank p95: ceil(0.95 * 10) = 10, index 9 → samples[9] = 10.0
    assert r.p95 == 10.0
    assert r.p99 == 10.0


def test_bench_result_p95_on_n100_uses_nearest_rank(perf_bench) -> None:
    """Pin: BenchResult.p95 uses _percentile (NIST nearest-rank), not
    statistics.median or some other smoother. Catches drift if someone
    refactors the property to call statistics.quantiles which uses
    linear interpolation + would return 95.5 instead of 95.0."""
    samples = tuple(float(i) for i in range(1, 101))
    r = perf_bench.BenchResult(name="x", iterations=100, samples_ms=samples)
    assert r.p95 == 95.0
    assert r.p99 == 99.0


# ---- format_table + parse_baseline_doc round-trip --------------------


def test_format_table_round_trips(perf_bench) -> None:
    """Writer + reader agree on cell layout."""
    results = [
        perf_bench.BenchResult(
            name="alpha bench",
            iterations=10,
            samples_ms=(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0),
        ),
        perf_bench.BenchResult(
            name="beta bench (with parens)",
            iterations=20,
            samples_ms=tuple(float(i) for i in range(1, 21)),
        ),
    ]
    table = perf_bench.format_table(results)
    parsed = perf_bench.parse_baseline_doc(table)
    assert set(parsed.keys()) == {"alpha bench", "beta bench (with parens)"}
    alpha = parsed["alpha bench"]
    assert alpha["iter"] == 10.0
    assert alpha["min"] == 1.0
    assert alpha["max"] == 10.0
    # Stable mean / median with the integers we picked
    assert alpha["mean"] == pytest.approx(5.5, abs=0.001)
    assert alpha["p50"] == pytest.approx(5.5, abs=0.001)


def test_format_baseline_doc_round_trips(perf_bench) -> None:
    """Full doc body (intro + table + categories) parses back to the
    same set of bench names — confirms the writer's table layout
    matches what `parse_baseline_doc` knows how to read even with
    surrounding markdown."""
    results = [
        perf_bench.BenchResult(
            name="solo",
            iterations=5,
            samples_ms=(1.0, 2.0, 3.0, 4.0, 5.0),
        ),
    ]
    doc = perf_bench.format_baseline_doc(results)
    assert "# Performance Baseline" in doc
    assert "## Latencies" in doc
    parsed = perf_bench.parse_baseline_doc(doc)
    assert "solo" in parsed
    assert parsed["solo"]["iter"] == 5.0


# ---- bench primitives (fast end-to-end) -----------------------------


def test_bench_dispatcher_returns_two_results(perf_bench) -> None:
    """`bench_dispatcher` returns one matching + one non-matching
    BenchResult, both with the requested iteration count."""
    matching, non_matching = perf_bench.bench_dispatcher(iterations=10)
    assert isinstance(matching, perf_bench.BenchResult)
    assert isinstance(non_matching, perf_bench.BenchResult)
    assert matching.iterations == 10
    assert non_matching.iterations == 10
    assert "matching" in matching.name
    assert "non-matching" in non_matching.name
    # All samples positive (real wall-clock measurements)
    assert all(s > 0 for s in matching.samples_ms)
    assert all(s > 0 for s in non_matching.samples_ms)


def test_bench_validate_canonical_write_runs(perf_bench) -> None:
    """`bench_validate_canonical_write` runs end-to-end against the
    committed A59 fixture + returns a populated BenchResult."""
    r = perf_bench.bench_validate_canonical_write(iterations=10)
    assert isinstance(r, perf_bench.BenchResult)
    assert r.iterations == 10
    assert r.p95 > 0
    # Sanity: this bench is sub-millisecond per call on commodity
    # hardware. If p95 > 100ms, something has gone seriously wrong
    # (e.g., we're re-reading the fixture file every call).
    assert r.p95 < 100.0, (
        f"validate_canonical_write p95 {r.p95}ms is unreasonable; "
        f"check that the fixture body isn't being re-read inside the loop."
    )


def test_time_callable_ms_warmup(perf_bench) -> None:
    """`_time_callable_ms` discards the warm-up call (only `iterations`
    samples come back, even though the function is called `iterations+1`
    times total)."""
    counter = {"n": 0}
    def fn() -> None:
        counter["n"] += 1
    samples = perf_bench._time_callable_ms(fn, iterations=5)
    assert len(samples) == 5
    assert counter["n"] == 6  # 5 measured + 1 warmup


def test_time_callable_ms_rejects_too_few_iterations(perf_bench) -> None:
    with pytest.raises(ValueError, match=">= 2"):
        perf_bench._time_callable_ms(lambda: None, iterations=1)


# ---- check_against_baseline -----------------------------------------


def _fake_result(perf_bench, name: str, p95: float) -> "object":
    """Construct a BenchResult whose p95 is the requested value."""
    # nearest-rank p95 over a 100-element sample picks index 94
    # (ceil(0.95 * 100) = 95, -1 = index 94). We make every sample
    # the same value so all percentiles equal `p95`.
    samples = tuple([p95] * 100)
    return perf_bench.BenchResult(name=name, iterations=100, samples_ms=samples)


def test_check_against_baseline_passes_when_within_threshold(
    perf_bench, tmp_path
) -> None:
    """A current p95 within 2.0× baseline → PASS."""
    baseline_results = [_fake_result(perf_bench, "alpha", 1.0)]
    baseline_path = tmp_path / "baseline.md"
    baseline_path.write_text(
        perf_bench.format_baseline_doc(baseline_results), encoding="utf-8"
    )
    current_results = [_fake_result(perf_bench, "alpha", 1.5)]  # ×1.5 < ×2.0
    passed, msgs = perf_bench.check_against_baseline(current_results, baseline_path)
    assert passed
    assert any("✓" in m and "alpha" in m for m in msgs)


def test_check_against_baseline_fails_on_regression(perf_bench, tmp_path) -> None:
    """A current p95 ≥ 2.0× baseline → FAIL (the contract that catches
    O(n) → O(n²) drift)."""
    baseline_results = [_fake_result(perf_bench, "alpha", 1.0)]
    baseline_path = tmp_path / "baseline.md"
    baseline_path.write_text(
        perf_bench.format_baseline_doc(baseline_results), encoding="utf-8"
    )
    current_results = [_fake_result(perf_bench, "alpha", 2.5)]  # ×2.5 ≥ ×2.0
    passed, msgs = perf_bench.check_against_baseline(current_results, baseline_path)
    assert not passed
    assert any("✗" in m and "alpha" in m for m in msgs)


def test_check_against_baseline_fails_on_renamed_bench(
    perf_bench, tmp_path
) -> None:
    """v1.1.13 round-1 (Codex): rename / addition without re-recording
    the baseline must HARD-FAIL. An earlier draft made this warning-only
    which let CI go green while a bench was silently no longer
    compared against baseline (defeating the regression check)."""
    baseline_results = [_fake_result(perf_bench, "alpha", 1.0)]
    baseline_path = tmp_path / "baseline.md"
    baseline_path.write_text(
        perf_bench.format_baseline_doc(baseline_results), encoding="utf-8"
    )
    current_results = [_fake_result(perf_bench, "alpha-renamed", 1.0)]
    passed, msgs = perf_bench.check_against_baseline(current_results, baseline_path)
    assert not passed, "renamed/added bench must hard-fail --check"
    assert any("NOT in baseline" in m and "alpha-renamed" in m for m in msgs)
    # AND the missing-from-current side: alpha is in baseline but not
    # in current, so that should also be flagged.
    assert any("NOT in current run" in m and "alpha" in m for m in msgs)


def test_check_against_baseline_fails_on_removed_bench(
    perf_bench, tmp_path
) -> None:
    """v1.1.13 round-1: a bench that's in the baseline but missing from
    the current run is also a hard-fail (catches accidental harness
    truncation)."""
    baseline_results = [
        _fake_result(perf_bench, "alpha", 1.0),
        _fake_result(perf_bench, "beta", 1.0),
    ]
    baseline_path = tmp_path / "baseline.md"
    baseline_path.write_text(
        perf_bench.format_baseline_doc(baseline_results), encoding="utf-8"
    )
    # Current run only has alpha; beta got removed.
    current_results = [_fake_result(perf_bench, "alpha", 1.0)]
    passed, msgs = perf_bench.check_against_baseline(current_results, baseline_path)
    assert not passed, "removed bench must hard-fail --check"
    assert any("NOT in current run" in m and "beta" in m for m in msgs)


def test_check_against_baseline_missing_doc(perf_bench, tmp_path) -> None:
    """Missing baseline doc → FAIL with a helpful re-record message."""
    current_results = [_fake_result(perf_bench, "alpha", 1.0)]
    missing = tmp_path / "does_not_exist.md"
    passed, msgs = perf_bench.check_against_baseline(current_results, missing)
    assert not passed
    assert any("baseline doc missing" in m for m in msgs)


# ---- Committed baseline doc sanity ----------------------------------


def test_committed_baseline_doc_exists() -> None:
    """v1.1.13 commits docs/perf_baseline.md alongside the bench script."""
    assert BASELINE_DOC.is_file(), (
        f"docs/perf_baseline.md missing at {BASELINE_DOC}. Run "
        f"`python3 scripts/perf_bench.py --report=docs/perf_baseline.md` "
        f"to regenerate."
    )


def test_committed_baseline_covers_all_categories(perf_bench) -> None:
    """Every category in DEFAULT_ITERATIONS produces at least one row in
    the committed baseline. Catches drift if someone adds a new category
    but forgets to re-record the baseline."""
    body = BASELINE_DOC.read_text(encoding="utf-8")
    parsed = perf_bench.parse_baseline_doc(body)
    assert parsed, "committed baseline parsed empty (no table rows)"
    # Each category contributes ≥1 named row. We don't pin exact names
    # here (those drift naturally) — instead pin one substring per
    # category, since the test should pass if the bench list is renamed
    # but not extended.
    expected_substrings = {
        "dispatcher": "F5 dispatch",
        "validate_canonical_write": "validate_canonical_write",
        "canon_hash": "compute_canon_hash",
        "fixture_runner": "fixture_runner",
        "ci_scan_budget": "scan budget",
    }
    for category, needle in expected_substrings.items():
        matched = [name for name in parsed.keys() if needle in name]
        assert matched, (
            f"committed baseline missing entry for category {category!r} "
            f"(no name contains {needle!r}); did you re-record after "
            f"renaming a bench?"
        )


def test_committed_baseline_doc_has_intro_sections() -> None:
    """The doc body carries the operator-facing intro (regression policy
    + machine-dependence note) — pins that the writer didn't drift to a
    bare table."""
    body = BASELINE_DOC.read_text(encoding="utf-8")
    assert "# Performance Baseline" in body
    assert "Regression policy" in body
    assert "Numbers ARE machine-dependent" in body
    assert "## Latencies" in body
    assert "## Categories" in body
