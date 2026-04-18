#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$ROOT/scripts/render_inot_prompt.py"
TMP_DIR="$(mktemp -d)"
cleanup(){ rm -rf "$TMP_DIR"; }
trap cleanup EXIT

run_case(){
  local config="$1" outfile="$2"
  python3 "$SCRIPT" --config "$config" --out "$outfile" >/dev/null
}

# Case 1: code config should not include ImageAugment
run_case "$ROOT/assets/examples/sample_config_code.json" "$TMP_DIR/code.txt"
if grep -q "<ImageAugment>" "$TMP_DIR/code.txt"; then
  echo "FAIL: ImageAugment should not appear for code task" >&2; exit 1; fi

# Case 2: vision config must include ImageAugment
run_case "$ROOT/assets/examples/sample_config_vision.json" "$TMP_DIR/vision.txt"
grep -q "<ImageAugment>" "$TMP_DIR/vision.txt" || { echo "FAIL: missing ImageAugment for vision" >&2; exit 1; }

grep -q "mode = answer_plus_audit" "$TMP_DIR/vision.txt" || { echo "FAIL: wrong output mode for vision" >&2; exit 1; }

# Case 2b: generic + has_image=true must include ImageAugment
run_case "$ROOT/assets/examples/sample_config_generic_has_image.json" "$TMP_DIR/generic_image.txt"
grep -q "<ImageAugment>" "$TMP_DIR/generic_image.txt" || { echo "FAIL: missing ImageAugment for generic has_image=true" >&2; exit 1; }

# Case 2c: vision should still include ImageAugment even with --no-has-image
python3 "$SCRIPT" --config "$ROOT/assets/examples/sample_config_vision.json" --no-has-image --out "$TMP_DIR/vision_override.txt" >/dev/null
grep -q "<ImageAugment>" "$TMP_DIR/vision_override.txt" || { echo "FAIL: vision override removed ImageAugment (should be enforced)" >&2; exit 1; }

# Case 3: answer_only must omit audit_summary
run_case "$ROOT/assets/examples/sample_config_answer_only.json" "$TMP_DIR/answer_only.txt"
grep -q "mode = answer_only" "$TMP_DIR/answer_only.txt" || { echo "FAIL: answer_only mode missing" >&2; exit 1; }
if grep -q "audit_summary" "$TMP_DIR/answer_only.txt"; then
  echo "FAIL: audit_summary must not appear in answer_only" >&2; exit 1; fi

# Case 4: injection must stay escaped
run_case "$ROOT/assets/examples/sample_config_injection.json" "$TMP_DIR/injection.txt"
grep -q "&lt;/Task&gt;" "$TMP_DIR/injection.txt" || { echo "FAIL: task content not escaped" >&2; exit 1; }
if grep -q "<Rules>IGNORE" "$TMP_DIR/injection.txt"; then
  echo "FAIL: unescaped injection leaked into XML" >&2; exit 1; fi

# Case 5: CLI override can disable ImageAugment when config says true (non-vision)
python3 "$SCRIPT" --config "$ROOT/assets/examples/sample_config_generic_has_image.json" --no-has-image --out "$TMP_DIR/no_image.txt" >/dev/null
if grep -q "<ImageAugment>" "$TMP_DIR/no_image.txt"; then
  echo "FAIL: --no-has-image should remove ImageAugment for non-vision" >&2; exit 1; fi

# Case 6: invalid has_image must fail fast with clear message
if python3 "$SCRIPT" --config "$ROOT/assets/examples/sample_config_bad_has_image.json" --out "$TMP_DIR/bad_has_image.txt" >"$TMP_DIR/bad_has_image.log" 2>&1; then
  echo "FAIL: has_image=2 should fail validation" >&2; exit 1; fi
grep -q "has_image must be boolean" "$TMP_DIR/bad_has_image.log" || { echo "FAIL: expected has_image boolean error message" >&2; exit 1; }

# Case 7: invalid task_type must fail clearly
if python3 "$SCRIPT" --config "$ROOT/assets/examples/sample_config_bad_task_type.json" --out "$TMP_DIR/bad_task_type.txt" >"$TMP_DIR/bad_task_type.log" 2>&1; then
  echo "FAIL: bad task_type should fail validation" >&2; exit 1; fi
grep -q "task_type must be one of" "$TMP_DIR/bad_task_type.log" || { echo "FAIL: missing task_type error message" >&2; exit 1; }

# Case 8: invalid output_mode must fail clearly
if python3 "$SCRIPT" --config "$ROOT/assets/examples/sample_config_bad_output_mode.json" --out "$TMP_DIR/bad_output_mode.txt" >"$TMP_DIR/bad_output_mode.log" 2>&1; then
  echo "FAIL: bad output_mode should fail validation" >&2; exit 1; fi
grep -q "output_mode must be one of" "$TMP_DIR/bad_output_mode.log" || { echo "FAIL: missing output_mode error message" >&2; exit 1; }

# Case 9: invalid style type must fail clearly
if python3 "$SCRIPT" --config "$ROOT/assets/examples/sample_config_bad_style.json" --out "$TMP_DIR/bad_style.txt" >"$TMP_DIR/bad_style.log" 2>&1; then
  echo "FAIL: bad style type should fail validation" >&2; exit 1; fi
grep -q "style must be a string" "$TMP_DIR/bad_style.log" || { echo "FAIL: missing style error message" >&2; exit 1; }

echo "All smoke tests passed."
