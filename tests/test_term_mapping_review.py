from unittest.mock import AsyncMock

import pytest

from applications.jiayueyang.services.term_mapping_crud import RagTermMappingLearnedCrud
from core.exceptions import ParameterException


class _FakeMapping:
    def __init__(self, status="candidate"):
        self.learned_mapping_id = "learned-test"
        self.status = status
        self.reviewed_by = None
        self.reviewed_time = None
        self.save = AsyncMock()


class _FakeQuery:
    def __init__(self, row):
        self.row = row

    async def first(self):
        return self.row


class _FakeModel:
    row = _FakeMapping()

    @classmethod
    def filter(cls, **kwargs):
        return _FakeQuery(cls.row)


@pytest.mark.asyncio
async def test_candidate_can_be_activated_and_records_reviewer(monkeypatch):
    crud = RagTermMappingLearnedCrud()
    monkeypatch.setattr(crud, "model", _FakeModel)

    row = await crud.review("learned-test", "activate", "reviewer-a")

    assert row.status == "active"
    assert row.reviewed_by == "reviewer-a"
    assert row.reviewed_time is not None
    row.save.assert_awaited_once()


@pytest.mark.asyncio
async def test_active_mapping_cannot_be_activated_again(monkeypatch):
    crud = RagTermMappingLearnedCrud()
    active = _FakeMapping(status="active")
    _FakeModel.row = active
    monkeypatch.setattr(crud, "model", _FakeModel)

    with pytest.raises(ParameterException, match="只有 candidate 状态"):
        await crud.review("learned-test", "activate", "reviewer-a")


@pytest.mark.asyncio
async def test_review_requires_reviewer(monkeypatch):
    crud = RagTermMappingLearnedCrud()
    _FakeModel.row = _FakeMapping()
    monkeypatch.setattr(crud, "model", _FakeModel)

    with pytest.raises(ParameterException, match="审核人不能为空"):
        await crud.review("learned-test", "activate", "")
