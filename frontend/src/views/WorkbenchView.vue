<template>
  <section class="page" :data-module="meta.key">
    <header class="page-head">
      <div>
        <h2>{{ meta.name }}</h2>
        <p class="page-desc">{{ meta.desc }}</p>
      </div>
      <div class="page-actions">
        <button
          v-if="!isFundPackage"
          class="btn primary"
          data-testid="open-create"
          type="button"
          @click="openCreate"
        >
          登记{{ meta.entity }}
        </button>
        <button
          v-if="isFundPackage"
          class="btn primary"
          data-testid="open-package-create"
          type="button"
          @click="showPackageCreate = true"
        >
          从竣工报告生成交账包
        </button>
        <button
          v-if="!isFundPackage"
          class="btn"
          data-testid="export"
          type="button"
          @click="exportRows"
        >
          导出{{ meta.name }}清单
        </button>
      </div>
    </header>

    <div v-if="isFundPackage" class="package-tip" data-testid="package-tip">
      交账包在生成时冻结同一数据时点：合计、逐条凭据与附件清单不会随后续核准变动；
      出现新核准行后可从同一报告再发起新包，旧备案仍按原快照复核。
    </div>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <p class="status-legend">
      <span v-for="item in statusSummary" :key="item.status" class="legend-item">
        {{ item.status }}：{{ item.count }}
      </span>
    </p>

    <form v-if="!isFundPackage" class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :data-testid="`filter-${field}`" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in meta.fields" :key="column">{{ column }}</th>
          <th>当前状态</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in rows"
          :key="String(row.id)"
          :data-testid="`row-${row.id}`"
          :data-status="String(row.status)"
        >
          <td v-for="column in meta.fields" :key="column">{{ row[column] ?? '—' }}</td>
          <td>
            {{ row.status }}
            <span
              v-if="isFundPackage && (row as FundPackageRow).有新核准行"
              class="badge warn"
              data-testid="new-approved-badge"
            >
              有新核准行
            </span>
          </td>
          <td class="row-actions">
            <template v-if="isFundPackage">
              <button
                class="link"
                type="button"
                :data-testid="`action-${row.id}-查看凭据`"
                @click="openPackageDetail(Number(row.id))"
              >
                查看凭据
              </button>
              <button
                class="link"
                type="button"
                :data-testid="`action-${row.id}-下载交账包`"
                @click="downloadPackage(Number(row.id), String((row as FundPackageRow).交账包编号))"
              >
                下载交账包
              </button>
              <button
                v-if="row.status === '待备案'"
                class="link"
                type="button"
                :data-testid="`action-${row.id}-提交备案`"
                @click="filePackage(Number(row.id))"
              >
                提交备案
              </button>
              <span v-else class="filed-note">费用确认已保留一次</span>
            </template>
            <template v-else-if="isCompletionSummary">
              <button
                v-for="action in meta.actions"
                :key="action"
                class="link"
                type="button"
                :data-testid="`action-${row.id}-${action}`"
                @click="runAction(action, row)"
              >
                {{ action }}
              </button>
              <button
                class="link"
                type="button"
                :data-testid="`action-${row.id}-生成费用交账包`"
                @click="createPackageForReport(Number(row.id))"
              >
                生成费用交账包
              </button>
            </template>
            <button
              v-else
              v-for="action in meta.actions"
              :key="action"
              class="link"
              type="button"
              :data-testid="`action-${row.id}-${action}`"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="meta.fields.length + 2" class="empty-state">
            暂无{{ meta.name }}数据，可先登记{{ meta.entity }}
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记{{ meta.entity }}</h3>
        <label v-for="field in meta.fields" :key="field" class="create-field">
          <span>{{ field }}</span>
          <input v-model="createValues[field]" :data-testid="`create-${field}`" required />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" data-testid="submit-create" type="submit" :disabled="creating">
            {{ creating ? '提交中…' : '确认登记' }}
          </button>
        </div>
      </form>
    </div>

    <div v-if="isFundPackage && showPackageCreate" class="modal-backdrop" data-testid="package-create-modal">
      <form class="modal" @submit.prevent="submitPackageCreate">
        <h3>从竣工报告生成费用交账包</h3>
        <p class="modal-hint">
          输入竣工报告 id，系统将冻结该报告施工范围内的核准支出、负数退款和关联签证；
          未核准与超范围支出只在包内留痕，不进实付净额。
        </p>
        <label class="create-field">
          <span>竣工报告 id</span>
          <input v-model="packageReportId" data-testid="package-report-id" required type="number" min="1" />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showPackageCreate = false">取消</button>
          <button class="btn primary" data-testid="submit-package-create" type="submit" :disabled="creating">
            {{ creating ? '生成中…' : '生成交账包' }}
          </button>
        </div>
      </form>
    </div>

    <div v-if="isFundPackage && packageDetail" class="modal-backdrop" data-testid="package-detail-modal">
      <div class="modal wide">
        <h3>交账包 {{ packageDetail.交账包编号 }} 凭据明细</h3>
        <p class="modal-hint">
          数据时点：{{ packageDetail.数据时点 }} ｜ 状态：{{ packageDetail.status }}
          ｜ 实付净额：{{ packageDetail.实付净额 }} 元
          <span v-if="packageDetail.有新核准行" class="badge warn">该时点后出现新核准行，可再发起新包</span>
        </p>

        <h4>包内条目（原款与退款逐条可辨）</h4>
        <table class="detail-table">
          <thead>
            <tr><th>类型</th><th>支出id</th><th>支出项目</th><th>实际金额</th><th>归属原支出</th><th>凭证编号</th><th>说明</th></tr>
          </thead>
          <tbody>
            <tr v-for="entry in packageDetail.快照?.entries ?? []" :key="String(entry.id)">
              <td>{{ entry.条目类型 }}</td>
              <td>{{ entry.id }}</td>
              <td>{{ entry.支出项目 }}</td>
              <td :class="{ refund: Number(entry.实际金额) < 0 }">{{ entry.实际金额 }}</td>
              <td>{{ entry.归属原支出 ?? '—' }}</td>
              <td>{{ entry.凭证编号 || '—' }}</td>
              <td>{{ entry.入包说明 }}</td>
            </tr>
          </tbody>
        </table>

        <h4>未装入项及原因</h4>
        <table class="detail-table">
          <thead>
            <tr><th>支出id</th><th>支出项目</th><th>实际金额</th><th>原因</th></tr>
          </thead>
          <tbody>
            <tr v-for="item in packageDetail.快照?.excluded ?? []" :key="`ex-${String(item.id)}`">
              <td>{{ item.id }}</td>
              <td>{{ item.支出项目 }}</td>
              <td>{{ item.实际金额 }}</td>
              <td>{{ item.原因 }}</td>
            </tr>
          </tbody>
        </table>

        <h4>关联签证凭据</h4>
        <table class="detail-table">
          <thead>
            <tr><th>签证id</th><th>变更事项</th><th>影响工序</th><th>费用增减</th><th>签认日期</th></tr>
          </thead>
          <tbody>
            <tr v-for="visa in packageDetail.快照?.visas ?? []" :key="`v-${String(visa.id)}`">
              <td>{{ visa.id }}</td>
              <td>{{ visa.变更事项 }}</td>
              <td>{{ visa.影响工序 }}</td>
              <td>{{ visa.费用增减 }}</td>
              <td>{{ visa.签认日期 }}</td>
            </tr>
          </tbody>
        </table>

        <h4>数据时点之后的新核准行（未进入本包数据）</h4>
        <table class="detail-table">
          <thead>
            <tr><th>支出id</th><th>支出项目</th><th>类型</th><th>实际金额</th><th>是否进入本包</th><th>说明</th></tr>
          </thead>
          <tbody>
            <tr v-for="item in packageDetail.新核准行" :key="`new-${String(item.id)}`">
              <td>{{ item.id }}</td>
              <td>{{ item.支出项目 }}</td>
              <td>{{ item.条目类型 ?? '—' }}</td>
              <td :class="{ refund: Number(item.实际金额) < 0 }">{{ item.实际金额 }}</td>
              <td>{{ item.是否进入本包数据 === false ? '否' : '—' }}</td>
              <td>{{ item.说明 ?? '—' }}</td>
            </tr>
            <tr v-if="!packageDetail.新核准行.length">
              <td colspan="6">数据时点之后暂无新核准行，包内合计即为当前所用数据。</td>
            </tr>
          </tbody>
        </table>

        <h4>附件清单（与合计同一时点）</h4>
        <ul class="attachment-list">
          <li v-for="att in packageDetail.快照?.attachments ?? []" :key="`a-${String(att.来源类型)}-${String(att.来源id)}`">
            {{ att.凭证编号 }}（{{ att.来源类型 }}：{{ att.来源名称 }}）
          </li>
        </ul>

        <div class="page-actions">
          <button class="btn" type="button" @click="packageDetail = null">关闭</button>
          <button
            class="btn primary"
            type="button"
            data-testid="detail-download"
            @click="downloadPackage(Number(packageDetail.id), packageDetail.交账包编号)"
          >
            下载交账包 CSV
          </button>
        </div>
      </div>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条{{ meta.name }}记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  createEntry,
  createFundPackage,
  downloadEntries,
  downloadFundPackage,
  fetchFundPackage,
  fileFundPackage,
  listEntries,
  listFundPackages,
  moduleMeta,
  runAction as applyAction,
  type FundPackageRow,
} from '@/api/backend-service'
import type { EntryRow } from '@/data/types'

