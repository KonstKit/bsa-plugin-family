# Support-Desk System Context (Source 001)

Origin: internal architecture note, authored by internal architect, 2026-02-10.

The support-desk system serves agents (the primary actor). It exposes a web UI container backed by an analytics database container. The whole thing sits inside the corporate intranet boundary.

The web UI is the agent's primary surface for triaging tickets. The analytics database backs reporting features (operational dashboards + per-agent volume metrics).

Agents authenticate against the corporate SSO gateway and access support tickets via the web UI; the analytics database backs reporting features.

The C4 system context for this architecture has 5 anchors: 1 system (support-desk), 1 person (agent), 1 boundary (corporate intranet), 2 containers (web UI + analytics database). These anchors are tracked in `analysis/canonical/core_controls/A61_anchor_map.csv` and consumed by the c4-plantuml-from-context sidecar in orchestrated mode.
