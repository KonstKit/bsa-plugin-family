# Constraints & Dependencies Route — fixture-project-0001

| constraint_id | dependency_id | source_ref | escalation_target | linked_a51_refs |
|---|---|---|---|---|
| CN-001 | | C-002 | ST-001 | |
| CN-002 | | C-003 | ST-001 | |
| CN-003 | | C-007 | ST-001 | A51-002 |
| | DP-001 | C-002 | ST-001 | |
| | DP-002 | C-001 | ST-003 | |
| | DP-003 | C-006 | ST-004 | |

Row context:
- CN-001 — severity assignment within 1 hour [C-002].
- CN-002 — only High/Critical pages on-call [C-003].
- CN-003 — SLA windows for initial response; channel-specific variants unresolved [C-007] [A51-002].
- DP-001 — ticketing-system severity metadata [C-002].
- DP-002 — billing-team intake form feeding tagged tickets [C-001].
- DP-003 — engineering escalation queue requires reproduction steps [C-006].
