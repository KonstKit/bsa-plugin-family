# Analytics Engineer Interview Transcript (Sanitized)

**Source type:** attestation (ReliabilityTier T4).
**Interviewee role:** analytics engineer (AE).
**Date:** current week.
**Disclaimers:** contemporaneous recall; contains rough estimates and subjective phrasing. Not a canonical claim source on its own; every factual-looking assertion here must be triangulated against a T1-T3 source before it can be promoted.

---

**Interviewer:** Can you describe how lineage between staging and marts is documented today?

**AE:** Honestly, it's not really documented anywhere except the dbt project file and the DAG it compiles into. If you want to know who owns which model you kind of have to read the schema prefix — `stg_` means data engineering owns it, `mart_` means we own it.

**Interviewer:** Is that convention written down somewhere?

**AE:** Not that I know of. It's just how we've always done it. There was a wiki page maybe two years ago but I think it's stale.

**Interviewer:** What are the biggest pain points?

**AE:** Probably lineage drift. When data engineering changes a staging model, we don't always find out until a dashboard breaks. I'd say maybe thirty percent of our dashboard incidents trace back to an upstream change we didn't hear about. Maybe more — I don't have exact numbers.

**Interviewer:** Do you have an owner defined for the BI consumer side?

**AE:** That's fuzzy too. BI team uses the marts but they don't own them. If a mart has a quality issue, they open a ticket with us, we investigate, and sometimes it turns out the root cause is in staging so we hand it to data engineering. The round-trip is slow.

**Interviewer:** Anything else?

**AE:** The other thing is reference data — lookup tables, taxonomy. Nobody really owns those. They live in the `ref` schema but we all update them. That probably should have a clearer owner.
