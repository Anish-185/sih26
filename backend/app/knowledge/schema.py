"""Schema for a single knowledge-base item.

This is intentionally a flat structure: one `KnowledgeItem` maps cleanly to one row
in a future PostgreSQL table, so migrating later is straightforward.

Every item names the authority its source belongs to (`source_authority`). Most
items are BIS; the `legal_metrology` category holds official Legal Metrology
(Department of Consumer Affairs) texts. The two stay distinct: a Legal Metrology
item is never presented as BIS information.
"""

from __future__ import annotations

import datetime as dt
import re
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Category(str, Enum):
    """The knowledge categories the project supports."""

    BIS_GENERAL = "bis_general"
    INDIAN_STANDARDS = "indian_standards"
    CERTIFICATION = "certification"
    TESTING = "testing"
    LABORATORIES = "laboratories"
    HALLMARKING = "hallmarking"
    CONSUMER_INFORMATION = "consumer_information"
    FAQS = "faqs"
    LEGAL_METROLOGY = "legal_metrology"


class SourceAuthority(str, Enum):
    """The authority an item's official source belongs to.

    - BIS:             Bureau of Indian Standards.
    - LEGAL_METROLOGY: Legal Metrology, Department of Consumer Affairs (for example
                       the Legal Metrology (Packaged Commodities) Rules, 2011).
    """

    BIS = "BIS"
    LEGAL_METROLOGY = "LEGAL_METROLOGY"


class VerificationStatus(str, Enum):
    """How much we trust this item.

    - verified:   checked against an official BIS source by a human.
    - unverified: sourced from official BIS material but not yet double-checked.
    - sample:     development/demo placeholder. NOT official BIS data.
    """

    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    SAMPLE = "sample"


# Slug-style IDs keep references stable and URL-safe, e.g. "is-15757-scope".
_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class KnowledgeItem(BaseModel):
    """One traceable unit of BIS information."""

    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=True)

    # --- identity ---
    id: str = Field(description="Stable internal ID, slug form (e.g. 'is-15757-scope').")
    title: str = Field(min_length=3, max_length=200)
    category: Category

    # --- body ---
    content: str = Field(
        min_length=20,
        description="The knowledge text. Plain prose, quoted/paraphrased from the source.",
    )
    keywords: list[str] = Field(
        default_factory=list,
        description="Lowercase tags to help later keyword retrieval.",
    )

    # --- standard reference (when the item is about a specific Indian Standard) ---
    standard_number: str | None = Field(
        default=None,
        description="e.g. 'IS 15757:2007'. Required for the indian_standards category.",
    )

    # --- provenance / traceability ---
    source_authority: SourceAuthority = Field(
        default=SourceAuthority.BIS,
        description="BIS or LEGAL_METROLOGY. Must be LEGAL_METROLOGY exactly for the legal_metrology category.",
    )
    source_organization: str = Field(
        default="Bureau of Indian Standards (BIS)",
        description="Who publishes the source, e.g. 'Bureau of Indian Standards (BIS)'.",
    )
    source_url: str | None = Field(
        default=None,
        description="Official URL. Required when verification_status is 'verified'.",
    )
    document_name: str | None = Field(
        default=None,
        description="Name of the source document, if it is a document.",
    )
    reference: str | None = Field(
        default=None,
        description="Where in the source: section / clause / page number.",
    )

    # --- verification ---
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    last_verified: dt.date | None = Field(
        default=None,
        description="ISO date (YYYY-MM-DD) the item was last checked against its source.",
    )

    # ------------------------------------------------------------------ validators

    @field_validator("id")
    @classmethod
    def _id_is_slug(cls, v: str) -> str:
        if not _ID_PATTERN.match(v):
            raise ValueError(
                "id must be lowercase letters/digits separated by single hyphens "
                "(e.g. 'is-15757-scope')"
            )
        return v

    @field_validator("title", "content")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank or whitespace only")
        return v.strip()

    @field_validator("keywords")
    @classmethod
    def _keywords_lowercase_unique(cls, v: list[str]) -> list[str]:
        cleaned: list[str] = []
        for kw in v:
            k = kw.strip().lower()
            if not k:
                raise ValueError("keywords must not contain blank entries")
            if k not in cleaned:
                cleaned.append(k)
        return cleaned

    @field_validator("source_url")
    @classmethod
    def _url_looks_like_url(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not re.match(r"^https?://\S+$", v):
            raise ValueError("source_url must start with http:// or https://")
        return v

    @field_validator("last_verified")
    @classmethod
    def _not_in_future(cls, v: dt.date | None) -> dt.date | None:
        if v is not None and v > dt.date.today():
            raise ValueError("last_verified cannot be in the future")
        return v

    @model_validator(mode="after")
    def _cross_field_rules(self) -> "KnowledgeItem":
        status = self.verification_status  # str, because use_enum_values=True
        category = self.category

        if status == VerificationStatus.VERIFIED.value:
            if not self.source_url:
                raise ValueError("a 'verified' item must have a source_url")
            if not self.last_verified:
                raise ValueError("a 'verified' item must have a last_verified date")

        if status != VerificationStatus.SAMPLE.value and not self.source_url:
            raise ValueError(
                "non-sample items must have a source_url so they are traceable "
                "(use verification_status 'sample' for development placeholders)"
            )

        is_lm_category = category == Category.LEGAL_METROLOGY.value
        is_lm_source = self.source_authority == SourceAuthority.LEGAL_METROLOGY.value
        if is_lm_category != is_lm_source:
            raise ValueError(
                "source_authority must be 'LEGAL_METROLOGY' for items in the 'legal_metrology' "
                "category, and 'BIS' for every other category"
            )

        if category == Category.INDIAN_STANDARDS.value and not self.standard_number:
            raise ValueError(
                "items in the 'indian_standards' category must set standard_number"
            )

        return self
