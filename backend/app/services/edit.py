"""后期剪辑业务规则：状态流转、版本快照与流转记录都收在这里。

生命周期：待粗剪 → 粗剪中 → 待精剪 → 已交付，退回修改沿序列往回走一格。
每次状态变更都会写入一条流转记录（操作人、时间、交付日期）并追加一版版本快照，
空版本或读取失败时可以恢复到上一版。
"""
from __future__ import annotations

from datetime import datetime
from itertools import count
from typing import Any

from app.store import store

MODULE = "edit"
REQUIRED_FIELDS = ["任务编号", "所属集数", "剪辑师"]
OPTIONAL_FIELDS = ["粗剪版本", "精剪版本", "交付日期"]
STATUS_ORDER = ["待粗剪", "粗剪中", "待精剪", "已交付"]
STAGE_BY_STATUS = {"待粗剪": "粗剪", "粗剪中": "粗剪", "待精剪": "精剪", "已交付": "交付"}
# 流转台列：阶段 -> 覆盖的状态，列表、流转台、导出都按这同一份口径取数
STAGE_COLUMNS = [("粗剪", ["待粗剪", "粗剪中"]), ("精剪", ["待精剪"]), ("交付", ["已交付"])]
ACTION_RULES = {"开始粗剪": "粗剪中", "提交精剪": "待精剪", "确认交付": "已交付"}
RETURN_ACTION = "退回修改"
RESTORE_ACTION = "恢复上一版"
NEGATIVE_ACTIONS = [RETURN_ACTION]
DEFAULT_OPERATOR = "值班管理员"
CREATE_ACTION = "登记任务"

_log_seq = count(1)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _revision_count(entry: dict[str, Any]) -> int:
    """修改轮次在老数据里可能是样例文本，解析失败按 0 算。"""
    try:
        return int(str(entry.get("修改轮次") or "0").strip())
    except ValueError:
        return 0


def _append_version(entry: dict[str, Any], stage: str, operator: str) -> dict[str, Any]:
    versions = entry["versions"]
    versions.append({
        "版本": f"V{len(versions) + 1}",
        "阶段": stage,
        "状态": entry.get("status"),
        "操作人": operator,
        "时间": _now(),
        "交付日期": entry.get("交付日期"),
        "修改轮次": _revision_count(entry),
        "粗剪版本": entry.get("粗剪版本"),
        "精剪版本": entry.get("精剪版本"),
    })
    return versions[-1]


def _append_log(entry: dict[str, Any], action: str, from_status: str, operator: str) -> None:
    versions = entry["versions"]
    entry["flow_log"].append({
        "序号": next(_log_seq),
        "时间": _now(),
        "任务编号": entry.get("任务编号"),
        "操作人": operator,
        "动作": action,
        "从状态": from_status,
        "到状态": entry.get("status"),
        "版本": versions[-1]["版本"] if versions else "",
        "交付日期": entry.get("交付日期"),
        "修改轮次": _revision_count(entry),
    })


def _ensure_lifecycle(entry: dict[str, Any]) -> None:
    """老数据没有版本与流转记录：按当前状态补一份快照，保证能继续流转、能恢复。"""
    versions = entry.setdefault("versions", [])
    entry.setdefault("flow_log", [])
    if not versions:
        versions.append({
            "版本": "V1",
            "阶段": STAGE_BY_STATUS.get(str(entry.get("status") or ""), "粗剪"),
            "状态": entry.get("status"),
            "操作人": "历史数据",
            "时间": "",
            "交付日期": entry.get("交付日期"),
            "修改轮次": _revision_count(entry),
            "粗剪版本": entry.get("粗剪版本"),
            "精剪版本": entry.get("精剪版本"),
        })


