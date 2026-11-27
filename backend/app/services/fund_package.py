"""费用交账包领域服务。

面向竣工总结执行备案的费用交账场景：
- 从指定竣工报告出发，按报告施工范围冻结一版费用快照（核准支出、负数退款、关联签证）；
- 未核准费用不得进入实付净额，退款按原支出归属抵减，超范围支出不得装入；
- 包内合计、条目与附件清单来自同一数据时点，快照一经生成不再随后续业务变动；
- 备案只确认一次：重复提交保留同一费用确认，不产生新包、不改写净额；
- 出现新核准行时可再发起一份交账包，旧备案与新报告各自按自己的证据办理。
"""
from __future__ import annotations

import copy
import re
from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store

APPROVED_STATUS = "已核准"
PACK_STATUS_PENDING = "待备案"
PACK_STATUS_FILED = "已备案"


class FundPackageService(BaseModuleService):
    MODULE = "fund_package"
    ENTITY = "费用交账包"
    OPERATION_TERM = "提交备案"
    LIST_FIELDS = [
        "交账包编号", "关联报告", "报告名称", "编制人", "生成时间", "数据时点",
        "支出合计", "退款合计", "实付净额", "条目数", "附件数", "备案时间", "备案说明",
    ]
    REQUIRED_FIELDS: list[str] = []
    STATUS_ORDER = [PACK_STATUS_PENDING, PACK_STATUS_FILED]
    ACTION_RULES = {"提交备案": PACK_STATUS_FILED}
    NEGATIVE_ACTIONS: list[str] = []

    # ── 范围与归属判定 ──
    @staticmethod
    def _report_scope(report: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(report.get("修缮项目") or "").strip(),
            str(report.get("开工日期") or "").strip(),
            str(report.get("竣工日期") or "").strip(),
        )

    @staticmethod
    def _in_scope(row: dict[str, Any], scope: str, start: str, end: str) -> bool:
        """判断支出是否属于报告施工范围。

        显式填写了「施工范围」的以范围归属为准；未填写的回退到报告工期内的支出日期。
        """
        row_scope = str(row.get("施工范围") or "").strip()
        if row_scope:
            return row_scope == scope
        row_date = str(row.get("支出日期") or "").strip()
        if row_date and start and end:
            return start <= row_date <= end
        return False

    @staticmethod
    def _to_amount(value: Any) -> float:
        try:
            return round(float(value or 0), 2)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _visa_ids_for_row(row: dict[str, Any]) -> set[int]:
        ids: set[int] = set()
        linked = str(row.get("关联签证") or "")
        for part in re.split(r"[,，;；\s]+", linked):
            if part.isdigit():
                ids.add(int(part))
        for match in re.findall(r"变更签证#(\d+)", str(row.get("备注说明") or "")):
            ids.add(int(match))
        return ids

    # ── 快照构建（同一数据时点，合计与附件不得跨时点拼接） ──
    def build_snapshot(self, report_id: int) -> tuple[dict[str, Any] | None, str]:
        report = store.find("completion_summary", report_id)
        if report is None:
            return None, f"竣工报告 {report_id} 不存在，无法生成费用交账包"

        scope, start, end = self._report_scope(report)
        data_as_of = datetime.now().isoformat(timespec="microseconds")

        entries: list[dict[str, Any]] = []
        excluded: list[dict[str, Any]] = []
        included_ids: set[int] = set()

        for row in store.rows("funding_use"):
            amount = self._to_amount(row.get("实际金额"))
            base = {
                "id": row.get("id"),
                "支出项目": row.get("支出项目", ""),
                "支出类别": row.get("支出类别", ""),
                "实际金额": amount,
                "支出日期": row.get("支出日期", ""),
                "经办人": row.get("经办人", ""),
                "施工范围": str(row.get("施工范围") or ""),
                "status": row.get("status", ""),
                "凭证编号": row.get("凭证编号", ""),
            }

            # 规则 1：超出报告施工范围的支出不得装入
            if not self._in_scope(row, scope, start, end):
                excluded.append({**base, "原因": "超出报告施工范围，不得装入本交账包"})
                continue

            # 规则 2：未核准费用不得进入实付净额（迟到的未核准退款也在此留痕说明）
            if row.get("status") != APPROVED_STATUS:
                excluded.append({
                    **base,
                    "原因": f"审批状态为「{row.get('status', '')}」，未核准费用不得进入实付净额",
                })
                continue

            if amount < 0:
                # 规则 3：退款按原支出归属抵减
                raw_origin = row.get("关联支出")
                reason = ""
                origin_id: int | None = None
                if raw_origin in (None, ""):
                    reason = "退款未标注原支出，无法按原支出归属抵减"
                else:
                    try:
                        origin_id = int(raw_origin)
                    except (TypeError, ValueError):
                        reason = f"退款关联原支出「{raw_origin}」无法识别"
                    else:
                        origin = store.find("funding_use", origin_id)
                        if origin is None:
                            reason = f"退款关联的原支出#{origin_id}不存在，无法归属抵减"
                        elif not self._in_scope(origin, scope, start, end):
                            reason = f"原支出#{origin_id}不属于本报告施工范围，退款不得在本包抵减"
                        elif origin.get("status") != APPROVED_STATUS:
                            reason = f"原支出#{origin_id}尚未核准，退款暂不具备抵减条件"
                if reason:
                    excluded.append({**base, "原因": reason})
                    continue
                entries.append({
                    **copy.deepcopy(row),
                    "实际金额": amount,
                    "条目类型": "退款抵减",
                    "归属原支出": origin_id,
                    "入包说明": f"按原支出#{origin_id}归属抵减",
                })
            else:
                entries.append({
                    **copy.deepcopy(row),
                    "实际金额": amount,
                    "条目类型": "核准支出",
                    "归属原支出": None,
                    "入包说明": "已核准支出，计入实付净额",
                })
            included_ids.add(int(row.get("id")))

        # 关联签证：只装入与包内核准支出挂钩且已签认的签证，作为净额凭据
        visa_ids: set[int] = set()
        for entry in entries:
            visa_ids.update(self._visa_ids_for_row(entry))
        visas: list[dict[str, Any]] = []
        pending_visas: list[dict[str, Any]] = []
        for visa_id in sorted(visa_ids):
            visa = store.find("change_order", visa_id)
            if visa is None:
                pending_visas.append({"id": visa_id, "status": "", "原因": "关联签证不存在"})
                continue
            if visa.get("status") != "已签认":
                pending_visas.append({
                    "id": visa_id,
                    "status": visa.get("status", ""),
                    "原因": "签证尚未签认，不进入本包凭据",
                })
                continue
            visas.append(copy.deepcopy(visa))

        gross = round(sum(
            e["实际金额"] for e in entries if e["实际金额"] >= 0
        ), 2)
        refund_total = round(sum(
            -e["实际金额"] for e in entries if e["实际金额"] < 0
        ), 2)
        net_amount = round(gross - refund_total, 2)

        # 附件清单与条目、签证在同一时点冻结，杜绝合计与附件来自两个处理时点
        attachments: list[dict[str, Any]] = []
        for entry in entries:
            proof = str(entry.get("凭证编号") or "").strip()
            attachments.append({
                "凭证编号": proof or f"支出#{entry.get('id')}",
                "来源类型": entry["条目类型"],
                "来源id": entry.get("id"),
                "来源名称": entry.get("支出项目", ""),
            })
        for visa in visas:
            attachments.append({
                "凭证编号": f"变更签证#{visa.get('id')}",
                "来源类型": "变更签证",
                "来源id": visa.get("id"),
                "来源名称": visa.get("变更事项", ""),
            })

        snapshot = {
            "report_id": report_id,
            "报告名称": report.get("修缮项目", ""),
            "施工范围": scope,
            "开工日期": start,
            "竣工日期": end,
            "数据时点": data_as_of,
            "entries": entries,
            "excluded": excluded,
            "visas": visas,
            "pending_visas": pending_visas,
            "attachments": attachments,
            "included_ids": sorted(included_ids),
            "totals": {
                "支出合计": gross,
                "退款合计": refund_total,
                "实付净额": net_amount,
                "条目数": len(entries),
                "签证数": len(visas),
                "附件数": len(attachments),
                "排除条数": len(excluded),
            },
        }
        return snapshot, ""

    # ── 生成交账包 ──
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        # 交账包必须由竣工报告驱动生成，以冻结完整快照；禁止通用登记绕过
        return None, ["费用交账包不能直接登记，请从竣工报告生成（POST /api/fund-packages/reports/{报告id}）"]

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        # 通用动作入口同样收口到备案流程，保证费用确认只保留一次
        if action == "提交备案":
            return self.file_package(entry_id)
        return None, f"动作「{action}」不属于{self.MODULE}可执行范围"

    def create_package(self, report_id: int) -> tuple[dict[str, Any] | None, str]:
        report = store.find("completion_summary", report_id)
        if report is None:
            return None, f"竣工报告 {report_id} 不存在，无法生成费用交账包"

        resource_key = f"fund_package:report:{report_id}"
        if not store.acquire_resource(resource_key):
            return None, "该报告的交账包正在生成中，请稍后重试"
        try:
            snapshot, err = self.build_snapshot(report_id)
            if snapshot is None:
                return None, err

            # 同一数据状态下重复发起：复用已有待备案包，不重复生成费用确认
            for existing in reversed(store.rows(self.MODULE)):
                if existing.get("关联报告") != report_id:
                    continue
                if existing.get("status") != PACK_STATUS_PENDING:
                    continue
                if not self._new_rows_after(existing):
                    return existing, (
                        f"当前数据与交账包{existing.get('交账包编号')}一致，"
                        "未重复生成；出现新核准行后可再发起新包"
                    )

            rows = store.rows(self.MODULE)
            package_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1
            now = snapshot["数据时点"]
            totals = snapshot["totals"]
            package = {
                "id": package_id,
                "交账包编号": f"FPK-{report_id}-{package_id:03d}",
                "关联报告": report_id,
                "报告名称": snapshot["报告名称"],
                "编制人": report.get("编制人", ""),
                "生成时间": now,
                "数据时点": now,
                "status": PACK_STATUS_PENDING,
                "pending": True,
                "abnormal": False,
                "支出合计": totals["支出合计"],
                "退款合计": totals["退款合计"],
                "实付净额": totals["实付净额"],
                "条目数": totals["条目数"],
                "附件数": totals["附件数"],
                "备案时间": None,
                "备案说明": "",
                "快照": snapshot,
            }
            rows.append(package)

            # 竣工总结的备案待办随交账包更新
            report["交账包状态"] = PACK_STATUS_PENDING
            report["最新交账包"] = package_id
            report["费用待办"] = f"费用交账包{package['交账包编号']}待备案，请按包内凭据核对净额"
            return package, f"费用交账包已生成，数据时点 {now}，实付净额 {totals['实付净额']:.2f} 元"
        finally:
            store.release_resource(resource_key)

    # ── 备案：重复提交只保留一次费用确认 ──
    def file_package(
        self, package_id: int, remark: str | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        package = store.find(self.MODULE, package_id)
        if package is None:
            return None, f"费用交账包 {package_id} 不存在"
        if package.get("status") == PACK_STATUS_FILED:
            return package, (
                f"交账包{package.get('交账包编号')}已备案，费用确认只保留一次，"
                "净额与签证凭据仍可按原快照复核"
            )

        resource_key = f"{self.MODULE}:{package_id}"
        if not store.acquire_resource(resource_key):
            return None, "交账包正在备案处理中，请稍后重试"
        try:
            filed_at = datetime.now().isoformat(timespec="microseconds")
            snapshot = package["快照"]
            note = remark or "编制人按包内凭据逐条核对净额无误，提交备案"
            package["status"] = PACK_STATUS_FILED
            package["pending"] = False
            package["备案时间"] = filed_at
            package["备案说明"] = note
            # 快照保持冻结：已备案净额和当时签证凭据仍可复核

            report = store.find("completion_summary", package["关联报告"])
            if report is not None:
                report["交账包状态"] = PACK_STATUS_FILED
                report["备案交账包"] = package_id
                report["备案净额"] = package["实付净额"]
                report["备案快照时点"] = package["数据时点"]
                report["费用待办"] = (
                    f"费用交账包{package['交账包编号']}已备案，"
                    f"实付净额 {package['实付净额']:.2f} 元（数据时点 {package['数据时点']}）"
                )
            return package, (
                f"交账包{package['交账包编号']}备案成功，实付净额 "
                f"{package['实付净额']:.2f} 元已确认"
            )
        finally:
            store.release_resource(resource_key)

    # ── 新核准行侦测：支撑“出现新核准行时再发起一份交账包” ──
    def _diff_approved_ids(self, snapshot: dict[str, Any]) -> set[int]:
        report = store.find("completion_summary", snapshot["report_id"])
        if report is None:
            return set()
        scope, start, end = self._report_scope(report)
        current: set[int] = set()
        for row in store.rows("funding_use"):
            if row.get("status") != APPROVED_STATUS:
                continue
            if not self._in_scope(row, scope, start, end):
                continue
            amount = self._to_amount(row.get("实际金额"))
            if amount < 0:
                raw_origin = row.get("关联支出")
                try:
                    origin_id = int(raw_origin)
                except (TypeError, ValueError):
                    continue
                origin = store.find("funding_use", origin_id)
                if (
                    origin is None
                    or not self._in_scope(origin, scope, start, end)
                    or origin.get("status") != APPROVED_STATUS
                ):
                    continue
            current.add(int(row.get("id")))
        return current - set(snapshot.get("included_ids", []))

    def _new_rows_after(self, package: dict[str, Any]) -> list[dict[str, Any]]:
        """快照数据时点之后出现、当前已核准且属于本报告范围的行。

        每一行都带「是否进入本包所用数据」的明确结论与原因，
        用于向编制人解释迟到退款/新支出与已冻结快照的关系。
        """
        snapshot = package.get("快照") or {}
        data_as_of = snapshot.get("数据时点", "")
        new_ids = self._diff_approved_ids(snapshot)
        annotated: list[dict[str, Any]] = []
        for row in store.rows("funding_use"):
            if int(row.get("id", 0)) not in new_ids:
                continue
            amount = self._to_amount(row.get("实际金额"))
            kind = "负数退款" if amount < 0 else "核准支出"
            annotated.append({
                "id": row.get("id"),
                "支出项目": row.get("支出项目"),
                "实际金额": amount,
                "条目类型": kind,
                "是否进入本包数据": False,
                "说明": (
                    f"该{kind}在数据时点 {data_as_of} 之后才核准，"
                    f"未进入本交账包所用数据；如需纳入，请从报告再发起一份新交账包"
                ),
            })
        return annotated

    def list_packages(self) -> list[dict[str, Any]]:
        result = []
        for package in store.rows(self.MODULE):
            view = dict(package)
            new_rows = self._new_rows_after(package)
            view["有新核准行"] = bool(new_rows)
            view["新核准行"] = new_rows
            result.append(view)
        return result

    def get_package(self, entry_id: int) -> dict[str, Any] | None:
        package = store.find(self.MODULE, entry_id)
        if package is None:
            return None
        view = dict(package)
        view["新核准行"] = self._new_rows_after(package)
        view["有新核准行"] = bool(view["新核准行"])
        return view
