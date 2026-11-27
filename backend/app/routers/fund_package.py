"""费用交账包路由：围绕竣工报告生成、下载、备案费用交账包。

与通用资源路由分开注册并优先挂载，避免被 /api/{module} 动态路径抢先匹配。
"""
from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.schemas import ActionResult
from app.services.fund_package import FundPackageService

router = APIRouter(prefix="/api/fund-packages", tags=["费用交账包"])
fund_package_service = FundPackageService()


def _csv_line_guard(values: list[Any]) -> list[Any]:
    return [
        "'" + str(value) if str(value or "").startswith(("=", "+", "-", "@")) else value
        for value in values
    ]


@router.get("", response_model=dict)
def list_packages() -> dict[str, Any]:
    """列出全部费用交账包，并标记每个包之后是否出现新核准行。"""
    items = fund_package_service.list_packages()
    return {"items": items, "total": len(items), "page": 1, "size": len(items) or 1}


@router.post("/reports/{report_id}", response_model=ActionResult)
def create_package(report_id: int) -> ActionResult:
    """从指定竣工报告下载（生成）一份费用交账包，快照在同一数据时点冻结。"""
    package, message = fund_package_service.create_package(report_id)
    return ActionResult(ok=package is not None, message=message, entry=package)


@router.get("/reports/{report_id}/new-approved")
def new_approved_for_report(report_id: int) -> dict[str, Any]:
    """查看报告最新交账包之后出现的新核准行（含迟到退款）。"""
    packages = [
        p for p in fund_package_service.list_packages()
        if p.get("关联报告") == report_id
    ]
    if not packages:
        raise HTTPException(status_code=404, detail=f"竣工报告 {report_id} 还没有费用交账包")
    latest = max(packages, key=lambda p: int(p.get("id", 0)))
    return {
        "report_id": report_id,
        "package_id": latest.get("id"),
        "数据时点": latest.get("数据时点"),
        "有新核准行": latest.get("有新核准行", False),
        "新核准行": latest.get("新核准行", []),
    }


@router.get("/{package_id}", response_model=dict)
def get_package(package_id: int) -> dict[str, Any]:
    package = fund_package_service.get_package(package_id)
    if package is None:
        raise HTTPException(status_code=404, detail=f"费用交账包 {package_id} 不存在")
    return package


@router.get("/{package_id}/file")
def download_package(package_id: int) -> StreamingResponse:
    """下载交账包 CSV：条目、排除项、签证、附件清单均来自同一快照。"""
    package = fund_package_service.get_package(package_id)
    if package is None:
        raise HTTPException(status_code=404, detail=f"费用交账包 {package_id} 不存在")
    snapshot = package["快照"]
    totals = snapshot["totals"]

    output = io.StringIO()
    output.write("﻿")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["费用交账包", package.get("交账包编号")])
    writer.writerow(["关联竣工报告", f"{snapshot['report_id']}（{snapshot['报告名称']}）"])
    writer.writerow(["施工范围", snapshot["施工范围"]])
    writer.writerow(["数据时点", snapshot["数据时点"]])
    writer.writerow(["生成时间", package.get("生成时间")])
    writer.writerow(["包状态", package.get("status")])
    writer.writerow([])

    writer.writerow(["合计口径（与下方明细同一快照时点）"])
    writer.writerow(["支出合计", totals["支出合计"]])
    writer.writerow(["退款合计", totals["退款合计"]])
    writer.writerow(["实付净额", totals["实付净额"]])
    writer.writerow(["条目数", totals["条目数"]])
    writer.writerow(["签证数", totals["签证数"]])
    writer.writerow(["附件数", totals["附件数"]])
    writer.writerow([])

    writer.writerow(["包内条目（逐条可辨：原款与退款各自成行）"])
    writer.writerow([
        "条目类型", "支出id", "支出项目", "支出类别", "实际金额", "支出日期",
        "经办人", "凭证编号", "归属原支出", "入包说明", "审批状态",
    ])
    for entry in snapshot["entries"]:
        writer.writerow(_csv_line_guard([
            entry.get("条目类型"), entry.get("id"), entry.get("支出项目"),
            entry.get("支出类别"), entry.get("实际金额"), entry.get("支出日期"),
            entry.get("经办人"), entry.get("凭证编号"), entry.get("归属原支出"),
            entry.get("入包说明"), entry.get("status"),
        ]))
    writer.writerow([])

    writer.writerow(["未装入项及原因（未核准/超范围/无法归属）"])
    writer.writerow(["支出id", "支出项目", "实际金额", "审批状态", "原因"])
    for item in snapshot["excluded"]:
        writer.writerow(_csv_line_guard([
            item.get("id"), item.get("支出项目"), item.get("实际金额"),
            item.get("status"), item.get("原因"),
        ]))
    writer.writerow([])

    writer.writerow(["关联签证凭据"])
    writer.writerow(["签证id", "变更事项", "影响工序", "费用增减", "签认日期", "状态"])
    for visa in snapshot["visas"]:
        writer.writerow(_csv_line_guard([
            visa.get("id"), visa.get("变更事项"), visa.get("影响工序"),
            visa.get("费用增减"), visa.get("签认日期"), visa.get("status"),
        ]))
    for item in snapshot["pending_visas"]:
        writer.writerow(_csv_line_guard([
            item.get("id"), "", "", "", "", item.get("原因"),
        ]))
    writer.writerow([])

    writer.writerow(["附件清单（与合计同一时点生成）"])
    writer.writerow(["凭证编号", "来源类型", "来源id", "来源名称"])
    for att in snapshot["attachments"]:
        writer.writerow(_csv_line_guard([
            att.get("凭证编号"), att.get("来源类型"),
            att.get("来源id"), att.get("来源名称"),
        ]))

    filename = f"{package.get('交账包编号', f'fund-package-{package_id}')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{package_id}/file", response_model=ActionResult)
def file_package(package_id: int, remark: str | None = Query(default=None)) -> ActionResult:
    """提交备案；同一交账包重复提交只保留一次费用确认。"""
    package, message = fund_package_service.file_package(package_id, remark)
    return ActionResult(ok=package is not None, message=message, entry=package)
