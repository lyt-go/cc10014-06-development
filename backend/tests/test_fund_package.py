"""费用交账包领域测试。

覆盖需求要点：
- 核准支出、负数退款、关联签证装入同一快照；未核准/超范围不得入净额；
- 退款按原支出归属抵减；500 元原款与 60 元退款逐条可辨；
- 合计与附件同一数据时点；迟到退款能否进入所用数据可解释；
- 备案重复提交只保留一次费用确认；新核准行后可再发起新包；
- 旧备案与新报告各自按自己的证据继续办理。
"""
from __future__ import annotations

import asyncio

import pytest

from app.seed import SEED_ROWS
from app.services.completion_summary import CompletionSummaryService
from app.services.fund_package import FundPackageService
from app.services.funding_use import FundingUseService
from app.store import store

REPORT_ID = 4  # 种子中的「大殿六月修缮」报告


@pytest.fixture(autouse=True)
def reset_store():
    store._idempotent_log.clear()
    store._resource_locks.clear()
    for name in list(store._tables.keys()):
        if name in SEED_ROWS:
            store._tables[name] = [dict(row) for row in SEED_ROWS[name]]
        else:
            store._tables[name] = []
    yield


fund_package_service = FundPackageService()
funding_service = FundingUseService()
completion_service = CompletionSummaryService()


def _make_refund(amount: float, origin_id: int, date: str, voucher: str) -> dict:
    entry, missing = funding_service.create_entry({
        "支出项目": f"退款{voucher}",
        "支出类别": "退款冲抵",
        "预算金额": amount,
        "实际金额": amount,
        "支出日期": date,
        "经办人": "周财务",
        "施工范围": "大殿六月修缮",
        "关联支出": str(origin_id),
        "凭证编号": voucher,
    })
    assert missing == []
    return entry


def _approve(entry_id: int) -> None:
    funding_service.run_action(entry_id, "提交报销")
    updated, msg = funding_service.run_action(entry_id, "核准支出")
    assert updated is not None, msg
    assert updated["status"] == "已核准"


def _unlock_archive_gate() -> None:
    """让既有“档案入库率”规则放行，使备案校验走到交账包规则。"""
    for row in store.rows("archive_mgmt"):
        row["status"] = "已入库"


# ═══════════════════════════════════════════════════════════════════
# 1. 生成交账包：500 原款与 60 退款逐条可辨，净额 440
# ═══════════════════════════════════════════════════════════════════

def test_package_contains_approved_expense_refund_and_visa():
    package, message = fund_package_service.create_package(REPORT_ID)
    assert package is not None, message
    snapshot = package["快照"]

    entries = snapshot["entries"]
    by_id = {e["id"]: e for e in entries}
    # 500 元原款、60 元退款逐条可辨认
    assert set(by_id) == {4, 5}
    assert by_id[4]["条目类型"] == "核准支出"
    assert by_id[4]["实际金额"] == 500.0
    assert by_id[5]["条目类型"] == "退款抵减"
    assert by_id[5]["实际金额"] == -60.0
    assert by_id[5]["归属原支出"] == 4  # 退款按原支出归属抵减

    totals = snapshot["totals"]
    assert totals["支出合计"] == 500.0
    assert totals["退款合计"] == 60.0
    assert totals["实付净额"] == 440.0

    # 关联签证随包装入
    assert [v["id"] for v in snapshot["visas"]] == [4]
    # 附件与条目/签证一一对应，同一时点冻结
    vouchers = {a["凭证编号"] for a in snapshot["attachments"]}
    assert {"PAY-500-001", "REF-60-001", "变更签证#4"} <= vouchers


def test_unapproved_and_out_of_scope_rows_excluded():
    package, _ = fund_package_service.create_package(REPORT_ID)
    excluded = {e["id"]: e["原因"] for e in package["快照"]["excluded"]}

    # 未核准费用不得进入实付净额
    assert 6 in excluded and "未核准" in excluded[6]
    # 超出报告施工范围的支出不得装入
    assert 7 in excluded and "超出报告施工范围" in excluded[7]
    # 排除项均不在净额条目内
    assert 6 not in {e["id"] for e in package["快照"]["entries"]}
    assert 7 not in {e["id"] for e in package["快照"]["entries"]}


def test_refund_must_attribute_to_origin_expense():
    # 退款未标注原支出：不得抵减
    bad, missing = funding_service.create_entry({
        "支出项目": "无归属退款", "支出类别": "退款冲抵",
        "预算金额": -20, "实际金额": -20, "支出日期": "2026-06-22",
        "施工范围": "大殿六月修缮", "凭证编号": "REF-ORPHAN",
    })
    assert missing == []
    _approve(bad["id"])

    package, _ = fund_package_service.create_package(REPORT_ID)
    excluded = {e["id"]: e["原因"] for e in package["快照"]["excluded"]}
    assert bad["id"] in excluded and "原支出" in excluded[bad["id"]]
    # 净额不受无归属退款影响
    assert package["实付净额"] == 440.0


