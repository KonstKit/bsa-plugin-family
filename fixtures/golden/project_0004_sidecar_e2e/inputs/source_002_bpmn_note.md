# Ticket Intake BPMN Flow (Source 002)

Origin: internal process note, authored by internal ops team lead, 2026-02-12.

Each ticket flow starts with an intake event, then routes through a severity-assignment task. High-severity tickets follow the page-on-call sequence flow.

The severity-assignment task ALWAYS runs within one hour of intake; the page-on-call flow ALWAYS triggers when severity is High or Critical.

The BPMN process for ticket intake has 5 anchors: 1 start event (intake), 1 task (assign severity), 2 sequence flows (intake-to-assign + high-to-page), 1 end event (paged). These anchors are tracked in `analysis/canonical/core_controls/A61_anchor_map.csv` and consumed by the camunda-bpmn-from-context sidecar in orchestrated mode.
