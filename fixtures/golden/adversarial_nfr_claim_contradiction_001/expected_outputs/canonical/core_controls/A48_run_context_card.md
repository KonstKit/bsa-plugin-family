# A48 Run Context Card

- `RunID`: adversarial-nfr-claim-contradiction-001
- `Mode`: direct
- `CurrentStage`: handoff
- `CanonPolicyVersion`: 1.1.0+hash:0d7654f6
- `RequestType`: adversarial fixture (Sprint 9 US-S9-04)
- `ProblemStatement`: Demonstrate Phase-3 contradictory-evidence handling — two upstream sources disagree on a measurable target; verify the chain (A59 → A60 → A51 → A62 → A70 → A71 → A72) propagates the contradiction as A51-routed deferrals at every layer rather than silently picking one side.
- `InScope`:
  - High-severity initial-response SLA contradiction between ops runbook (4h) and PM email (30min).
  - Full Phase-3 chain rendered with deferred A62.Target (Metric uncontested) + A70.INVESTStatus=needs-negotiation + A71.AutomationStatus=deferred + A72.LinkType=a51-routed, all co-populating A51-CONFL-001 per the contract.
- `OutOfScope`:
  - Block-on-contradiction failure mode (separate fixture).
  - Multi-way contradictions (3+ sources).
  - Tier-delta contradictions (auto-resolution via tier hierarchy per reliability_tier_spec). This fixture is intentionally same-tier (T2 vs T2) — neither auto-wins, A51 contradiction route is the contract-correct outcome.
- `EntryCondition`: Stage 1 promoted with the two contradictory claims captured.
