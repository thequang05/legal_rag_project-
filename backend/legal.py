"""Explicit, reviewer-supplied legal metadata; never infer legal validity from a PDF."""
from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class LegalMetadata(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    document_code: str = Field(default='', max_length=200)
    title: str = Field(default='', max_length=500)
    version: str = Field(default='1', min_length=1, max_length=80)
    source_url: str = Field(default='', max_length=2000)
    source_note: str = Field(default='', max_length=2000)
    effective_from: date | None = None
    effective_to: date | None = None
    validity_note: str = Field(default='', max_length=2000)

    @model_validator(mode='after')
    def validate_metadata(self):
        if not self.version:
            raise ValueError('Phiên bản không được rỗng.')
        if self.source_url:
            HttpUrl(self.source_url)
        if self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            raise ValueError('Ngày hết hiệu lực phải từ ngày có hiệu lực trở đi.')
        return self


class MetadataUpdate(LegalMetadata):
    expected_revision: int = Field(ge=1)
    actor: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    expected_revision: int = Field(ge=1)
    decision: Literal['approved', 'rejected', 'draft']
    actor: str = Field(min_length=1, max_length=200)
    note: str = Field(min_length=1, max_length=2000)


class RelationshipRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    expected_revision: int = Field(ge=1)
    target_id: str = Field(min_length=1, max_length=100)
    kind: Literal['amends', 'replaces']
    effective_on: date | None = None
    note: str = Field(min_length=1, max_length=2000)
    actor: str = Field(min_length=1, max_length=200)


def validity(document, on=None):
    on = str(on or date.today())
    if document['effective_from'] and on < document['effective_from']:
        return 'not_yet_effective'
    if document['effective_to'] and on >= document['effective_to']:
        return 'expired'
    if not document['effective_from']:
        return 'unknown'
    return 'within_recorded_dates'
