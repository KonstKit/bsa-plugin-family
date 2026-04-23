# SRE On-Call Handbook — P0 Triage

## P0 response

P0 incident response begins within 5 minutes of page acknowledgement.
This is the SRE-team-internal target; the on-call SRE pages the IM and
opens the war-room within 5 minutes regardless of the underlying alert
source (PagerDuty, Statuspage, customer email).

The 5-minute target is tracked via the `p0_response_minutes` SLO;
breaches show up on the weekly SLO review and require a postmortem.

Sign-off: SRE team lead, monthly handbook review.
