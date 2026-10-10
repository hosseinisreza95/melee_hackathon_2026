"""Structured answer of /ask (Pydantic). Both the deterministic builder and the LLM produce this shape, so the
UI shows a headline, a compact table of only the relevant fields, and short caveats — never raw rows.

The LLM receives the JSON schema of `StructuredAnswer` (OpenAI structured output) and the facts; it may only pick
and phrase, and every number/country it writes is checked by the grounding guard (ask.py).
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class AnswerItem(BaseModel):
    country: str | None = Field(None, description="ISO alpha-2 country code, e.g. FR")
    product: str | None = Field(None, description="commercial name exactly as in the facts")
    registrationNumber: str | None = Field(None, description="official number exactly as in the facts, or null")
    status: str | None = Field(None, description="normalised status (active, withdrawn, pending, expired, unknown) or a coverage state: not_found_in_source / source_not_collected")
    statusOriginal: str | None = Field(None, description="status wording of the source, verbatim")
    expiry: str | None = Field(None, description="YYYY-MM-DD or null")
    detail: str | None = Field(None, description="one short clause that answers the question for this row (e.g. 'Fraisier → pourriture grise, 0.25 kg/ha, DAR 1 j'); max 160 chars")
    relationship: str | None = Field(None, description="for related/sister products only: relationship type and review status")
    sourceId: str | None = None
    collectedAt: str | None = Field(None, description="YYYY-MM-DD")


class StructuredAnswer(BaseModel):
    headline: str = Field(..., description="one or two sentences that directly answer the question; no row dump; max 320 chars")
    items: list[AnswerItem] = Field(default_factory=list, description="only the rows needed to support the headline; max 12")
    caveats: list[str] = Field(default_factory=list, description="max 4 short caveats the reader must know (missing dose, unpaired lists, not proof of absence, hypothesis)")

    def to_text(self, lang: str = "fr") -> str:
        lines = [self.headline.strip()]
        for it in self.items[:12]:
            head = " · ".join(x for x in [it.country, it.product, (f"n° {it.registrationNumber}" if it.registrationNumber else None)] if x)
            tail = " · ".join(x for x in [it.status, (f"« {it.statusOriginal} »" if it.statusOriginal else None), (f"exp. {it.expiry}" if it.expiry else None),
                                         it.relationship, it.detail, (f"{it.sourceId} {it.collectedAt or ''}".strip() if it.sourceId else None)] if x)
            lines.append(f"- {head}: {tail}" if head else f"- {tail}")
        for c in self.caveats[:4]:
            lines.append(f"! {c}")
        return "\n".join(lines)


SCHEMA = StructuredAnswer.model_json_schema()
