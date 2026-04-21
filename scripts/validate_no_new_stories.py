#!/usr/bin/env python3
"""No-new-stories auditor (Sprint 7 US-S7-03).

Phase-3 equivalent of the main-cycle ``bsa-no-new-claims-auditor``:
verifies that every row in ``A70_story_register.csv`` is bound to
upstream evidence and does NOT introduce net-new subjects, verbs, or
conditions absent from the source claims/NFRs it references.

Three check classes produced:

1. ``STORY_PROVENANCE`` — row has empty SourceClaimIDs AND empty
   RelatedNFRIDs (INV-08 violation). Schema catches this already in
   well-formed input, but the auditor re-checks for belt-and-braces.

2. ``STORY_DANGLING_REF`` — SourceClaimIDs references a ClaimID not
   present in promoted A59, OR RelatedNFRIDs references an NFRID not
   present in promoted A62. These are cross-artifact foreign-key
   errors the per-row schema can't catch.

3. ``STORY_LEAKAGE`` — significant tokens in StoryText or
   AcceptanceCriteria that do not appear in any referenced upstream
   source. Mirrors the main-cycle no-new-claims discipline.

CLI:
    scripts/validate_no_new_stories.py <workspace_root>

Exit 0 = clean; exit 1 = findings; exit 2 = invocation error.
Stdlib-only.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from governance.schemas import loader as _schema_loader  # noqa: E402

# Tokens shorter than this are ignored for leakage detection (articles,
# short prepositions, short common verbs — too noisy).
_MIN_TOKEN_LEN = 4

# English stop-words that would otherwise dominate the token-diff.
# Small hand-curated list — full nltk stop-words would be overkill.
_STOP_WORDS: frozenset[str] = frozenset({
    "about", "above", "after", "again", "against", "along", "also", "among", "and",
    "another", "around", "before", "behind", "below", "between", "both", "during",
    "each", "either", "enough", "every", "except", "from", "have", "having", "here",
    "inside", "into", "itself", "just", "like", "many", "might", "more", "most",
    "much", "must", "need", "never", "next", "none", "nothing", "only", "other",
    "others", "otherwise", "over", "same", "since", "some", "still", "such", "than",
    "that", "their", "them", "themselves", "then", "there", "these", "they", "this",
    "those", "though", "through", "under", "until", "upon", "used", "very", "want",
    "what", "when", "where", "which", "while", "with", "within", "without", "would",
    "your", "yours", "yourself", "able", "because", "been", "being", "come", "does",
    "done", "down", "even", "feel", "form", "goes", "going", "good", "great", "hard",
    "know", "left", "less", "made", "make", "most", "much", "near", "need", "next",
    "once", "open", "part", "past", "same", "said", "show", "side", "soon", "sure",
    "take", "that", "them", "they", "this", "time", "turn", "used", "very", "want",
    "well", "went", "were", "what", "when", "will", "work", "your", "always", "once",
    "should", "shall", "story", "user", "users", "stakeholder",
    "persona", "benefit", "goal",
})


@dataclass
class Finding:
    code: str
    story_id: str
    detail: str

    def format(self) -> str:
        return f"[{self.code}] {self.story_id}: {self.detail}"


@dataclass
class Report:
    findings: list[Finding]

    @property
    def ok(self) -> bool:
        return not self.findings


def _tokenize(text: str) -> set[str]:
    """Lowercased word-like tokens >= _MIN_TOKEN_LEN, stop-words removed."""
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]+", text.lower())
    return {
        w for w in words
        if len(w) >= _MIN_TOKEN_LEN and w not in _STOP_WORDS
    }


def _split_refs(value: str) -> list[str]:
    """Split ';' or '/' separated ID list into individual refs."""
    if not value:
        return []
    return [r for r in re.split(r"[;/]", value) if r]


def _load_a59_index(workspace: Path) -> dict[str, dict[str, str]]:
    """Map ClaimID → A59 row (or empty if A59 not present)."""
    path = workspace / "analysis" / "canonical" / "core_controls" / "A59_claim_register.csv"
    if not path.is_file():
        return {}
    return {row["ClaimID"]: row for row in _schema_loader.iter_a59_rows(path)}


def _load_a58_by_source(workspace: Path) -> dict[str, str]:
    """Concat ExcerptText by SourceID for leakage-check context.
    Returns {SourceID: concatenated_excerpt_text}."""
    path = workspace / "analysis" / "canonical" / "core_controls" / "A58_evidence_excerpts.csv"
    if not path.is_file():
        return {}
    result: dict[str, list[str]] = {}
    for row in _schema_loader.iter_a58_rows(path):
        sid = row.get("SourceID", "")
        if sid:
            result.setdefault(sid, []).append(row.get("ExcerptText", ""))
    return {sid: " ".join(texts) for sid, texts in result.items()}


def _load_a62_index(workspace: Path) -> dict[str, dict[str, str]]:
    """Map NFRID → A62 row (or empty if A62 not present)."""
    path = workspace / "analysis" / "canonical" / "core_controls" / "A62_nfr_register.csv"
    if not path.is_file():
        return {}
    return {row["NFRID"]: row for row in _schema_loader.iter_a62_rows(path)}


def audit_workspace(workspace: Path) -> Report:
    """Run no-new-stories audit."""
    a70_path = workspace / "analysis" / "canonical" / "core_controls" / "A70_story_register.csv"
    if not a70_path.is_file():
        return Report(findings=[])  # no stories → nothing to audit

    a59_index = _load_a59_index(workspace)
    a62_index = _load_a62_index(workspace)
    a58_by_source = _load_a58_by_source(workspace)

    findings: list[Finding] = []

    for row in _schema_loader.iter_a70_rows(a70_path):
        story_id = row.get("StoryID", "<?>")
        claim_refs = _split_refs(row.get("SourceClaimIDs", ""))
        nfr_refs = _split_refs(row.get("RelatedNFRIDs", ""))

        # Check 1: INV-08 provenance.
        if not claim_refs and not nfr_refs:
            findings.append(Finding(
                "STORY_PROVENANCE",
                story_id,
                "both SourceClaimIDs and RelatedNFRIDs are empty (INV-08 violation)",
            ))
            continue  # leakage check meaningless without any source

        # Check 2: dangling foreign-key refs.
        dangling_claims = [c for c in claim_refs if c not in a59_index]
        if dangling_claims:
            findings.append(Finding(
                "STORY_DANGLING_REF",
                story_id,
                f"SourceClaimIDs references ClaimIDs not in promoted A59: {dangling_claims}",
            ))
        dangling_nfrs = [n for n in nfr_refs if n not in a62_index]
        if dangling_nfrs:
            findings.append(Finding(
                "STORY_DANGLING_REF",
                story_id,
                f"RelatedNFRIDs references NFRIDs not in promoted A62: {dangling_nfrs}",
            ))

        # Check 3: leakage. Build the corpus of tokens this story is
        # allowed to use (upstream claim statements + their evidence
        # excerpts + upstream NFR statements). Any token in StoryText
        # or AcceptanceCriteria not in the corpus is a leakage candidate.
        corpus_texts: list[str] = []
        corpus_texts.append(row.get("Persona", ""))  # persona is ground truth
        for claim_id in claim_refs:
            if claim_id in a59_index:
                claim_row = a59_index[claim_id]
                corpus_texts.append(claim_row.get("Statement", ""))
                corpus_texts.append(claim_row.get("JustificationRationale", ""))
                # Pull excerpt text for the claim's sources.
                for src_id in _split_refs(claim_row.get("SourceID", "")):
                    corpus_texts.append(a58_by_source.get(src_id, ""))
        for nfr_id in nfr_refs:
            if nfr_id in a62_index:
                nfr_row = a62_index[nfr_id]
                corpus_texts.append(nfr_row.get("Statement", ""))
                corpus_texts.append(nfr_row.get("TestabilityNotes", ""))
                corpus_texts.append(nfr_row.get("Metric", ""))
                corpus_texts.append(nfr_row.get("Target", ""))
        allowed_tokens = _tokenize(" ".join(corpus_texts))

        story_tokens = _tokenize(
            row.get("StoryText", "") + " " + row.get("AcceptanceCriteria", "")
        )
        leaked = story_tokens - allowed_tokens
        if leaked:
            # Surface only the top-5 most-suspicious tokens — a deluge
            # of stop-word-adjacent misses would be noise. Sort by
            # length descending as a proxy for "specificity".
            top = sorted(leaked, key=lambda t: (-len(t), t))[:5]
            findings.append(Finding(
                "STORY_LEAKAGE",
                story_id,
                f"tokens in StoryText/AcceptanceCriteria absent from upstream sources: {top}",
            ))

    return Report(findings=findings)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="No-new-stories auditor (Sprint 7 US-S7-03)."
    )
    parser.add_argument("workspace", type=Path, help="Workspace root containing analysis/.")
    args = parser.parse_args(argv)

    if not (args.workspace / "analysis").is_dir():
        print(
            f"[no-new-stories] error: no analysis/ subdirectory at {args.workspace}",
            file=sys.stderr,
        )
        return 2

    report = audit_workspace(args.workspace)
    for f in report.findings:
        print(f.format(), file=sys.stderr)
    if report.ok:
        print(f"OK: no-new-stories audit clean ({args.workspace})")
        return 0
    print(
        f"\nFAIL: {len(report.findings)} no-new-stories finding(s) — "
        f"canonical A70_story_register.csv contains rows without upstream provenance, "
        f"with dangling foreign-key refs, or with leaked tokens. Either correct the "
        f"story text to stay within claim/NFR semantics, extend the upstream claim set, "
        f"or route the gap through A51.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