def test_refund_following_out_of_scope_origin_is_rejected():
    # 原支出#7 属于另一施工范围，其退款不得在本报告包内抵减
    refund, missing = funding_service.create_entry({
        "支出项目": "外项退款", "支出类别": "退款冲抵",
        "预算金额": -30, "实际金额": -30, "支出日期": "2026-06-23",
        "施工范围": "大殿六月修缮", "关联支出": "7", "凭证编号": "REF-EXT",
    })
    assert missing == []
    _approve(refund["id"])

    package, _ = fund_package_service.create_package(REPORT_ID)
    excluded = {e["id"]: e["原因"] for e in package["快照"]["excluded"]}
    assert refund["id"] in excluded and "施工范围" in excluded[refund["id"]]
    assert package["实付净额"] == 440.0


# ═══════════════════════════════════════════════════════════════════
# 2. 备案待办联动与备案前置
# ═══════════════════════════════════════════════════════════════════

def test_report_todo_updates_with_package():
    package, _ = fund_package_service.create_package(REPORT_ID)
    report = store.find("completion_summary", REPORT_ID)
    assert report["交账包状态"] == "待备案"
    assert report["最新交账包"] == package["id"]
    assert "待备案" in report["费用待办"]


def test_completion_filing_requires_filed_package():
    _unlock_archive_gate()
    report = store.find("completion_summary", REPORT_ID)

    # 没有交账包：备案被阻止
    ok, reason = completion_service.cross_module_verify(REPORT_ID, "执行备案", report)
    assert ok is False and "费用交账包" in reason

    # 有包但未备案：仍被阻止
    package, _ = fund_package_service.create_package(REPORT_ID)
    ok, reason = completion_service.cross_module_verify(REPORT_ID, "执行备案", report)
    assert ok is False and "尚未备案" in reason

    # 交账包备案后放行
    filed, msg = fund_package_service.file_package(package["id"])
    assert filed is not None and filed["status"] == "已备案"
    ok, reason = completion_service.cross_module_verify(REPORT_ID, "执行备案", report)
    assert ok is True, reason


# ═══════════════════════════════════════════════════════════════════
# 3. 重复备案只保留一次费用确认
# ═══════════════════════════════════════════════════════════════════

def test_duplicate_filing_keeps_single_confirmation():
    package, _ = fund_package_service.create_package(REPORT_ID)
    first, msg1 = fund_package_service.file_package(package["id"])
    assert first is not None and first["status"] == "已备案"
    filed_at = first["备案时间"]
    net = first["实付净额"]

    second, msg2 = fund_package_service.file_package(package["id"])
    # 返回同一条费用确认，不产生新包、不改净额、不改备案时间
    assert second["id"] == package["id"]
    assert second["备案时间"] == filed_at
    assert second["实付净额"] == net
    assert "只保留一次" in msg2
    assert len(store.rows("fund_package")) == 1

    report = store.find("completion_summary", REPORT_ID)
    assert report["备案净额"] == 440.0
    assert report["备案快照时点"] == package["数据时点"]


# ═══════════════════════════════════════════════════════════════════
# 4. 迟到退款：备案可说明其是否进入所用数据；同一时点保证
# ═══════════════════════════════════════════════════════════════════

def test_late_refund_traceability_and_single_point_in_time():
    package, _ = fund_package_service.create_package(REPORT_ID)
    as_of = package["数据时点"]
    fund_package_service.file_package(package["id"])

    # 迟到退款先处于未核准：旧包侦测不到“新核准行”，快照内也不含它
    late = _make_refund(-30, 4, "2026-07-05", "REF-LATE-001")
    funding_service.run_action(late["id"], "提交报销")
    view = fund_package_service.get_package(package["id"])
    assert view["有新核准行"] is False
    frozen_ids = {e["id"] for e in package["快照"]["entries"]}
    assert late["id"] not in frozen_ids

    # 核准后：旧包明确标记新核准行，可解释该退款未进入备案所用数据
    funding_service.run_action(late["id"], "核准支出")
    view = fund_package_service.get_package(package["id"])
    assert view["有新核准行"] is True
    new_row = view["新核准行"][0]
    assert new_row["id"] == late["id"]
    assert new_row["是否进入本包数据"] is False
    assert "未进入本交账包所用数据" in new_row["说明"]
    assert "再发起一份新交账包" in new_row["说明"]

    # 旧包快照仍冻结在原数据时点，净额不变（合计与附件不会跨时点）
    old = store.find("fund_package", package["id"])
    assert old["数据时点"] == as_of
    assert old["实付净额"] == 440.0
    assert {e["id"] for e in old["快照"]["entries"]} == {4, 5}
    attachment_sources = {a["来源id"] for a in old["快照"]["attachments"]}
    assert late["id"] not in attachment_sources


