# API Latency Spec (Signed Engineering Spec, v3.2)

Author: Lead engineer (engineering team)
Sign-off: Engineering Director, 2026-04-01
Version control: tracked in main repo; PR-reviewed before merge.

## Section 2.4 Performance targets

API p95 latency target: 200 ms.

This target is measured at the load balancer, captured per-endpoint
in the standard observability pipeline, and reviewed during the
weekly performance triage. The 200-ms threshold is derived from the
customer-experience study (Q4 2025) that established 250 ms as the
upper bound for "feels instant" perception, with a 50-ms buffer for
network jitter.
