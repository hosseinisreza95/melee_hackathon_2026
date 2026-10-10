"""Structured answer of /ask (Pydantic). Both the deterministic builder and the LLM produce this shape, so the
UI shows a headline, a compact table of only the relevant fields, optional sections (multi-part questions) and short
caveats — never raw rows.

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
    relationship: str | None = Field(None, description="for related/sister/alternative products only: relationship type and review status")
    sourceId: str | None = None
    collectedAt: str | None = Field(None, description="YYYY-MM-DD")
    url: str | None = Field(None, description="official source URL when the row is a source or an official record")


class AnswerSection(BaseModel):
    title: str = Field(..., description="short title of this part of the answer (e.g. 'Authorised uses')")
    text: str | None = Field(None, description="one or two sentences answering this part; max 320 chars")
    items: list[AnswerItem] = Field(default_factory=list, description="rows supporting this part; max 12")


class StructuredAnswer(BaseModel):
    headline: str = Field(..., description="one or two sentences that directly answer the question (or the first part of a multi-part question); no row dump; max 400 chars")
    items: list[AnswerItem] = Field(default_factory=list, description="only the rows needed to support the headline; max 12")
    sections: list[AnswerSection] = Field(default_factory=list, description="for multi-part questions only: one section per further part, in the order asked; max 4")
    caveats: list[str] = Field(default_factory=list, description="max 4 short caveats the reader must know (missing dose, unpaired lists, not proof of absence, hypothesis, no advice on use)")

    def to_text(self, lang: str = "fr") -> str:
        lines = [self.headline.strip()]
        lines += _item_lines(self.items)
        for s in self.sections[:4]:
            lines.append(f"## {s.title}" + (f" — {s.text}" if s.text else ""))
            lines += _item_lines(s.items)
        for c in self.caveats[:4]:
            lines.append(f"! {c}")
        return "\n".join(lines)


def _item_lines(items: list[AnswerItem]) -> list[str]:
    out = []
    for it in items[:12]:
        head = " · ".join(x for x in [it.country, it.product, (f"n° {it.registrationNumber}" if it.registrationNumber else None)] if x)
        tail = " · ".join(x for x in [it.status, (f"« {it.statusOriginal} »" if it.statusOriginal else None), (f"exp. {it.expiry}" if it.expiry else None),
                                     it.relationship, it.detail, (f"{it.sourceId} {it.collectedAt or ''}".strip() if it.sourceId else None), it.url] if x)
        out.append(f"- {head}: {tail}" if head else f"- {tail}")
    return out


SCHEMA = StructuredAnswer.model_json_schema()
