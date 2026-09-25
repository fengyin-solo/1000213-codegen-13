"""后期剪辑接口：维护剪辑任务，覆盖开始粗剪、提交精剪、确认交付、退回修改与恢复上一版。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.edit import EditService

router = APIRouter(prefix="/api/edit", tags=["后期剪辑"])

service = EditService()

LIST_FIELDS = ["任务编号", "所属集数", "剪辑师", "粗剪版本", "精剪版本", "交付日期", "修改轮次", "剪辑状态"]
STATUSES = ["待粗剪", "粗剪中", "待精剪", "已交付"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按任务编号检索"),
    status: str | None = Query(default=None, description="待粗剪、粗剪中、待精剪、已交付"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按任务编号与状态过滤后期剪辑列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/flow")
def flow_board() -> dict[str, Any]:
    """剪辑版本流转台：按粗剪、精剪、交付分列，并给出全量流转记录（操作人、时间、交付日期）。"""
    return service.flow_board()


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出后期剪辑清单：包含版本快照与流转记录，与列表、流转台保持同一份数据。"""
    items, total = service.export_entries()
    return {"module": "edit", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条剪辑任务明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"剪辑任务 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条剪辑任务，缺字段时说明原因而不是静默丢弃。"""
    operator = str(payload.values.get("操作人") or "").strip() or None
    entry, missing = service.create_entry(payload.values, operator=operator)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="剪辑任务已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条剪辑任务执行开始粗剪、提交精剪、确认交付、退回修改、恢复上一版。

    动作只能一格一格往前走，跳态或重复推进会被拦下并说明原因。
    """
    action = str(payload.values.get("action") or payload.action or "").strip()
    operator = str(payload.values.get("操作人") or "").strip() or None
    delivery_date = str(payload.values.get("交付日期") or "").strip() or None
    entry, message = service.run_action(
        entry_id, action, operator=operator, delivery_date=delivery_date
    )
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
