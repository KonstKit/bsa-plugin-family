# Canonical Artifact Map

## Main Cycle
- `stage1/`
  - `source_inventory.md`
  - `source_manifest.csv`
  - `source_coverage.md`
  - `contradiction_scan.md`
  - `missing_sources.md`
  - `A58_evidence_excerpts.csv`
  - `A59_claim_register.csv`
  - `A60_negative_evidence_register.csv`
  - `A63_analyst_judgment_register.csv` (v1.4.0+) — one row per A59 ClaimType=analyst_judgment claim, with hard-to-fake metadata (AnalystID, EmittedAt, UpstreamClaimRefs, ValidationStatus). Cross-checked by `bsa-no-new-claims-auditor` at promote time.
- `stage2/`
  - `context_state_frame.md`
  - `stakeholder_authority_map.md`
  - `system_context_seed.md`
  - `constraints_dependencies_route.md`
  - `stage2_summary.json`
- `stage3/`
  - `semantic_core_rows.md`
  - `semantic_issues.md`
  - optional `semantic_normalization_rows.md`
  - `semantic_traceability_report.md`
- `stage4/`
  - stage catalogs + `stage4_anchor_candidates.csv`
- `stage5/`
  - path decision + backbone + `stage5_anchor_candidates.csv` + anchor audit
- `stage6/`
  - contract layer pack + `A61_anchor_map_candidate.csv` + anchor audit
- `stage7/`
  - citation / consistency / skeptical / validation reports
- `stage8/`
  - readiness outputs + `no_new_claims_report.md`
- `handoff/`
  - `H1_exec_brief.md`
  - `H2_delivery_packet.md`
  - `H3_validation_packet.md`
  - `H4_open_items_packet.md`
  - `handoff_manifest.json`

## Discovery
- `d1/` problem framing artifacts
- `d2/` research design + path artifact pack + discovery `A58/A59/A60`
- `d3/` prioritization pack
- `d4/` feasibility pack
- `d5/`
  - `discovery_report.md`
  - `discovery_brief.md`
  - `stage1_seed_bundle.md`
  - `stage2_seed_bundle.md`
  - D5 audit reports

## Consumer Rule
Consumers read only canonical surfaces or promoted handoff surfaces. Raw proposal directories are not authoritative inputs for downstream package generation.
