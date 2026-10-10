"""SQLAlchemy models = canonical data model (docs/DATA_MODEL.md).

Column names deliberately equal the starter-kit CSV headers so that export -> CSV passes
scripts/validate_data.py without renaming. Traceability columns are NOT NULL by design.
"""
from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ValidationStatus(str, enum.Enum):
    automatically_extracted = "automatically_extracted"
    to_verify = "to_verify"
    validated = "validated"
    rejected = "rejected"
    obsolete = "obsolete"
    source_unavailable = "source_unavailable"


class RegStatus(str, enum.Enum):
    active = "active"
    expired = "expired"
    withdrawn = "withdrawn"
    pending = "pending"
    unknown = "unknown"


class ExtractionMethod(str, enum.Enum):
    csv_parser = "csv_parser"
    json_parser = "json_parser"
    llm_pdf = "llm_pdf"
    manual = "manual"


class AliasRelation(str, enum.Enum):
    alternate_name = "alternate_name"
    historical_name = "historical_name"
    sister_product_candidate = "sister_product_candidate"
    confirmed_sister_product = "confirmed_sister_product"
    related_formulation = "related_formulation"
    related_product = "related_product"  # distinct product sharing strain/name history (LPC answer 2026-10-10); never merged


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# --------------------------------------------------------------------------- sources & evidence
class Source(Base):
    __tablename__ = "sources"
    source_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    official_name: Mapped[str] = mapped_column(String(200))
    country_or_region: Mapped[str] = mapped_column(String(60))
    base_url: Mapped[str] = mapped_column(Text)
    access_method: Mapped[str] = mapped_column(String(30))  # web|api|download|sftp|manual_extract
    data_format: Mapped[str] = mapped_column(String(100))
    license_name: Mapped[str | None] = mapped_column(String(200))
    access_and_reuse_limits: Mapped[str | None] = mapped_column(Text)
    manual_validation_required: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)


class Snapshot(Base):
    """One collector run for one source. Temporal anchor for every row."""

    __tablename__ = "snapshots"
    snapshot_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.source_id"), index=True)
    collected_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    collector_version: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="ok")  # ok|failed|partial
    notes: Mapped[str | None] = mapped_column(Text)


class RawDocument(Base):
    """What was actually fetched (CSV, JSON, PDF). Kept so we can re-parse without re-downloading."""

    __tablename__ = "raw_documents"
    raw_document_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.snapshot_id"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.source_id"), index=True)
    url: Mapped[str] = mapped_column(Text)
    local_path: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(String(120))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    bytes: Mapped[int] = mapped_column(Integer)
    collected_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    document_kind: Mapped[str] = mapped_column(String(30))  # extract_csv|api_json|label_pdf|zip|html


# --------------------------------------------------------------------------- products
class Product(Base):
    __tablename__ = "products"
    product_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    commercial_name: Mapped[str] = mapped_column(String(400), index=True)
    active_entity_original: Mapped[str | None] = mapped_column(Text)
    active_entity_normalized: Mapped[str | None] = mapped_column(Text)
    strain: Mapped[str | None] = mapped_column(String(120))
    formulation_code: Mapped[str | None] = mapped_column(String(20))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    validation_status: Mapped[ValidationStatus] = mapped_column(Enum(ValidationStatus), default=ValidationStatus.automatically_extracted)

    aliases: Mapped[list["ProductAlias"]] = relationship(back_populates="product")
    registrations: Mapped[list["Registration"]] = relationship(back_populates="product")


class ProductAlias(Base):
    __tablename__ = "product_aliases"
    alias_id: Mapped[str] = mapped_column(String(400), primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.product_id"), index=True)
    alias_name: Mapped[str] = mapped_column(String(400), index=True)
    country_code: Mapped[str | None] = mapped_column(String(2))
    relationship_type: Mapped[AliasRelation] = mapped_column(Enum(AliasRelation))
    confidence: Mapped[float | None] = mapped_column(Float)
    evidence: Mapped[str | None] = mapped_column(Text)
    source_record_url: Mapped[str | None] = mapped_column(Text)
    review_status: Mapped[ValidationStatus] = mapped_column(Enum(ValidationStatus), default=ValidationStatus.to_verify)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)

    product: Mapped[Product] = relationship(back_populates="aliases")


