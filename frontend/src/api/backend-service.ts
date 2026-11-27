import { request } from './client'
import { moduleMeta } from '@/data/modules'
import type { ActionResult, EntryRow, OverviewResult, PageResult } from '@/data/types'

export { moduleMeta }

export async function listEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<PageResult> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}?${query}`)
  if (!response.ok) throw new Error('业务数据读取失败')
  return await response.json()
}

export async function createEntry(
  key: string,
  values: Record<string, string>,
): Promise<ActionResult> {
  const response = await request(`/api/${key}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}

export async function runAction(
  key: string,
  id: number,
  action: string,
): Promise<ActionResult> {
  const response = await request(`/api/${key}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
  return await response.json()
}

export async function downloadEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}/export?${query}`)
  if (!response.ok) throw new Error('业务数据导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${key}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function loadOverview(): Promise<OverviewResult> {
  const response = await request('/api/overview')
  if (!response.ok) throw new Error('运营概览读取失败')
  return await response.json()
}

export type DependentStatus = {
  module: string
  entry_id: number
  entry: Record<string, unknown>
  upstream: { module: string; id: number; name: string; status: string }[]
  downstream: { module: string; id: number; name: string; status: string }[]
}

export async function fetchDependentStatus(
  moduleKey: string,
  entryId: number,
): Promise<DependentStatus> {
  const response = await request(`/api/cross-module/dependent-status/${moduleKey}/${entryId}`)
  if (!response.ok) throw new Error('跨模块状态查询失败')
  return await response.json()
}

export async function fetchDependencyGraph(): Promise<{ nodes: unknown[]; edges: unknown[] }> {
  const response = await request('/api/cross-module/dependency-graph')
  if (!response.ok) throw new Error('依赖图加载失败')
  return await response.json()
}

// ── 费用交账包：从竣工报告生成、下载、备案 ──

export type FundPackageRow = EntryRow & {
  交账包编号: string
  关联报告: number
  报告名称: string
  编制人: string
  生成时间: string
  数据时点: string
  支出合计: number
  退款合计: number
  实付净额: number
  条目数: number
  附件数: number
  备案时间: string | null
  备案说明: string
  有新核准行: boolean
  新核准行: {
    id: number
    支出项目: string
    实际金额: number
    条目类型?: string
    是否进入本包数据?: boolean
    说明?: string
  }[]
  快照?: {
    entries: Record<string, unknown>[]
    excluded: Record<string, unknown>[]
    visas: Record<string, unknown>[]
    attachments: Record<string, unknown>[]
    totals: Record<string, number>
  }
}

export async function listFundPackages(): Promise<{ items: FundPackageRow[]; total: number }> {
  const response = await request('/api/fund-packages')
  if (!response.ok) throw new Error('费用交账包读取失败')
  return await response.json()
}

export async function createFundPackage(
  reportId: number,
): Promise<ActionResult & { entry: FundPackageRow | null }> {
  const response = await request(`/api/fund-packages/reports/${reportId}`, { method: 'POST' })
  return await response.json()
}

export async function fetchFundPackage(packageId: number): Promise<FundPackageRow> {
  const response = await request(`/api/fund-packages/${packageId}`)
  if (!response.ok) throw new Error('费用交账包读取失败')
  return await response.json()
}

export async function fileFundPackage(packageId: number): Promise<ActionResult> {
  const response = await request(`/api/fund-packages/${packageId}/file`, { method: 'POST' })
  return await response.json()
}

export async function downloadFundPackage(packageId: number, fileName: string): Promise<void> {
  const response = await request(`/api/fund-packages/${packageId}/file`)
  if (!response.ok) throw new Error('费用交账包下载失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fileName
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}
