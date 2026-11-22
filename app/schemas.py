from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PasteMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=200, strict=True)
    language: str | None = Field(default=None, max_length=50, strict=True)

    @field_validator("title", "language")
    @classmethod
    def reject_metadata_null_character(cls, value: str | None) -> str | None:
        if value is not None and "\x00" in value:
            raise ValueError("metadata cannot contain U+0000")
        return value


class PasteCreate(PasteMetadata):
    content: str = Field(min_length=1, max_length=100_000, strict=True)

    @field_validator("content")
    @classmethod
    def reject_null_character(cls, value: str) -> str:
        # PostgreSQL TEXT cannot represent U+0000. All other text is unchanged.
        if "\x00" in value:
            raise ValueError("content cannot contain U+0000")
        return value


class PastePatch(PasteMetadata):
    pass


class PastePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    title: str | None
    language: str | None


class PasteCreated(PastePublic):
    management_key: str


class PasteRead(PastePublic):
    content: str