# --------------------------------------------------------------------------- registrations & uses
class Registration(Base):
    __tablename__ = "registrations"
    registration_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.product_id"), index=True)
    country_code: Mapped[str] = mapped_column(String(2), index=True)
    authority_name: Mapped[str] = mapped_column(String(300))
    registration_number: Mapped[str | None] = mapped_column(String(80), index=True)
    holder_original: Mapped[str | None] = mapped_column(String(400))
    status_original: Mapped[str | None] = mapped_column(String(150))
    status_normalized: Mapped[RegStatus] = mapped_column(Enum(RegStatus), default=RegStatus.unknown)
    approval_date: Mapped[dt.date | None] = mapped_column(DateTime)
    expiration_date: Mapped[dt.date | None] = mapped_column(DateTime)
    formulation_original: Mapped[str | None] = mapped_column(Text)
    active_entity_original: Mapped[str | None] = mapped_column(Text)
    # --- traceability (NOT NULL by design: G2)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.source_id"), index=True)
    source_record_url: Mapped[str] = mapped_column(Text)
    collected_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.snapshot_id"), index=True)
    raw_document_id: Mapped[int | None] = mapped_column(ForeignKey("raw_documents.raw_document_id"))
    extraction_method: Mapped[ExtractionMethod] = mapped_column(Enum(ExtractionMethod))
    evidence_excerpt: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    validation_status: Mapped[ValidationStatus] = mapped_column(Enum(ValidationStatus), default=ValidationStatus.automatically_extracted, index=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)  # false once superseded by a newer snapshot

    product: Mapped[Product] = relationship(back_populates="registrations")
    uses: Mapped[list["AuthorizedUse"]] = relationship(back_populates="registration")


class AuthorizedUse(Base):
    __tablename__ = "uses"
    use_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    registration_id: Mapped[str] = mapped_column(ForeignKey("registrations.registration_id"), index=True)
    crop_name_original: Mapped[str | None] = mapped_column(Text)
    crop_name_normalized: Mapped[str | None] = mapped_column(Text)
    eppo_crop_code: Mapped[str | None] = mapped_column(String(10))
    eppo_crop_status: Mapped[str | None] = mapped_column(String(12))  # to_verify|validated|list|unmapped
    target_name_original: Mapped[str | None] = mapped_column(Text)
    target_name_normalized: Mapped[str | None] = mapped_column(Text)
    eppo_target_code: Mapped[str | None] = mapped_column(String(10))
    eppo_target_status: Mapped[str | None] = mapped_column(String(12))
    application_method: Mapped[str | None] = mapped_column(Text)
    dose_value: Mapped[float | None] = mapped_column(Float)
    dose_unit_original: Mapped[str | None] = mapped_column(String(120))
    dose_unit_normalized: Mapped[str | None] = mapped_column(String(60))
    dose_value_normalized: Mapped[float | None] = mapped_column(Float)
    max_applications: Mapped[int | None] = mapped_column(Integer)
    application_interval_days: Mapped[float | None] = mapped_column(Float)
    phi_days: Mapped[float | None] = mapped_column(Float)
    rei_hours: Mapped[float | None] = mapped_column(Float)
    growth_stage_min: Mapped[str | None] = mapped_column(String(40))  # BBCH
    growth_stage_max: Mapped[str | None] = mapped_column(String(40))
    restrictions_original: Mapped[str | None] = mapped_column(Text)
    use_status_original: Mapped[str | None] = mapped_column(String(120))
    # CA/US give sites[] and pests[] as independent lists -> pairing is not asserted by the source
    pairing: Mapped[str] = mapped_column(String(20), default="source_paired")  # source_paired|unpaired_lists|llm_paired
    # --- traceability
    source_record_url: Mapped[str] = mapped_column(Text)
    collected_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    raw_document_id: Mapped[int | None] = mapped_column(ForeignKey("raw_documents.raw_document_id"))
    extraction_method: Mapped[ExtractionMethod] = mapped_column(Enum(ExtractionMethod))
    evidence_excerpt: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    validation_status: Mapped[ValidationStatus] = mapped_column(Enum(ValidationStatus), default=ValidationStatus.automatically_extracted, index=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    registration: Mapped[Registration] = relationship(back_populates="uses")


# --------------------------------------------------------------------------- history & review
class ChangeLog(Base):
    """Field-level difference between two snapshots of the same entity (bonus: change detection)."""

    __tablename__ = "change_log"
    change_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(20))  # registration|use|product
    entity_id: Mapped[str] = mapped_column(String(400), index=True)
    field: Mapped[str] = mapped_column(String(60))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    from_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("snapshots.snapshot_id"))
    to_snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.snapshot_id"))
    detected_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ReviewLog(Base):
    """Every human change of validation_status (Regulatory Affairs validation procedure)."""

    __tablename__ = "review_log"
    review_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[str] = mapped_column(String(400), index=True)
    old_status: Mapped[str] = mapped_column(String(30))
    new_status: Mapped[str] = mapped_column(String(30))
    reviewer: Mapped[str] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
