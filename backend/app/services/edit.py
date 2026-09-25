"""后期剪辑版本流转台业务规则。

粗剪、精剪、交付与修改轮次都按生命周期记录：每次状态变更都会写入一条
流转记录（操作人、操作时间、交付日期、版本快照）。状态只能沿相邻节点
推进，不允许跳级；当前版本为空或读取失败时，可以回退到上一版快照。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "edit"
REQUIRED_FIELDS = ["任务编号", "所属集数", "剪辑师"]
# 粗剪 → 精剪 → 交付 的正向生命周期；「修改中」是交付环节的退回支链。
STATUS_ORDER = ["待粗剪", "粗剪中", "待精剪", "精剪中", "待交付", "已交付"]
REVISION_STATUS = "修改中"
FINAL_STATUS = "已交付"
# 看板分组顺序：修改中的任务与交付环节归到一组跟进。
BOARD_GROUPS = ["待粗剪", "粗剪中", "待精剪", "精剪中", "待交付", REVISION_STATUS, FINAL_STATUS]

# 动作 → 目标状态。退回后需要重新送交付，不能跳级。
ACTION_RULES = {
    "开始粗剪": "粗剪中",
    "提交粗剪": "待精剪",
    "开始精剪": "精剪中",
    "提交精剪": "待交付",
    "确认交付": FINAL_STATUS,
    "退回修改": REVISION_STATUS,
    "重新提交": "待交付",
}
# 触发异常标记的动作（退回属于负向流转，会在概览里计入异常量）。
NEGATIVE_ACTIONS = ["退回修改"]
# 提交类动作产出的版本环节（开始类动作只流转，不产版本）。
STAGE_BY_ACTION = {
    "提交粗剪": "粗剪",
    "提交精剪": "精剪",
    "确认交付": "交付",
}
VERSION_FIELD = {"粗剪": "粗剪版本", "精剪": "精剪版本", "交付": "交付版本"}
DEFAULT_OPERATOR = "值班管理员"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _parse_round(value: Any) -> int:
    """修改轮次尽量转整数；存量脏数据转不动就按 0 处理，不阻断流转。"""
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def _allowed_next(status: str) -> list[str]:
    """返回当前状态允许流转到的相邻状态，重复推进/跳级都会被拦。"""
    if status == REVISION_STATUS:
        return ["待交付"]
    if status == "待交付":
        # 交付审核不通过可以在确认前直接退回，也可以确认交付。
        return [FINAL_STATUS, REVISION_STATUS]
    if status == FINAL_STATUS:
        return [REVISION_STATUS]
    try:
        index = STATUS_ORDER.index(status)
    except ValueError:
        # 存量数据若出现未知状态，统一回收到生命周期起点再往后走。
        return [STATUS_ORDER[0]]
    return [STATUS_ORDER[index + 1]] if index + 1 < len(STATUS_ORDER) else []


class EditService:
    # ---- 读取 ----------------------------------------------------------------

    def _normalize(self, entry: dict[str, Any]) -> dict[str, Any]:
        """补齐新版本流转台字段，保证存量剪辑任务与交付结果继续可读。"""
        entry.setdefault("交付版本", "")
        entry.setdefault("粗剪版本", "")
        entry.setdefault("精剪版本", "")
        entry.setdefault("read_error", False)
        entry.setdefault("read_error_stage", "")
        entry.setdefault("versions", [])
        entry.setdefault("lifecycle", [])
        entry["修改轮次"] = _parse_round(entry.get("修改轮次", 0))
        status = str(entry.get("status") or STATUS_ORDER[0])
        if status not in STATUS_ORDER and status != REVISION_STATUS:
            status = STATUS_ORDER[0]
        entry["status"] = status
        # 「剪辑状态」列与内部 status 始终保持一致，列表与流程台口径才不会打架。
        entry["剪辑状态"] = status
        return entry

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        round_no: int | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = [self._normalize(dict(row)) for row in store.rows(MODULE)]
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("任务编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if round_no is not None:
            rows = [row for row in rows if int(row.get("修改轮次", 0)) == round_no]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return self._normalize(entry) if entry is not None else None

    def board(self) -> list[dict[str, Any]]:
        """流程台：按生命周期节点分组，退回修改的任务单独成列跟进。"""
        rows = [self._normalize(dict(row)) for row in store.rows(MODULE)]
        groups: list[dict[str, Any]] = []
        for status in BOARD_GROUPS:
            tasks = [row for row in rows if row.get("status") == status]
            groups.append({"status": status, "count": len(tasks), "tasks": tasks})
        return groups

    # ---- 写入 ----------------------------------------------------------------

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["剪辑状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["粗剪版本"] = ""
        entry["精剪版本"] = ""
        entry["交付版本"] = ""
        entry["交付日期"] = ""
        entry["修改轮次"] = 0
        entry["read_error"] = False
        entry["versions"] = []
        entry["lifecycle"] = [{
            "from": "",
            "to": STATUS_ORDER[0],
            "action": "登记任务",
            "operator": str(values.get("operator") or DEFAULT_OPERATOR),
            "time": _now(),
            "交付日期": "",
            "round": 0,
            "note": "剪辑任务登记，进入粗剪排队",
        }]
        rows.append(entry)
        return entry, []

    def _append_lifecycle(
        self,
        entry: dict[str, Any],
        *,
        action: str,
        target: str,
        operator: str,
        delivery_date: str,
        note: str = "",
        from_status: str | None = None,
    ) -> None:
        entry.setdefault("lifecycle", []).append({
            "from": entry.get("status") if from_status is None else from_status,
            "to": target,
            "action": action,
            "operator": operator,
            "time": _now(),
            "交付日期": delivery_date,
            "round": int(entry.get("修改轮次", 0)),
            "note": note,
        })

    def _push_version(self, entry: dict[str, Any], stage: str, version: str, operator: str) -> None:
        """登记一个版本快照；回退时按阶段取这里的最后一条。"""
        entry.setdefault("versions", []).append({
            "stage": stage,
            "version": version,
            "round": int(entry.get("修改轮次", 0)),
            "operator": operator,
            "time": _now(),
        })

    def run_action(
        self,
        entry_id: int,
        raw_action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        values = values or {}
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"剪辑任务 {entry_id} 不存在或已归档"
        self._normalize(entry)

        action = str(raw_action or "").strip()
        operator = str(values.get("operator") or DEFAULT_OPERATOR).strip() or DEFAULT_OPERATOR
        from_status = str(entry.get("status"))

        if action == "恢复上一版":
            return self._recover(entry, operator, values)

        if action not in ACTION_RULES:
            return None, f"动作「{raw_action}」不属于剪辑版本流转台可执行范围"
        target = ACTION_RULES[action]

        # 只能推进到相邻节点：重复点同一个动作、跨阶段跳级都会在这里被拦下。
        allowed = _allowed_next(str(entry["status"]))
        if target not in allowed:
            current = entry["status"]
            if target == current:
                return None, f"任务当前已是「{current}」，请勿重复推进"
            expected = "、".join(allowed) if allowed else "无（任务已交付，可退回修改）"
            return None, f"不能从「{current}」直接{action}到「{target}」，请先流转到：{expected}"

        delivery_date = ""
        note = ""

        if action == "退回修改":
            entry["修改轮次"] = int(entry.get("修改轮次", 0)) + 1
            entry["read_error"] = False
            note = str(values.get("remark") or "交付审核未通过，退回修改")
        elif action == "重新提交":
            # 修改完成重新送交付：精剪版本更新为本轮修改版，交付版本待确认时落定。
            version = self._resolve_version(entry, "精剪", values)
            entry["精剪版本"] = version
            self._push_version(entry, "精剪", version, operator)
            note = f"第 {entry['修改轮次']} 轮修改完成，重新提交交付"
        elif action in STAGE_BY_ACTION:
            stage = STAGE_BY_ACTION[action]
            version = self._resolve_version(entry, stage, values)
            if stage in ("粗剪", "精剪"):
                entry[VERSION_FIELD[stage]] = version
            self._push_version(entry, stage, version, operator)
            if action == "确认交付":
                entry["交付版本"] = version
                delivery_date = str(values.get("交付日期") or _today()).strip()
                entry["交付日期"] = delivery_date
                note = f"交付日期 {delivery_date}"
            elif stage == "精剪":
                note = f"精剪版本 {version} 送交付审核"
            else:
                note = f"粗剪版本 {version} 送精剪"

        entry["status"] = target
        entry["剪辑状态"] = target
        entry["pending"] = target != FINAL_STATUS
        entry["abnormal"] = action in NEGATIVE_ACTIONS or target == REVISION_STATUS
        entry["read_error"] = entry.get("read_error", False) and target == REVISION_STATUS
        self._append_lifecycle(
            entry,
            action=action,
            target=target,
            operator=operator,
            delivery_date=delivery_date,
            note=note,
            from_status=from_status,
        )
        return entry, f"剪辑任务已{action}，当前状态：{target}"

    def _resolve_version(self, entry: dict[str, Any], stage: str, values: dict[str, Any]) -> str:
        """取本次提交的版本号；没填就按「环节 V轮次.序号」自动编一个。"""
        field = VERSION_FIELD[stage]
        version = str(values.get("版本号") or values.get(field) or "").strip()
        if version:
            return version
        round_no = int(entry.get("修改轮次", 0))
        stage_versions = [v for v in entry.get("versions", []) if v.get("stage") == stage]
        seq = len(stage_versions) + 1
        suffix = f"-R{round_no}" if round_no else ""
        return f"{stage}V{seq}{suffix}"

    def _recover(
        self,
        entry: dict[str, Any],
        operator: str,
        values: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str]:
        """空版本或读取失败时恢复到上一版快照，不改变生命周期状态。"""
        stage = str(values.get("stage") or entry.get("read_error_stage") or "").strip()
        if not stage:
            # 默认恢复当前生命周期所处环节：粗剪段→粗剪，精剪/交付审核段→精剪，
            # 交付完成后→交付。修改中的任务拿到的是精剪返修版。
            stage = {
                "粗剪中": "粗剪",
                "待精剪": "粗剪",
                "精剪中": "精剪",
                "待交付": "精剪",
                "修改中": "精剪",
                "已交付": "交付",
            }.get(str(entry.get("status")), "")
        if stage not in VERSION_FIELD:
            return None, "恢复失败：未指定可恢复的版本环节（粗剪/精剪/交付）"

        current_version = str(entry.get(VERSION_FIELD[stage]) or "").strip()
        read_error = bool(entry.get("read_error"))
        failed_stage = str(entry.get("read_error_stage") or "")
        if read_error and failed_stage and failed_stage != stage:
            return None, f"当前登记的是{failed_stage}版本读取失败，请在该环节恢复"
        if current_version and not read_error:
            return None, f"{stage}版本「{current_version}」可读，无需恢复；仅空版本或读取失败时允许回退"

        snapshots = [
            v for v in entry.get("versions", [])
            if v.get("stage") == stage and str(v.get("version") or "").strip()
        ]
        if not snapshots:
            return None, f"没有可回退的{stage}历史版本，请重新提交版本"
        last = snapshots[-1]
        entry[VERSION_FIELD[stage]] = last["version"]
        entry["read_error"] = False
        entry["read_error_stage"] = ""
        self._append_lifecycle(
            entry,
            action="恢复上一版",
            target=str(entry["status"]),
            operator=operator,
            delivery_date=str(entry.get("交付日期") or ""),
            note=f"{stage}回退到版本 {last['version']}（{last['time']}）",
        )
        return entry, f"已恢复到上一版{stage}版本：{last['version']}"

    def mark_read_error(self, entry_id: int, values: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, str]:
        """登记一次版本读取失败：置标记后即可在流程台上执行「恢复上一版」。"""
        values = values or {}
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"剪辑任务 {entry_id} 不存在或已归档"
        self._normalize(entry)
        operator = str(values.get("operator") or DEFAULT_OPERATOR)
        stage = str(values.get("stage") or "").strip()
        if stage not in VERSION_FIELD:
            stage = {
                "粗剪中": "粗剪", "待精剪": "粗剪",
                "精剪中": "精剪", "待交付": "精剪", "修改中": "精剪",
                "已交付": "交付",
            }.get(str(entry.get("status")), "")
        entry["read_error"] = True
        entry["read_error_stage"] = stage
        self._append_lifecycle(
            entry,
            action="标记读取失败",
            target=str(entry["status"]),
            operator=operator,
            delivery_date=str(entry.get("交付日期") or ""),
            note=f"{stage}版本读取失败，等待回退" if stage else str(values.get("remark") or "当前版本读取失败，等待回退"),
        )
        return entry, f"已标记{stage or ''}版本读取失败，可执行恢复上一版"
