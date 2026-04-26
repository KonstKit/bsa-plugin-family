#!/usr/bin/env python3
"""Protocol Buffers (proto3) exporter from BSA Stage 6 contract layer (v1.3.2).

Reads `analysis/canonical/stage6/A61_anchor_map.csv`, materializes every
`AnchorClass=contract` row whose `ElementID` is path-shaped AND yields a
valid proto3 service+method synthesis into a placeholder `service { rpc
Method(Request) returns (Response); }` plus matching empty Request +
Response messages, and emits the result as a proto3 file at
`<output_dir>/services.proto` (default
`analysis/handoff/contracts/proto/`) plus an anchor manifest at
`<output_dir>/anchor_manifest.json`.

**v1.3.2 ships the SKELETON ONLY.** The script does not parse free-form
prose in `interface_contract_model.md` and does not synthesize message
field schemas beyond promoting `{template}` parameters from the path to
`string` fields in the request message. Operators enrich the .proto in
place after the export. Skeleton boundary mirrors v1.3.0 OpenAPI +
v1.3.1 AsyncAPI exporters — bundle shape pinned now so v1.3.2.x can
iterate against a stable contract.

Schemas:
  * Anchor manifest: `skills/proto-from-context/references/anchor_manifest.schema.json` (v1.0).
  * Proto file: written as proto3 minimal-valid shape (operator runs
    `protoc` themselves for full conformance).

Pattern lineage: v1.2.4 telemetry collector → v1.2.16 freshness → v1.2.17
triangulation → v1.2.18 miner → v1.2.19 patcher → v1.3.0 OpenAPI →
v1.3.1 AsyncAPI → v1.3.2 (this script). Stdlib-only (proto syntax is
text, rendered directly — no yaml dep needed). Defensive CSV reads.
Atomic writes via tempfile + os.replace. Operator-invoked. NEVER runs
git/commit/push/protoc, NEVER edits canonical state, NEVER modifies
source files referenced by the inputs.

Lessons baked in pre-Codex from v1.3.0 + v1.3.1 retros:
- `--input` bypasses workspace `analysis/` guard (v1.3.0 R1-FIX-1).
- Path-shape regex `^/[A-Za-z0-9_/{}.~-]*$` — atomic regex-level
  rejection of `%` closes recursive-decode attack surface (v1.3.0 R2).
- Brace-balance scan after shape regex catches malformed `{...}`
  templates (v1.3.0 R1-FIX-2 part b).
- Parameter-name charset check inside brace-balance scan uses the
  proto3 field-name grammar `^[A-Za-z_][A-Za-z0-9_]*$` — NOT the
  v1.3.1 AsyncAPI charset which permitted hyphens. Rejects illegal-
  by-proto3 template names (`{order-id}`, `{9id}`, `{tenant.id}`,
  `{user id}`, `{order/sub}`) at gate time so that the synthesized
  request-message field names are guaranteed valid proto3 identifiers
  (v1.3.2 R1 lesson — extension of v1.3.1 R2 to all-emission-points).
- Reach equality: literal `..` → `_TRAVERSAL_HINT` →
  `element_id_path_traversal`; encoded variants → `_PATH_SHAPE` →
  `element_id_not_path_shaped` (v1.3.0 R5 docstring lesson).
- AnchorID validated against `^ANC-[A-Z0-9_-]+$` BEFORE filename
  construction (untrusted-input-as-path-component, v1.2.19 R1-FIX-1).
- `_is_relative_to` fallback before any write (v1.2.19 R1-FIX-2).

NEW for v1.3.2 (lessons #12 + #13 from v1.3.1 retro applied at design):
- Proto3 spec read for required fields per element kind (lesson #12):
  `syntax = "proto3";` MUST be first non-comment statement; `service`
  and `message` blocks have no required body content (empty allowed);
  field tags MUST be in [1, 536870911] with reserved range 19000-19999.
- Proto-identifier synthesis pass: ElementID path → service+method
  PascalCase names. Both names MUST match proto3 identifier regex
  `^[A-Za-z_][A-Za-z0-9_]*$`. Reach equality discipline (lesson #13):
  the synthesis-output charset MUST equal the manifest schema's
  view_element_id constraint AND the proto3 identifier grammar — all
  three pinned by per-gate regression tests.
- Service deduplication: multiple anchors mapping to the same service
  name share one `service { ... }` block; one Service entry per
  distinct synthesized service in `anchor_map`.

CLI:
  python3 skills/proto-from-context/scripts/generate_proto.py --workspace <path>
  python3 skills/proto-from-context/scripts/generate_proto.py --workspace <path> --input <a61_csv>
  python3 skills/proto-from-context/scripts/generate_proto.py --workspace <path> --output-dir <dir>
  python3 skills/proto-from-context/scripts/generate_proto.py --workspace <path> --package my.events
  python3 skills/proto-from-context/scripts/generate_proto.py --workspace <path> --print-only

Exit codes:
  0 — bundle generated (zero or more rpcs materialized).
  2 — invocation error.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REPO_ROOT = SKILL_DIR.parent.parent

DEFAULT_INPUT_REL = "analysis/canonical/stage6/A61_anchor_map.csv"
DEFAULT_OUTPUT_REL = "analysis/handoff/contracts/proto"
DEFAULT_PROTO_FILENAME = "services.proto"
DEFAULT_MANIFEST_FILENAME = "anchor_manifest.json"

DEFAULT_PACKAGE = "bsa.contracts"
PROTO_SYNTAX = "proto3"
MANIFEST_VERSION = "1.0"
SIDECAR_LITERAL = "proto-from-context"
SIDECAR_VERSION = "1.0.0"
FORMAT_LITERAL = "proto3"

# A61 columns we consume.
A61_REQUIRED_COLS = {
    "AnchorID",
    "AnchorClass",
    "ElementType",
    "ElementID",
    "ClaimID",
    "A51Ref",
}

# Path-shape regex. ASCII-exact, NO `%` (mirrors v1.3.0 OpenAPI +
# v1.3.1 AsyncAPI exporters' post-R2 design — atomic regex-level
# rejection of percent-encoding closes the recursive-decode attack
# surface; encoded traversal at any depth surfaces as
# `element_id_not_path_shaped`, matches the gate that fired). v1.3.2
# supports only path-style ElementIDs (`/orders/{order_id}/created`);
# dot-style (`OrderService.CreateOrder`) is intentionally deferred (see
# SKILL.md "Out of scope").
_PATH_SHAPE = re.compile(r"^/[A-Za-z0-9_/{}.~-]*$")
# Literal `..` traversal blocker (encoded variants caught by the shape
# regex's `%` reject). Reported as `element_id_path_traversal`.
_TRAVERSAL_HINT = re.compile(r"\.\.")
_ANCHOR_ID_PATTERN = re.compile(r"^ANC-[A-Z0-9_-]+$")
# Proto3 identifier regex (per https://protobuf.dev/reference/protobuf/
# proto3-spec/#identifiers — same as most C-family languages). Used by
# (a) synthesized service / method names, (b) the brace-balance scan's
# template-name charset, (c) extracted parameter → request-field names.
# v1.3.2 R1 lesson (extension of v1.3.1 R2): when the same charset must
# bind a gate AND a downstream emission, the charset MUST equal the
# downstream consumer's grammar — NOT a sibling exporter's grammar
# (AsyncAPI/OpenAPI accept hyphens in parameter names; proto3 does
# not). Pre-R1 the brace-balance scan used `^[A-Za-z0-9_-]+$` (copied
# from v1.3.1 AsyncAPI exporter), which silently admitted illegal-by-
# proto3 names like `{order-id}` and `{9id}` — the gate accepted them
# and `_synthesize_service_method` emitted them verbatim as
# `string order-id = 1;` (invalid proto3 field name). Post-R1 the
# charset matches `_PROTO_IDENTIFIER` exactly; illegal-by-proto3
# template names now surface as `element_id_not_path_shaped` at gate
# time.
_PROTO_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Parameter-name charset for templates. Aliased to `_PROTO_IDENTIFIER`
# to make the reach-equality discipline explicit. v1.3.2 divergence
# from v1.3.0 (OpenAPI: `[A-Za-z0-9._~-]+` per RFC 3986) and v1.3.1
# (AsyncAPI: `^[A-Za-z0-9_-]+$` per AsyncAPI 3.0 Parameter Object
# spec): each exporter's gate must match its own format's downstream
# consumer grammar.
_PARAM_NAME_CHARSET = _PROTO_IDENTIFIER
# Pure-template segment: `^\{<name>\}$` where name matches the
# tightened proto-identifier charset. Used by synthesis to distinguish
# pure-template segments (promoted to request-message fields) from
# literal segments (used to build service+method names).
_PURE_TEMPLATE_SEGMENT = re.compile(r"^\{([A-Za-z_][A-Za-z0-9_]*)\}$")
# Proto3 package-name syntax: dot-separated identifiers. Used to
# validate `--package` operator input.
_PROTO_PACKAGE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$"
)


# ---- CSV helpers ---------------------------------------------------


def _read_a61_rows(path: Path) -> tuple[list[dict], str | None]:
    """Defensive CSV read. Returns (rows, error_message). On success
    error is None; on failure rows is empty."""
    if not path.is_file():
        return [], (
            f"A61 anchor map not found at {path}. Did Stage 6 finish "
            f"promotion? Re-run /bsa-stage 6 first, or pass --input "
            f"explicitly to point at a fixture-based A61 CSV."
        )
    try:
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            actual_cols = set(reader.fieldnames or [])
            missing = A61_REQUIRED_COLS - actual_cols
            if missing:
                return [], (
                    f"A61 anchor map at {path} is missing required "
                    f"columns: {sorted(missing)}. Expected at least "
                    f"{sorted(A61_REQUIRED_COLS)}."
                )
            rows = list(reader)
    except (OSError, csv.Error) as exc:
        return [], f"failed to read A61 CSV at {path}: {exc}"
    return rows, None


# ---- Anchor classification -----------------------------------------


def _classify_anchor(row: dict) -> str:
    """Run an A61 row through the inclusion gates.

    Returns one of:
      * "ready"                    — passes shape + brace-balance gates;
                                     proto-identifier synthesis runs in
                                     `build_bundle` (synthesis failures
                                     surface there as
                                     `proto_identifier_synthesis_failed`).
      * "skipped_non_contract"     — AnchorClass != contract.
      * "skipped_shape"            — ElementID not path-shaped: fails
        the `_PATH_SHAPE` regex (rejects `%`, shell metacharacters,
        Unicode digits, dot-style addresses missing leading `/`, etc.
        — so percent-encoded `..` like `%2e%2e`, `%252e%252e`,
        `%25252e%25252e` ALL surface here, not under
        `skipped_traversal`) OR has malformed OpenAPI-style template
        syntax (unbalanced / empty / nested / misordered `{...}`) OR
        contains a `{...}` template whose name doesn't match the proto3
        field-name grammar `^[A-Za-z_][A-Za-z0-9_]*$` (illegal names
        like `{order-id}` (hyphen), `{9id}` (leading digit),
        `{tenant.id}` (dot), `{user id}` (space), `{order/sub}`
        (slash). v1.3.2 R1 lesson — the gate's template-name charset
        MUST match the downstream consumer (proto3 field names),
        NOT a sibling exporter's charset).
      * "skipped_traversal"        — ElementID contains a LITERAL `..`
        in its raw form. Encoded variants are caught one gate earlier
        (`skipped_shape`) because the path-shape regex rejects `%`
        outright (closes recursive-decode attack surface, mirrors
        v1.3.0/v1.3.1 post-R2 design).
      * "skipped_bad_anchor_id"    — AnchorID malformed.
    """
    anchor_id = (row.get("AnchorID") or "").strip()
    anchor_class = (row.get("AnchorClass") or "").strip()
    element_id = (row.get("ElementID") or "").strip()

    if not _ANCHOR_ID_PATTERN.fullmatch(anchor_id):
        return "skipped_bad_anchor_id"
    if anchor_class != "contract":
        return "skipped_non_contract"
    if _TRAVERSAL_HINT.search(element_id):
        return "skipped_traversal"
    if not _PATH_SHAPE.fullmatch(element_id):
        return "skipped_shape"
    # Brace-balance + parameter-name-charset scan. Mirrors v1.3.0
    # OpenAPI exporter R1-FIX-2 part b PLUS the v1.3.2 R1 tightening
    # (proto3-specific): contents inside `{...}` MUST match the proto3
    # field-name grammar `^[A-Za-z_][A-Za-z0-9_]*$`. Rejects hyphenated
    # `{order-id}`, leading-digit `{9id}`, plus all the v1.3.1 R2
    # rejects (`{tenant.id}`, `{user id}`, `{order/sub}`). Reach
    # equality: this charset = `_PROTO_IDENTIFIER` = the field-name
    # rendered into `services.proto` = the manifest schema constraint
    # for `view_element_id` (R1 MINOR fix added a real schema pattern
    # there too).
    in_template = False
    template_buf = ""
    depth = 0
    for ch in element_id:
        if ch == "{":
            if in_template:
                return "skipped_shape"  # nested
            in_template = True
            template_buf = ""
            depth += 1
        elif ch == "}":
            if not in_template:
                return "skipped_shape"  # `}` before `{`
            if not template_buf:
                return "skipped_shape"  # `{}` empty
            if not _PARAM_NAME_CHARSET.fullmatch(template_buf):
                return "skipped_shape"
            in_template = False
            depth -= 1
        elif in_template:
            template_buf += ch
    if depth != 0:
        return "skipped_shape"  # unbalanced
    return "ready"


# ---- Proto-identifier synthesis -----------------------------------


def _to_pascal_case(segment: str) -> str:
    """Convert a path-segment string to PascalCase. Splits on
    non-alphanumeric characters (`_`, `-`, `{`, `}`, `.`, `~`),
    capitalizes each word, concatenates. Returns "" on empty input or
    if the segment contains no alphanumeric characters."""
    parts = re.split(r"[^A-Za-z0-9]+", segment)
    parts = [p for p in parts if p]
    if not parts:
        return ""
    return "".join(p[0].upper() + p[1:] for p in parts)


def _synthesize_service_method(
    element_id: str,
) -> tuple[str, str, list[str]] | None:
    """Synthesize (service_name, method_name, param_names) from a
    path-shaped, brace-balanced ElementID.

    Algorithm (lesson #12 — proto3 identifier rules read from spec):
      1. Strip leading `/` and split on `/`.
      2. Filter empty segments (handles `//` and trailing `/`).
      3. Classify each segment as pure-template (`{name}`) or literal.
         Mixed segments like `abc{id}xyz` are treated as literal —
         their template name does NOT become a request-message field;
         the segment is PascalCased into the method name with `{`/`}`
         acting as separators. Documented in integration-contract.md as
         a v1.3.2 corner case.
      4. Take the first non-template segment as service-name source;
         take all remaining non-template segments as method-name parts.
         If no non-template segments exist (e.g., `/{a}/{b}` or `/`),
         synthesis fails.
      5. Take ordered list of pure-template parameter names as
         request-message fields.
      6. PascalCase service-name + method-name parts. If method parts
         are empty (e.g., `/orders/{id}` has only one literal segment),
         method defaults to `Invoke`.
      7. Both synthesized names MUST match `_PROTO_IDENTIFIER`. If
         either fails (e.g., segment starts with digit `/123abc/foo`),
         synthesis fails.

    Reach-equality discipline (lesson #13): the output of this function
    flows directly into:
      * `services.proto` rendered text (proto3 grammar: identifiers
        match `^[A-Za-z_][A-Za-z0-9_]*$`),
      * `anchor_manifest.json::anchor_map[].view_element_id` (schema
        `minLength: 1` + the same identifier grammar by convention).
    All three must agree atomically; pinned by per-gate regression
    tests.

    Returns (service_name, method_name, param_names) on success,
    None on synthesis failure (caller surfaces as
    `proto_identifier_synthesis_failed`).
    """
    stripped = element_id.lstrip("/")
    raw_segments = stripped.split("/")
    # Strip empties from `//` or trailing `/`.
    raw_segments = [s for s in raw_segments if s]

    param_names: list[str] = []
    literal_segments: list[str] = []
    for seg in raw_segments:
        m = _PURE_TEMPLATE_SEGMENT.fullmatch(seg)
        if m is not None:
            name = m.group(1)
            # Dedup while preserving first-seen order (handles
            # `/parent/{id}/child/{id}`).
            if name not in param_names:
                param_names.append(name)
        else:
            literal_segments.append(seg)

    if not literal_segments:
        return None  # no segment for service name

    service_raw = literal_segments[0]
    method_raws = literal_segments[1:]

    service_name = _to_pascal_case(service_raw)
    if not _PROTO_IDENTIFIER.fullmatch(service_name):
        return None

    if method_raws:
        method_parts = [_to_pascal_case(p) for p in method_raws]
        if any(not part for part in method_parts):
            return None
        method_name = "".join(method_parts)
    else:
        method_name = "Invoke"

    if not _PROTO_IDENTIFIER.fullmatch(method_name):
        return None

    return service_name, method_name, param_names


# ---- Bundle builder ------------------------------------------------


def _read_plugin_canon_version() -> str:
    """Read active canon_policy_version from .claude-plugin/canon_policy.json
    (extracted from plugin.json in v1.3.6 hotfix — Claude Code v2.1.19
    plugin install schema rejects unknown top-level keys, so the canon
    block lives in a sibling file now). Falls back to plugin.json's
    legacy `canonPolicyVersion` block when canon_policy.json is missing
    (one-version backward compat for downstream tooling that pinned
    pre-v1.3.6 manifests)."""
    canon_path = REPO_ROOT / ".claude-plugin" / "canon_policy.json"
    plugin_path = REPO_ROOT / ".claude-plugin" / "plugin.json"
    canon: dict = {}
    if canon_path.is_file():
        try:
            canon = json.loads(canon_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            canon = {}
    elif plugin_path.is_file():
        try:
            doc = json.loads(plugin_path.read_text(encoding="utf-8"))
            legacy = doc.get("canonPolicyVersion", {})
            if isinstance(legacy, dict):
                canon = legacy
        except (OSError, json.JSONDecodeError):
            canon = {}
    if not isinstance(canon, dict):
        return "0.0.0"
    semver = str(canon.get("semver", "0.0.0"))
    prefix = canon.get("hash_prefix")
    if isinstance(prefix, str) and prefix:
        return f"{semver}+hash:{prefix}"
    return semver


def build_bundle(
    rows: list[dict],
    *,
    package: str,
    proto_path_str: str,
) -> tuple[dict, dict]:
    """Build the proto bundle (intermediate dict for rendering) + the
    anchor manifest. `proto_path_str` is the value to record in
    `view_files[].path` — repo-relative when the file lives inside the
    workspace, absolute otherwise (v1.2.19 R1-FIX-2 + v1.3.0 patterns).

    Returns (proto_doc, manifest_doc), where proto_doc has shape:
      {
        "syntax": "proto3",
        "package": "<name>",
        "services": {
          "<ServiceName>": [
            {
              "method": "<MethodName>",
              "request_msg": "<ServiceMethodRequest>",
              "response_msg": "<ServiceMethodResponse>",
              "tag_provenance": "<ClaimID|A51Ref|AnchorID>",
            },
            ...
          ],
          ...
        },
        "messages": {
          "<MessageName>": [
            {"name": "<field_name>", "type": "string", "tag": <int>},
            ...
          ],
          ...
        },
      }
    """
    services: dict[str, list[dict]] = {}
    messages: dict[str, list[dict]] = {}
    anchor_map: list[dict] = []
    unmapped: list[dict] = []
    seen_services: set[str] = set()
    seen_rpcs: set[str] = set()

    for row in rows:
        status = _classify_anchor(row)
        anchor_id = (row.get("AnchorID") or "").strip()
        element_id = (row.get("ElementID") or "").strip()

        if status == "skipped_bad_anchor_id":
            # Silently dropped — AnchorID itself unusable as manifest
            # reference (would fail manifest schema's ANC-... pattern).
            continue
        if status == "skipped_non_contract":
            unmapped.append({
                "a61_anchor_id": anchor_id,
                "reason": "non_contract_anchor_class",
                "element_id": element_id,
            })
            continue
        if status == "skipped_traversal":
            unmapped.append({
                "a61_anchor_id": anchor_id,
                "reason": "element_id_path_traversal",
                "element_id": element_id,
            })
            continue
        if status == "skipped_shape":
            unmapped.append({
                "a61_anchor_id": anchor_id,
                "reason": "element_id_not_path_shaped",
                "element_id": element_id,
            })
            continue

        # status == "ready" — try proto-identifier synthesis.
        synth = _synthesize_service_method(element_id)
        if synth is None:
            unmapped.append({
                "a61_anchor_id": anchor_id,
                "reason": "proto_identifier_synthesis_failed",
                "element_id": element_id,
            })
            continue

        service_name, method_name, param_names = synth
        rpc_key = f"{service_name}.{method_name}"

        if rpc_key in seen_rpcs:
            unmapped.append({
                "a61_anchor_id": anchor_id,
                "reason": "duplicate_rpc_collision",
                "element_id": element_id,
            })
            continue
        seen_rpcs.add(rpc_key)

        claim_id = (row.get("ClaimID") or "").strip()
        a51_ref = (row.get("A51Ref") or "").strip()
        tag_provenance = claim_id or a51_ref or anchor_id

        request_msg = f"{service_name}{method_name}Request"
        response_msg = f"{service_name}{method_name}Response"

        services.setdefault(service_name, []).append({
            "method": method_name,
            "request_msg": request_msg,
            "response_msg": response_msg,
            "tag_provenance": tag_provenance,
        })
        # Request message: one `string <param> = N;` field per template
        # parameter, sequential tags starting at 1. Response: empty.
        request_fields = [
            {"name": name, "type": "string", "tag": idx + 1}
            for idx, name in enumerate(param_names)
        ]
        messages[request_msg] = request_fields
        messages[response_msg] = []

        # Service entry: deduplicated — one per distinct service name.
        if service_name not in seen_services:
            seen_services.add(service_name)
            anchor_map.append({
                "view_element_id": service_name,
                "view_element_kind": "Service",
                "a61_anchor_id": anchor_id,
                "notes": (
                    f"placeholder service block (first-seen anchor "
                    f"contributing to this service); trace: "
                    f"{tag_provenance}"
                ),
            })
        # Rpc entry: one per materialized anchor.
        anchor_map.append({
            "view_element_id": rpc_key,
            "view_element_kind": "Rpc",
            "a61_anchor_id": anchor_id,
            "notes": (
                f"placeholder unary rpc (operator may switch to "
                f"streaming with `stream` keyword); trace: "
                f"{tag_provenance}"
            ),
        })

    proto_doc = {
        "syntax": PROTO_SYNTAX,
        "package": package,
        "services": services,
        "messages": messages,
    }

    generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    manifest_doc = {
        "manifest_version": MANIFEST_VERSION,
        "generated_at": generated_at,
        "sidecar": SIDECAR_LITERAL,
        "sidecar_version": SIDECAR_VERSION,
        "canon_policy_version": _read_plugin_canon_version(),
        "view_files": [
            {
                "path": proto_path_str,
                "format": FORMAT_LITERAL,
                "anchor_map": anchor_map,
                "unmapped_anchors": unmapped,
            },
        ],
    }
    return proto_doc, manifest_doc


# ---- Proto rendering -----------------------------------------------


def _render_proto(doc: dict) -> str:
    """Render the proto bundle dict as deterministic proto3 text.
    Output shape:

      syntax = "proto3";

      package <name>;

      // Generated by skills/proto-from-context (v1.3.2 skeleton).
      // ...

      service <Name> {
        // bsa-anchor: <provenance>
        rpc <Method>(<Request>) returns (<Response>);
        ...
      }

      message <Name> {
        string <field> = <tag>;
        ...
      }

    Service ordering = first-seen; rpc ordering within service =
    first-seen; message ordering = same as services then rpcs.
    Insertion-order is deterministic in Python 3.7+ dicts; idempotency
    test pins this.
    """
    lines: list[str] = []
    lines.append(f'syntax = "{doc["syntax"]}";')
    lines.append("")
    lines.append(f'package {doc["package"]};')
    lines.append("")
    lines.append(
        "// Generated by skills/proto-from-context (v1.3.2 skeleton)."
    )
    lines.append(
        "// Operator must enrich each rpc with real Request/Response"
    )
    lines.append(
        "// message fields and choose unary vs streaming semantics"
    )
    lines.append("// before shipping.")
    lines.append("")

    for service_name, rpcs in doc["services"].items():
        lines.append(f"service {service_name} {{")
        for rpc in rpcs:
            lines.append(f"  // bsa-anchor: {rpc['tag_provenance']}")
            lines.append(
                f"  rpc {rpc['method']}({rpc['request_msg']}) "
                f"returns ({rpc['response_msg']});"
            )
        lines.append("}")
        lines.append("")

    for message_name, fields in doc["messages"].items():
        if not fields:
            lines.append(f"message {message_name} {{")
            lines.append(
                "  // Placeholder — operator enriches with real fields."
            )
            lines.append("}")
        else:
            lines.append(f"message {message_name} {{")
            for field in fields:
                lines.append(
                    f"  // Placeholder field — operator must enrich "
                    f"with real proto3 type and rename for clarity "
                    f"(extracted from `{{{field['name']}}}` template "
                    f"in ElementID)."
                )
                lines.append(
                    f"  {field['type']} {field['name']} = {field['tag']};"
                )
            lines.append("}")
        lines.append("")

    return "\n".join(lines).rstrip("\n") + "\n"


# ---- Atomic writes -------------------------------------------------


def _atomic_write(target_path: Path, body: str) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=target_path.parent,
        prefix=".proto_exporter_",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
        os.replace(tmp, target_path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _atomic_write_json(target_path: Path, doc: dict) -> None:
    _atomic_write(target_path, json.dumps(doc, indent=2))


# ---- _is_relative_to backport --------------------------------------


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


# ---- CLI -----------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Protocol Buffers (proto3) exporter from BSA Stage 6 "
            "contract layer (v1.3.2). Reads A61 anchor map, emits "
            "skeleton services.proto + anchor manifest. Skeleton-only: "
            "operator enriches Request/Response messages and chooses "
            "streaming semantics after export. NEVER runs git/commit/"
            "push/protoc or modifies canonical state."
        ),
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="BSA workspace root (defaults to cwd).",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help=(
            f"Override the A61 anchor-map CSV path (default <workspace>/"
            f"{DEFAULT_INPUT_REL}). Bypasses the workspace `analysis/` "
            f"guard so fixture-based runs work without an initialized "
            f"BSA workspace (v1.3.0 OpenAPI exporter R1-FIX-1 lesson)."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=(
            f"Override the output directory (default <workspace>/"
            f"{DEFAULT_OUTPUT_REL}). Implicit-missing path is "
            f"permissive (created on demand); explicit-missing path "
            f"is rejected (operator typo defense, mirrors v1.2.19 "
            f"patcher R1-FIX-1 + v1.3.0/v1.3.1 exporters)."
        ),
    )
    parser.add_argument(
        "--package",
        type=str,
        default=DEFAULT_PACKAGE,
        help=(
            f"proto3 package name (default `{DEFAULT_PACKAGE}`). MUST "
            f"match `^[A-Za-z_][A-Za-z0-9_]*(\\.[A-Za-z_][A-Za-z0-9_]"
            f"*)*$`."
        ),
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help=(
            "Print the manifest JSON to stdout instead of writing "
            "files."
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-summary log line.",
    )
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if not _PROTO_PACKAGE.fullmatch(args.package):
        print(
            f"proto-from-context: --package {args.package!r} is not a "
            f"valid proto3 package name (must match "
            f"`^[A-Za-z_][A-Za-z0-9_]*(\\.[A-Za-z_][A-Za-z0-9_]*)*$`).",
            file=sys.stderr,
        )
        return 2

    workspace = args.workspace.resolve()
    # v1.3.0 R1-FIX-1: workspace guard only when --input not provided.
    if args.input is None:
        if not (workspace / "analysis").is_dir():
            print(
                f"proto-from-context: workspace {workspace} is not "
                f"initialized (no analysis/ directory). Run /bsa-start "
                f"first OR pass --input explicitly.",
                file=sys.stderr,
            )
            return 2
        input_path = workspace / DEFAULT_INPUT_REL
    else:
        input_path = args.input.resolve()

    if args.output_dir is None:
        output_dir = workspace / DEFAULT_OUTPUT_REL
    else:
        output_dir = args.output_dir.resolve()
        # v1.2.19 R1-FIX-1 mirror: explicit override requires existence.
        if not output_dir.is_dir():
            print(
                f"proto-from-context: --output-dir {output_dir} does "
                f"not exist or is not a directory. (An implicit "
                f"workspace-derived output dir that doesn't exist yet "
                f"is permissive; an explicit path that doesn't exist "
                f"is a typo and rejected.)",
                file=sys.stderr,
            )
            return 2

    rows, err = _read_a61_rows(input_path)
    if err is not None:
        print(f"proto-from-context: {err}", file=sys.stderr)
        return 2

    proto_path = output_dir / DEFAULT_PROTO_FILENAME
    manifest_path = output_dir / DEFAULT_MANIFEST_FILENAME

    # v1.2.19 R1-FIX-2 mirror: relative when in workspace, absolute
    # otherwise.
    if _is_relative_to(proto_path, workspace):
        proto_path_str = str(proto_path.relative_to(workspace))
    else:
        proto_path_str = str(proto_path)

    proto_doc, manifest_doc = build_bundle(
        rows,
        package=args.package,
        proto_path_str=proto_path_str,
    )

    proto_text = _render_proto(proto_doc)

    if args.print_only:
        print(json.dumps(manifest_doc, indent=2))
        return 0

    _atomic_write(proto_path, proto_text)
    _atomic_write_json(manifest_path, manifest_doc)

    if not args.quiet:
        view_file = manifest_doc["view_files"][0]
        anchors_in = len(view_file["anchor_map"])
        unmapped = len(view_file["unmapped_anchors"])
        services_count = len(proto_doc["services"])
        rpcs_count = sum(
            len(rpcs) for rpcs in proto_doc["services"].values()
        )
        print(
            f"proto-from-context: wrote {proto_path} + {manifest_path}\n"
            f"  services materialized: {services_count}\n"
            f"  rpcs materialized: {rpcs_count}\n"
            f"  anchor_map entries: {anchors_in}\n"
            f"  unmapped_anchors: {unmapped}\n"
            f"  NOTE: v1.3.2 ships a SKELETON — placeholder unary "
            f"rpcs + empty Request/Response messages only. Operator "
            f"must enrich services.proto with real proto3 fields + "
            f"streaming semantics before shipping."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