class EditService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("任务编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is not None:
            _ensure_lifecycle(entry)
        return entry

    def create_entry(
        self,
        values: dict[str, Any],
        *,
        operator: str | None = None,
    ) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        for field in OPTIONAL_FIELDS:
            if str(values.get(field) or "").strip():
                entry[field] = values.get(field)
        entry["status"] = STATUS_ORDER[0]
        entry["剪辑状态"] = STATUS_ORDER[0]
        entry["修改轮次"] = 0
        entry["pending"] = True
        entry["abnormal"] = False
        entry["versions"] = []
        entry["flow_log"] = []
        rows.append(entry)
        operator = operator or DEFAULT_OPERATOR
        _append_version(entry, STAGE_BY_STATUS[STATUS_ORDER[0]], operator)
        _append_log(entry, CREATE_ACTION, "", operator)
        return entry, []

    def run_action(
        self,
        entry_id: int,
        action: str,
        *,
        operator: str | None = None,
        delivery_date: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"剪辑任务 {entry_id} 不存在或已归档"
        _ensure_lifecycle(entry)
        operator = operator or DEFAULT_OPERATOR
        if action in ACTION_RULES:
            return self._advance(entry, action, operator=operator, delivery_date=delivery_date)
        if action == RETURN_ACTION:
            return self._return_for_revision(entry, operator=operator)
        if action == RESTORE_ACTION:
            return self._restore_previous(entry, operator=operator)
        return None, f"动作「{action}」不属于后期剪辑可执行范围"

    def flow_board(self) -> dict[str, Any]:
        """剪辑版本流转台：按粗剪、精剪、交付分列，并汇总全部流转记录。"""
        rows = store.rows(MODULE)
        stages: list[dict[str, Any]] = []
        for stage, statuses in STAGE_COLUMNS:
            items = []
            for row in rows:
                if row.get("status") not in statuses:
                    continue
                _ensure_lifecycle(row)
                items.append({
                    "id": row.get("id"),
                    "任务编号": row.get("任务编号"),
                    "所属集数": row.get("所属集数"),
                    "剪辑师": row.get("剪辑师"),
                    "status": row.get("status"),
                    "当前版本": row["versions"][-1].get("版本"),
                    "修改轮次": _revision_count(row),
                    "交付日期": row.get("交付日期"),
                })
            stages.append({"stage": stage, "statuses": statuses, "count": len(items), "items": items})
        logs: list[dict[str, Any]] = []
        for row in rows:
            _ensure_lifecycle(row)
            logs.extend(row["flow_log"])
        logs.sort(key=lambda item: int(item.get("序号", 0)), reverse=True)
        return {"stages": stages, "logs": logs[:50], "total": len(rows)}

    def export_entries(self) -> tuple[list[dict[str, Any]], int]:
        """导出前补齐版本与流转记录，保证导出与列表、流转台是同一份数据。"""
        rows = store.rows(MODULE)
        for row in rows:
            _ensure_lifecycle(row)
        return rows, len(rows)

    def _advance(
        self,
        entry: dict[str, Any],
        action: str,
        *,
        operator: str,
        delivery_date: str | None,
    ) -> tuple[dict[str, Any] | None, str]:
        current = str(entry.get("status") or "")
        target = ACTION_RULES[action]
        if current not in STATUS_ORDER:
            return None, f"剪辑任务状态「{current}」无法识别，请先{RESTORE_ACTION}"
        if current == target:
            return None, f"剪辑任务已处于「{target}」，重复推进不会生效"
        if STATUS_ORDER.index(target) != STATUS_ORDER.index(current) + 1:
            return None, f"不能从「{current}」直接推进到「{target}」，请按 {'→'.join(STATUS_ORDER)} 顺序流转"
        if delivery_date:
            entry["交付日期"] = delivery_date
        if target == STATUS_ORDER[-1] and not str(entry.get("交付日期") or "").strip():
            entry["交付日期"] = _today()
        entry["status"] = target
        entry["剪辑状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = False
        _append_version(entry, STAGE_BY_STATUS[target], operator)
        _append_log(entry, action, current, operator)
        return entry, f"剪辑任务已{action}，当前版本 {entry['versions'][-1]['版本']}"

    def _return_for_revision(
        self,
        entry: dict[str, Any],
        *,
        operator: str,
    ) -> tuple[dict[str, Any] | None, str]:
        current = str(entry.get("status") or "")
        if current not in STATUS_ORDER:
            return None, f"剪辑任务状态「{current}」无法识别，请先{RESTORE_ACTION}"
        if current == STATUS_ORDER[0]:
            return None, f"剪辑任务还在「{STATUS_ORDER[0]}」，没有可退回的上一环节"
        target = STATUS_ORDER[STATUS_ORDER.index(current) - 1]
        entry["status"] = target
        entry["剪辑状态"] = target
        entry["修改轮次"] = _revision_count(entry) + 1
        entry["pending"] = True
        entry["abnormal"] = True
        _append_version(entry, "修改", operator)
        _append_log(entry, RETURN_ACTION, current, operator)
        return entry, f"剪辑任务已退回「{target}」，进入第 {entry['修改轮次']} 轮修改"

    def _restore_previous(
        self,
        entry: dict[str, Any],
        *,
        operator: str,
    ) -> tuple[dict[str, Any] | None, str]:
        versions = entry["versions"]
        if len(versions) < 2:
            return None, "只有一版记录，没有可恢复的上一版"
        broken = versions.pop()
        previous = versions[-1]
        restored = previous.get("状态")
        entry["status"] = restored if restored in STATUS_ORDER else STATUS_ORDER[0]
        entry["剪辑状态"] = entry["status"]
        entry["交付日期"] = previous.get("交付日期")
        entry["修改轮次"] = previous.get("修改轮次") or 0
        entry["粗剪版本"] = previous.get("粗剪版本")
        entry["精剪版本"] = previous.get("精剪版本")
        entry["pending"] = entry["status"] != STATUS_ORDER[-1]
        entry["abnormal"] = False
        _append_log(entry, RESTORE_ACTION, str(broken.get("状态") or "空版本"), operator)
        return entry, f"已恢复到上一版 {previous['版本']}（{previous['阶段']}），当前状态「{entry['status']}」"
