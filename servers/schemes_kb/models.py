from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceItem(Record):
    text: str = Field(min_length=1)
    source_url: HttpUrl
    source_path: str
    channel: str | None = None
    heading: str | None = None


class Section(Record):
    capture_status: Literal["captured", "partial", "not_in_source", "not_collected"]
    items: list[SourceItem] = Field(default_factory=list)


class SchemeSections(Record):
    details: Section
    benefits: Section
    eligibility: Section
    exclusions: Section
    application_process: Section
    required_documents: Section


class ResourceLink(Record):
    title: str
    type: Literal["application_form", "application_portal", "guidelines", "other"]
    url: HttpUrl
    source_url: HttpUrl
    format: Literal["pdf", "webpage", "unknown"]
    verification_status: Literal["pending", "checked", "broken"] = "pending"


class Scheme(Record):
    scheme_id: str = Field(min_length=1)
    slug: str
    name: str
    government_level: Literal["Central", "State"]
    geography: str
    source_url: HttpUrl
    collected_on: date
    review_status: Literal["draft", "needs_correction", "approved"] = "draft"
    availability_status: Literal["unverified", "open", "closed"] = "unverified"
    sample_only: bool = False
    sections: SchemeSections
    links: list[ResourceLink] = Field(default_factory=list)
