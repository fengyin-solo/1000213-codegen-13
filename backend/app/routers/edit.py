"""剪辑版本流转台接口。

维护剪辑任务的粗剪、精剪、交付与修改轮次生命周期；列表、流程台与导出
共用同一份数据，退回修改后三处同步切换。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.edit import FINAL_STATUS, REVISION_STATUS, STATUS_ORDER, EditService

router = APIRouter(prefix="/api/edit", tags=["后期剪辑"])

service = EditService()

LIST_FIELDS = ["任务编号", "所属集数", "剪辑师", "粗剪版本", "精剪版本", "交付版本", "交付日期", "修改轮次", "剪辑状态"]
STATUSES = STATUS_ORDER + [REVISION_STATUS]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按任务编号检索"),
    status: str | None = Query(default=None, description="生命周期状态，含修改中"),
    round_no: int | None = Query(default=None, alias="round", description="按修改轮次筛选"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按任务编号、状态或修改轮次过滤剪辑任务；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, round_no=round_no, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/board")
def board() -> dict[str, Any]:
    """流程台：按生命周期节点返回分组任务，退回修改的任务进入「修改中」列。"""
    groups = service.board()
    return {
        "module": "edit",
        "order": list(STATUS_ORDER),
        "revision_status": REVISION_STATUS,
        "final_status": FINAL_STATUS,
        "groups": groups,
        "total": sum(group["count"] for group in groups),
    }


@router.get("/export")
def export_entries(
    status: str | None = Query(default=None, description="可选：按状态导出"),
    round_no: int | None = Query(default=None, alias="round", description="可选：按修改轮次导出"),
) -> dict[str, Any]:
    """导出剪辑版本流转清单：含生命周期与版本快照，口径与列表/流程台一致。"""
    items, total = service.list_entries(status=status, round_no=round_no, page=1, size=10000)
    return {
        "module": "edit",
        "total": total,
        "statuses": STATUSES,
        "items": items,
    }


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条剪辑任务明细（含生命周期记录与版本快照）。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"剪辑任务 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条剪辑任务，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="剪辑任务已登记，进入粗剪排队", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """执行生命周期动作；只能推进到相邻状态，重复推进或跳级会被拦下。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/recover", response_model=ActionResult)
def recover_version(entry_id: int, payload: EntryPayload) -> ActionResult:
    """空版本或读取失败时恢复到上一版快照，不改变当前生命周期状态。"""
    entry, message = service.run_action(entry_id, "恢复上一版", payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/read-error", response_model=ActionResult)
def mark_read_error(entry_id: int, payload: EntryPayload) -> ActionResult:
    """登记一次版本读取失败，之后即可在流程台上恢复到上一版。"""
    entry, message = service.mark_read_error(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
