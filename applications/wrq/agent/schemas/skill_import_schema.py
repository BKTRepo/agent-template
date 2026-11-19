from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ImportFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int = Field(ge=0)
    path: str = Field(min_length=1, max_length=255)


class ImportManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    upload_mode: Literal["file", "directory", "zip"]
    files: list[ImportFile] = Field(min_length=1, max_length=1000)
    replaces_import_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    selected_root: str | None = Field(default=None, min_length=1, max_length=255)


class ImportSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    item_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    name: str = Field(min_length=1, max_length=128)
    class_id: int = Field(ge=1, le=2147483647)
    application_paso: str = Field(min_length=1, max_length=100)
    expected_revision: int | None = Field(default=None, ge=1)


class ImportRestart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    import_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class ImportConfirm(ImportRestart):
    model_config = ConfigDict(extra="forbid")
    import_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    items: list[ImportSelection] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def unique_items(self):
        if len({row.item_id for row in self.items}) != len(self.items):
            raise ValueError("候选技能不能重复提交")
        return self


class ImportName(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    item_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    name: str = Field(min_length=1, max_length=128)


class ImportNameCheck(ImportRestart):
    items: list[ImportName] = Field(min_length=1, max_length=50)