def test_new_package_after_new_approval_while_old_filing_remains_reviewable():
    first, _ = fund_package_service.create_package(REPORT_ID)
    fund_package_service.file_package(first["id"])

    late = _make_refund(-30, 4, "2026-07-05", "REF-LATE-002")
    _approve(late["id"])

    # 出现新核准行后再发起一份交账包
    second, message = fund_package_service.create_package(REPORT_ID)
    assert second is not None and second["id"] != first["id"]
    assert second["快照"]["totals"]["实付净额"] == 410.0
    assert {e["id"] for e in second["快照"]["entries"]} == {4, 5, late["id"]}

    # 旧备案仍按自己的证据可复核
    old = store.find("fund_package", first["id"])
    assert old["status"] == "已备案"
    assert old["实付净额"] == 440.0
    assert [e["实际金额"] for e in old["快照"]["entries"]] == [500.0, -60.0]
    assert old["快照"]["visas"][0]["id"] == 4

    # 新报告（新包）按自己的证据继续办理：备案互不影响
    filed2, _ = fund_package_service.file_package(second["id"])
    assert filed2["status"] == "已备案"
    assert store.find("fund_package", first["id"])["status"] == "已备案"
    assert store.find("fund_package", first["id"])["实付净额"] == 440.0


def test_recreate_without_new_rows_reuses_pending_package():
    first, _ = fund_package_service.create_package(REPORT_ID)
    second, message = fund_package_service.create_package(REPORT_ID)
    assert second["id"] == first["id"]
    assert "未重复生成" in message
    assert len(store.rows("fund_package")) == 1


# ═══════════════════════════════════════════════════════════════════
# 5. 边界与下载
# ═══════════════════════════════════════════════════════════════════

def test_package_for_unknown_report_rejected():
    package, message = fund_package_service.create_package(999)
    assert package is None
    assert "不存在" in message


def test_download_csv_matches_frozen_snapshot():
    from app.routers.fund_package import download_package

    package, _ = fund_package_service.create_package(REPORT_ID)
    response = download_package(package["id"])

    async def collect() -> str:
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.encode() if isinstance(chunk, str) else chunk)
        return b"".join(chunks).decode("utf-8")

    text = asyncio.run(collect())
    # 合计、逐条明细、排除说明、附件清单同处一份文件（同一处理时点）
    assert "实付净额" in text and "440.0" in text
    assert "PAY-500-001" in text and "REF-60-001" in text
    assert "变更签证#4" in text
    assert "大殿木作待核准尾款" in text and "未核准" in text
    assert "围墙外项工程支出" in text and "超出报告施工范围" in text
    assert "数据时点" in text and package["数据时点"] in text


def test_scope_fallback_to_report_period_when_scope_blank():
    # 支出未填施工范围时，按报告工期（2026-06-01 ~ 2026-06-30）判定
    in_period, missing = funding_service.create_entry({
        "支出项目": "工期内支出", "支出类别": "工程支出",
        "预算金额": 80, "实际金额": 80, "支出日期": "2026-06-15",
        "凭证编号": "PAY-DATE-IN",
    })
    assert missing == []
    _approve(in_period["id"])
    out_period, _ = funding_service.create_entry({
        "支出项目": "工期外支出", "支出类别": "工程支出",
        "预算金额": 90, "实际金额": 90, "支出日期": "2026-08-15",
        "凭证编号": "PAY-DATE-OUT",
    })
    _approve(out_period["id"])

    package, _ = fund_package_service.create_package(REPORT_ID)
    ids_in = {e["id"] for e in package["快照"]["entries"]}
    ids_out = {e["id"] for e in package["快照"]["excluded"]}
    assert in_period["id"] in ids_in
    assert out_period["id"] in ids_out


def test_direct_generic_create_is_blocked():
    # 通用登记入口不能绕过快照直接造交账包
    entry, missing = fund_package_service.create_entry({"交账包编号": "FPK-FORGE"})
    assert entry is None
    assert missing and "竣工报告" in missing[0]
    assert store.rows("fund_package") == []


def test_generic_action_routes_to_idempotent_filing():
    package, _ = fund_package_service.create_package(REPORT_ID)
    # 通过通用动作入口提交备案
    entry, message = fund_package_service.run_action(package["id"], "提交备案")
    assert entry is not None and entry["status"] == "已备案"
    # 再次提交仍是同一条费用确认
    again, again_msg = fund_package_service.run_action(package["id"], "提交备案")
    assert again["id"] == package["id"] and "只保留一次" in again_msg
    # 不支持的动作被拒绝
    bad, bad_msg = fund_package_service.run_action(package["id"], "不存在的动作")
    assert bad is None and "可执行范围" in bad_msg
