# A48 — Run Context Card (project_0002)

- `RunID`: project_0002-run-001
- `RequestType`: discovery_pack_mixed_sources
- `Mode`: discovery_then_bsa
- `ProblemStatement`: Audit the analytics-platform data lineage and clarify cross-team ownership (data engineering vs analytics engineering vs BI vs reference-data custodian).
- `InScope`: staging schema, marts schema, reference-data schema, team ownership boundaries, lineage-drift detection.
- `OutOfScope`: individual dashboard rewrites, new dimensional models, performance tuning of dbt runs.
- `EntryCondition`: discovery.go emitted from D5; scope framed around ownership clarification.
- `CurrentStage`: handoff
- `SelectedPath`: structural
- `CanonPolicyVersion`: 1.0.0-rc2+hash:cbba8e53
