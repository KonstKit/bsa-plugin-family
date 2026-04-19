# Contract Versioning

## Canonical Version Source
- `A48.CanonPolicyVersion` is the authoritative active contract version.
- Every run must record the active version before Stage 1 starts.

## Version Semantics
- `MAJOR.MINOR.PATCH`.
- `PATCH`: wording clarifications only; no schema/marker/runtime behavior change.
- `MINOR`: backward-compatible additive changes (new optional fields, additive reports, additive checks).
- `MAJOR`: breaking changes (marker rename/removal, required field removal/rename, stage ordering changes, gate logic changes). Major bumps also fire when any `governance/immutable_invariants.md` invariant is touched.

## CanonPolicyVersion Hash Form (Sprint 3 US-S3-04)

Starting Sprint 3, `CanonPolicyVersion` accepts two forms:

| Form | Example | Where used |
|---|---|---|
| Bare semver | `0.95`, `1.0.0` | Pre-Sprint-3 runs; backward-compat. |
| Semver + hash | `1.0.0+hash:abc123def456` | Sprint-3+ runs; the hash pins the exact policy-file state at emission time. |

### Hash computation

The hash is the SHA-256 digest computed by `scripts/compute_canon_hash.py` over the sorted concatenation of policy files. The authoritative policy-file list lives inside the script (`POLICY_GLOBS` tuple) — changing that tuple is itself a policy change. High-level coverage:

- `governance/immutable_invariants.md`
- Every `skills/*/SKILL.md` (content-level, not just frontmatter — the body describes policy).
- Every orchestrator reference under `skills/bsa-orchestrator/references/`.
- `skills/bsa-evidence-intake/references/source-intake.md` + `reliability_tier_spec.md`.
- `skills/bsa-claim-binder/references/claim-layer.md`.
- `skills/bsa-context-framer/references/` (all three references).
- `skills/bsa-no-new-claims-auditor/references/no-new-claims-contract.md`.
- `skills/bsa-handoff-packager/references/` (h1..h4 specs, handoff-contract.md, handoff_manifest.schema.json).
- Both sidecar `integration-contract.md` + `anchor_manifest.schema.json` files.
- `docs/sem_audit_rename.md`.

Serialization (see `compute_canon_hash.py` for the reference implementation):
```
h = sha256()
for path in sorted(policy_files):
    h.update(rel_path_utf8)
    h.update(b'\x00')
    h.update(file_bytes)
    h.update(b'\x00')
digest = h.hexdigest()
```

### Marker field

Every runtime marker (`*.pass.json`, `*.ready.json`, etc.) emitted Sprint-3+ MUST include:

```json
{
  "canon_policy_version": "1.0.0",
  "canon_policy_version_hash": "abc123def456..."
}
```

The hash MAY be truncated to 6-64 hex characters in marker files (short-hash for readability); consumers MUST match by prefix when comparing to a full-digest hash.

### Bump rules

| Trigger | Version impact |
|---|---|
| Any `governance/immutable_invariants.md` change | MAJOR bump (hash changes automatically). |
| New SCN entry in `validation-scenario-manifest.csv` | MINOR bump (hash changes). |
| New skill directory or new required reference file | MINOR bump (hash changes). |
| Existing reference doc edited — prose clarification only | PATCH bump (hash changes, even for prose — because future drift-detection compares hashes). |
| Anything outside the policy-files list (fixtures, tests, scripts, README) | No bump, no hash change. |

Semver and hash are orthogonal: the semver portion captures intentional version delta; the hash captures exact file-state fingerprint. Two distinct commits with identical semver `1.0.0` that touched policy files will have different hashes — this is expected and signals that "the version label is the same but the policy state drifted".

### Drift detection

`bsa-anchor-auditor` and Sprint-3+ marker-chain validators MAY compare prior-run marker `canon_policy_version_hash` against the current repo hash. Mismatch surfaces a `policy_version_drift_warning`; whether it blocks or only logs is stage-profile-specific (see `run-profile-gates.md`).

## Compatibility Rules
- Producers must not emit artifacts below required version floor for the run profile.
- Consumers must reject artifacts marked with unknown future major version.
- Marker name aliases must be explicitly documented during any migration window.
- Producers MAY emit bare-semver markers in pre-v1.0 workspaces; consumers MUST treat a missing `canon_policy_version_hash` as "pre-hash workspace" and skip hash comparison (not as a validation failure).

## Migration Checklist
1. Publish version delta note with impacted artifacts/markers.
2. Update validation scenario manifest with migration checks.
3. Update runtime marker schema and workflow contract together.
4. Add re-entry guidance for in-flight runs crossing versions.
5. Remove compatibility aliases only after migration window closes.
