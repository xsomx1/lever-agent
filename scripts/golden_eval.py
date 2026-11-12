#!/usr/bin/env python3
"""Golden-set sanity check for the screening rubric/prompt (T2.6's testing note).

NOT part of `pytest` — this makes real OpenAI API calls and costs a small
amount of real money. Run by hand:

    uv run python scripts/golden_eval.py

The three "candidates" below are entirely fabricated placeholders (not real
people, not derived from any real candidate) — built in-process as minimal
PDF bytes, never written to disk. Purpose: catch silent drift if the rubric
or prompt changes later, by checking each still lands in its expected score
band against the real Staff SWE — IAM (Serbia) rubric.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from openai import OpenAI  # noqa: E402

from lever_agent.keychain import get_openai_api_key  # noqa: E402
from lever_agent.rubric import load_rubric  # noqa: E402
from lever_agent.screening import MODEL, compute_overall_score, recommendation_band, score_resume  # noqa: E402

POSTING_ID = "f5349e52-94b9-4eb7-aaea-e83b001854a3"  # Staff SWE — IAM (Serbia)

# (label, fabricated resume text, expected recommendation band)
GOLDEN_SET = [
    (
        "strong_iam_staff_fit",
        """
        FICTIONAL CANDIDATE — Jordan Rivers (synthetic test profile, not a real person)

        Staff Software Engineer, Identity Platform — FakeCorp (7 years)
        - Owned OAuth 2.0 / OIDC authorization server serving 40M+ daily token requests.
        - Designed token rotation and revocation framework with audit trails used org-wide.
        - Wrote the RFC that changed how all product teams handle session invalidation;
          adopted by 12 teams without further involvement from the author.
        - On-call escalation point for identity-platform production incidents for 3 years;
          led incident retros and drove the follow-up hardening work to completion.
        - Regularly reviews auth designs from other teams for security and compliance gaps
          (SOC2, GDPR token-handling requirements) before they ship.
        - Mentors two engineers toward staff scope; no formal management role.
        """,
        "strong yes",
    ),
    (
        "weak_generalist_fit",
        """
        FICTIONAL CANDIDATE — Sam Okafor (synthetic test profile, not a real person)

        Junior Full-Stack Developer — FakeStartup (1.5 years)
        - Built CRUD REST endpoints and React components for an internal admin tool.
        - Used a third-party auth library (Firebase Auth) for login/signup; did not modify
          its internals or design any auth protocol logic directly.
        - Fixed CSS bugs and wrote unit tests for existing endpoints.
        - No production incident ownership; escalates issues to a senior engineer.
        - No design docs or RFCs authored; works from tickets assigned by a lead.
        """,
        "no",
    ),
    (
        "borderline_adjacent_fit",
        """
        FICTIONAL CANDIDATE — Casey Lindqvist (synthetic test profile, not a real person)

        Senior Backend Engineer — FakeCorp (5 years), Platform Infra team (adjacent to IAM)
        - Designed the internal service-to-service token-issuance layer (JWT minting,
          expiry, rotation) used by ~15 backend services, though built on top of an
          off-the-shelf OIDC provider rather than owning the OIDC flows themselves.
        - Led the incident response for a token-expiry outage that took down checkout for
          40 minutes; was the primary escalation point and wrote the public postmortem.
        - Wrote an RFC proposing a shared session-invalidation pattern; adopted by 3 of 6
          teams it was pitched to, still under discussion with the rest.
        - Occasionally flags security concerns in design reviews (e.g. token scope
          creep) but has no formal compliance review responsibility.
        - Well-regarded senior IC, not yet operating at the cross-org staff scope the
          IAM platform role calls for.
        """,
        "maybe",
    ),
]


def _make_pdf(text: str) -> bytes:
    """Build a minimal, valid one-page PDF containing `text` — no external deps."""
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    y = 750
    content_ops = []
    for line in lines:
        escaped = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        content_ops.append(f"BT /F1 10 Tf 50 {y} Td ({escaped}) Tj ET")
        y -= 14
    content = "\n".join(content_ops).encode("latin-1", errors="replace")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
    ]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_offset = len(pdf)
    pdf += f"xref\n0 {len(objects) + 1}\n".encode()
    pdf += b"0000000000 65535 f \n"
    for off in offsets:
        pdf += f"{off:010d} 00000 n \n".encode()
    pdf += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF".encode()
    return bytes(pdf)


def main() -> None:
    rubric = load_rubric(POSTING_ID)
    client = OpenAI(api_key=get_openai_api_key())

    print(f"Golden-set eval against rubric: {rubric.posting_title} (model {MODEL})\n")

    failures = []
    for label, resume_text, expected_band in GOLDEN_SET:
        pdf_bytes = _make_pdf(resume_text)
        verdict, response = score_resume(client, rubric, pdf_bytes)
        overall = compute_overall_score(rubric, verdict)
        actual_band = recommendation_band(overall)
        status = "OK" if actual_band == expected_band else "MISMATCH"
        if status == "MISMATCH":
            failures.append(label)
        usage = response.usage
        print(
            f"[{status}] {label}: score={overall:.1f} band='{actual_band}' "
            f"(expected '{expected_band}') tokens in/out={usage.input_tokens}/{usage.output_tokens}"
        )
        print(f"    summary: {verdict.summary}")

    print()
    if failures:
        print(f"FAILED: {len(failures)}/{len(GOLDEN_SET)} profiles landed outside their expected band: {failures}")
        sys.exit(1)
    print(f"All {len(GOLDEN_SET)} synthetic profiles landed in their expected band.")


if __name__ == "__main__":
    main()