const props = defineProps<{ moduleKey: string }>()
const meta = moduleMeta(props.moduleKey)
const isFundPackage = props.moduleKey === 'fund_package'
const isCompletionSummary = props.moduleKey === 'completion_summary'
const rows = ref<EntryRow[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = meta.fields.slice(0, 3)
const showCreate = ref(false)
const creating = ref(false)
const createValues = ref<Record<string, string>>({})
const showPackageCreate = ref(false)
const packageReportId = ref('')
const packageDetail = ref<FundPackageRow | null>(null)

const stats = computed(() => {
  if (isFundPackage) {
    return [
      { label: meta.metrics[0], value: total.value },
      { label: meta.metrics[1], value: rows.value.filter((r) => r.status === '待备案').length },
      { label: meta.metrics[2], value: rows.value.filter((r) => r.status === '已备案').length },
    ]
  }
  return [
    { label: meta.metrics[0], value: total.value },
    { label: meta.metrics[1], value: rows.value.filter((r) => r.status === meta.statuses[1]).length },
    { label: meta.metrics[2], value: rows.value.filter((r) => r.status === meta.statuses[meta.statuses.length - 1]).length },
  ]
})

const statusSummary = computed(() =>
  meta.statuses.map((s) => ({ status: s, count: rows.value.filter((r) => String(r.status) === s).length })),
)

function resetFilters() { filters.value = {}; void reload() }

async function exportRows() {
  errorMessage.value = ''
  try { await downloadEntries(meta.key, filters.value) }
  catch (e) { errorMessage.value = e instanceof Error ? e.message : '导出失败' }
}

function openCreate() {
  createValues.value = Object.fromEntries(meta.fields.map((f) => [f, '']))
  errorMessage.value = ''
  showCreate.value = true
}

async function submitCreate() {
  creating.value = true; errorMessage.value = ''
  try {
    const r = await createEntry(meta.key, createValues.value)
    if (!r.ok) throw new Error(r.message)
    showCreate.value = false; await reload()
  } catch (e) { errorMessage.value = e instanceof Error ? e.message : '登记失败' }
  finally { creating.value = false }
}

async function runAction(action: string, row: EntryRow) {
  errorMessage.value = ''
  try {
    const r = await applyAction(meta.key, Number(row.id), action)
    if (!r.ok) throw new Error(r.message)
    await reload()
  } catch (e) { errorMessage.value = e instanceof Error ? e.message : '操作失败' }
}

// ── 费用交账包专用流程 ──
async function submitPackageCreate() {
  creating.value = true; errorMessage.value = ''
  try {
    const reportId = Number(packageReportId.value)
    if (!Number.isInteger(reportId) || reportId <= 0) throw new Error('请输入有效的竣工报告 id')
    const r = await createFundPackage(reportId)
    if (!r.ok) throw new Error(r.message)
    showPackageCreate.value = false
    packageReportId.value = ''
    await reload()
  } catch (e) { errorMessage.value = e instanceof Error ? e.message : '交账包生成失败' }
  finally { creating.value = false }
}

async function createPackageForReport(reportId: number) {
  errorMessage.value = ''
  try {
    const r = await createFundPackage(reportId)
    if (!r.ok) throw new Error(r.message)
    await reload()
  } catch (e) { errorMessage.value = e instanceof Error ? e.message : '交账包生成失败' }
}

async function openPackageDetail(packageId: number) {
  errorMessage.value = ''
  try { packageDetail.value = await fetchFundPackage(packageId) }
  catch (e) { errorMessage.value = e instanceof Error ? e.message : '凭据读取失败' }
}

async function downloadPackage(packageId: number, fileName: string) {
  errorMessage.value = ''
  try { await downloadFundPackage(packageId, `${fileName}.csv`) }
  catch (e) { errorMessage.value = e instanceof Error ? e.message : '交账包下载失败' }
}

async function filePackage(packageId: number) {
  errorMessage.value = ''
  try {
    const r = await fileFundPackage(packageId)
    if (!r.ok) throw new Error(r.message)
    packageDetail.value = null
    await reload()
  } catch (e) { errorMessage.value = e instanceof Error ? e.message : '备案失败' }
}

async function reload() {
  errorMessage.value = ''
  try {
    if (isFundPackage) {
      const payload = await listFundPackages()
      rows.value = payload.items; total.value = payload.total
      return
    }
    const payload = await listEntries(meta.key, filters.value)
    rows.value = payload.items; total.value = payload.total
  } catch (e) { errorMessage.value = e instanceof Error ? e.message : '业务列表读取失败' }
}

onMounted(reload)
</script>

<style scoped>
.modal-backdrop { position:fixed; inset:0; background:rgba(0,0,0,.35); display:flex; align-items:center; justify-content:center; z-index:100; }
.modal { background:#fff; border-radius:8px; padding:24px; width:480px; max-height:80vh; overflow-y:auto; }
.modal.wide { width:880px; }
.create-field { display:flex; flex-direction:column; gap:4px; margin-bottom:12px; }
.create-field span { font-size:13px; color:var(--text-secondary,#4a5568); }
.create-field input { padding:6px 8px; border:1px solid var(--border-color,#e2e8f0); border-radius:4px; font-size:13px; }
.package-tip { margin:12px 0; padding:10px 14px; background:#f0f7ff; border:1px solid #bee3f8; border-radius:6px; color:#2c5282; font-size:13px; }
.modal-hint { font-size:13px; color:var(--text-secondary,#4a5568); line-height:1.6; }
.badge { display:inline-block; margin-left:6px; padding:1px 8px; border-radius:10px; font-size:12px; }
.badge.warn { background:#fff3cd; color:#975a16; border:1px solid #f6e05e; }
.filed-note { font-size:12px; color:var(--text-secondary,#718096); }
.detail-table { width:100%; border-collapse:collapse; margin-bottom:16px; font-size:12px; }
.detail-table th, .detail-table td { border:1px solid var(--border-color,#e2e8f0); padding:6px 8px; text-align:left; }
.detail-table .refund { color:#c53030; font-weight:600; }
.attachment-list { margin:0 0 16px; padding-left:20px; font-size:13px; line-height:1.8; }
</style>