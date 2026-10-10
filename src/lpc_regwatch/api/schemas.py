"""Pydantic models = schema/openapi.yaml components (camelCase on the wire), plus documented extensions.

Extensions never remove a contract field (README: "Teams may extend the contract but must not silently
remove traceability fields"). Added fields are marked `# ext` below.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Camel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class Evidence(Camel):
    sourceId: str
    sourceUrl: str
    collectedAt: datetime
    validationStatus: Literal["automatically_extracted", "to_verify", "validated", "rejected", "obsolete", "source_unavailable"]
    excerpt: str | None = None
    extractionMethod: str | None = None  # ext
    confidence: float | None = None  # ext
    snapshotId: int | None = None  # ext


class Product(Camel):
    productId: str
    commercialName: str
    activeEntityOriginal: str | None = None
    activeEntityNormalized: str | None = None
    formulationCode: str | None = None
    isSynthetic: bool = False
    strain: str | None = None  # ext
    countries: list[str] = Field(default_factory=list)  # ext: countries with a registration row
    matchedOn: str | None = None  # ext: why the search returned it (name | alias | active entity)


class AuthorizedUse(Camel):
    useId: str
    cropOriginal: str | None = None
    cropNormalized: str | None = None
    eppoCropCode: str | None = None
    eppoCropStatus: str | None = None  # ext: to_verify | validated | list | unmapped
    targetOriginal: str | None = None
    targetNormalized: str | None = None
    eppoTargetCode: str | None = None
    eppoTargetStatus: str | None = None  # ext
    applicationMethod: str | None = None  # ext
    doseValue: float | None = None
    doseUnitOriginal: str | None = None
    doseValueNormalized: float | None = None  # ext
    doseUnitNormalized: str | None = None  # ext
    maxApplications: int | None = None  # ext
    phiDays: float | None = None  # ext
    growthStageMin: str | None = None  # ext
    growthStageMax: str | None = None  # ext
    restrictionsOriginal: str | None = None
    pairing: str | None = None  # ext: source_paired | unpaired_lists | llm_paired
    evidence: Evidence


class Registration(Camel):
    registrationId: str
    productId: str
    countryCode: str
    authorityName: str
    registrationNumber: str | None = None
    statusOriginal: str | None = None  # ext
    statusNormalized: Literal["active", "expired", "withdrawn", "pending", "unknown"]
    approvalDate: str | None = None  # ext (YYYY-MM-DD)
    expirationDate: str | None = None  # ext
    holderOriginal: str | None = None  # ext
    activeEntityOriginal: str | None = None  # ext
    formulationOriginal: str | None = None  # ext
    isCurrent: bool = True  # ext
    usesCount: int = 0  # ext
    uses: list[AuthorizedUse] = Field(default_factory=list)
    evidence: Evidence


class RegistrationsResponse(Camel):
    items: list[Registration]
    warnings: list[str] = Field(default_factory=list)  # ext
    disclaimer: str


class ProductsResponse(Camel):
    items: list[Product]
    warnings: list[str] = Field(default_factory=list)  # ext
    disclaimer: str | None = None  # ext


class CountryCoverage(Camel):  # ext
    countryCode: str
    sourceId: str | None
    collectedAt: datetime | None
    coverage: Literal["found", "not_found_in_source", "source_not_collected"]
    note: str


class ComparisonResponse(Camel):
    productId: str
    countries: list[str]
    registrations: list[Registration]
    warnings: list[str]
    disclaimer: str
    coverage: list[CountryCoverage] = Field(default_factory=list)  # ext
    commercialName: str | None = None  # ext
    relatedProducts: list[dict] = Field(default_factory=list)  # ext: distinct linked products (sister, related), never merged


class AliasOut(Camel):  # ext
    aliasId: str
    productId: str
    aliasName: str
    countryCode: str | None
    relationshipType: str
    confidence: float | None
    evidence: str | None
    sourceRecordUrl: str | None
    reviewStatus: str


class AskRequest(BaseModel):
    question: str = Field(min_length=3)
    language: str = "fr"


class Answer(Camel):
    answer: str
    evidence: list[Evidence]
    warnings: list[str]
    disclaimer: str
    facts: list[dict] = Field(default_factory=list)  # ext: structured facts the answer is built from
    intent: str | None = None  # ext
    toolsUsed: list[str] = Field(default_factory=list)  # ext
    model: str | None = None  # ext: null when answered deterministically
    structured: dict | None = None  # ext: {headline, items[], caveats[]} (answer_model.StructuredAnswer)
    warningsLocalized: list[str] = Field(default_factory=list)  # ext: `warnings` in the question language (`warnings` itself stays English)


class ReviewRequest(BaseModel):
    entityType: Literal["registration", "use", "alias", "product"]
    entityId: str
    newStatus: Literal["to_verify", "validated", "rejected", "obsolete"]
    reviewer: str = Field(min_length=2)
    note: str | None = None


class ChangeOut(Camel):  # ext
    changeId: int
    entityType: str
    entityId: str
    field: str
    oldValue: str | None
    newValue: str | None
    fromSnapshotId: int | None
    toSnapshotId: int
    detectedAt: datetime
