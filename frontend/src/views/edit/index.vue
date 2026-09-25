<template>
  <section class="page" data-module="edit">
    <header class="page-head">
      <div>
        <h2>剪辑版本流转台</h2>
        <p class="page-desc">粗剪、精剪、交付与修改轮次按生命周期推进，每次状态变更记录操作人与时间；退回修改后列表、流程台与导出同步切换。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记剪辑任务</button>
        <button class="btn" type="button" @click="exportRows">导出剪辑流转清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card" :class="{ warn: item.warn }">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <div class="view-tabs">
      <button class="tab" :class="{ active: view === 'list' }" type="button" @click="view = 'list'">版本列表</button>
      <button class="tab" :class="{ active: view === 'board' }" type="button" @click="view = 'board'">流程台</button>
    </div>

    <!-- ============ 版本列表 ============ -->
    <template v-if="view === 'list'">
      <form class="filter-bar" @submit.prevent="reload">
        <label class="filter-item">
          <span>任务编号</span>
          <input v-model="filters.keyword" placeholder="按任务编号检索" />
        </label>
        <label class="filter-item">
          <span>生命周期状态</span>
          <select v-model="filters.status">
            <option value="">全部状态</option>
            <option v-for="status in statusOrder" :key="status" :value="status">{{ status }}</option>
            <option value="修改中">修改中（退回轮次）</option>
            <option value="已交付">已交付</option>
          </select>
        </label>
        <label class="filter-item">
          <span>修改轮次</span>
          <input v-model="filters.round" type="number" min="0" placeholder="如 1" style="width: 90px" />
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
      </form>

      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in columns" :key="column">{{ column }}</th>
            <th>生命周期操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="String(row.id)" :class="{ revision: row.status === '修改中' }">
            <td>{{ row['任务编号'] ?? '—' }}</td>
            <td>{{ row['所属集数'] ?? '—' }}</td>
            <td>{{ row['剪辑师'] ?? '—' }}</td>
            <td>{{ row['粗剪版本'] || '—' }}</td>
            <td>{{ row['精剪版本'] || '—' }}</td>
            <td>{{ row['交付版本'] || '—' }}</td>
            <td>{{ row['交付日期'] || '—' }}</td>
            <td>{{ roundText(row['修改轮次']) }}</td>
            <td>
              <span class="status-tag" :class="statusClass(row.status)">{{ row.status }}</span>
              <span v-if="row.read_error" class="error-badge">读取失败</span>
            </td>
            <td class="row-actions">
              <button
                v-for="action in availableActions(row)"
                :key="action.name"
                class="link"
                :class="{ danger: action.tone === 'danger' }"
                type="button"
                @click="openAction(action.name, row)"
              >
                {{ action.name }}
              </button>
              <button class="link" type="button" @click="markReadError(row)" v-if="!row.read_error && canHaveVersion(row)">
                标记读取失败
              </button>
              <button class="link" type="button" @click="recoverVersion(row)" v-if="canRecover(row)">
                恢复上一版
              </button>
              <button class="link" type="button" @click="openHistory(row)">流转记录</button>
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td :colspan="columns.length + 1" class="empty-state">暂无符合条件的剪辑任务，可先登记一条</td>
          </tr>
        </tbody>
      </table>

      <footer class="page-foot">
        <span>共 {{ total }} 条剪辑任务</span>
        <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      </footer>
    </template>

    <!-- ============ 流程台 ============ -->
    <template v-else>
      <div v-if="errorMessage" class="error-text board-error">{{ errorMessage }}</div>
      <div class="board">
        <section v-for="group in boardGroups" :key="group.status" class="board-col" :class="{ revision: group.status === '修改中' }">
          <header class="board-col-head">
            <strong>{{ group.status }}</strong>
            <span class="board-count">{{ group.count }}</span>
          </header>
          <article v-for="row in group.tasks" :key="String(row.id)" class="task-card">
            <div class="task-title">
              {{ row['任务编号'] }}
              <span v-if="row.read_error" class="error-badge">读取失败</span>
            </div>
            <div class="task-meta">{{ row['所属集数'] }} · {{ row['剪辑师'] }}</div>
            <div class="task-versions">
              <span>粗剪：{{ row['粗剪版本'] || '—' }}</span>
              <span>精剪：{{ row['精剪版本'] || '—' }}</span>
              <span>交付：{{ row['交付版本'] || '—' }}</span>
            </div>
            <div class="task-foot">
              <span class="round-chip" v-if="row['修改轮次']">第 {{ row['修改轮次'] }} 轮修改</span>
              <span class="task-date" v-if="row['交付日期']">交付日 {{ row['交付日期'] }}</span>
            </div>
            <div class="task-actions">
              <button
                v-for="action in availableActions(row)"
                :key="action.name"
                class="btn mini"
                :class="{ danger: action.tone === 'danger' }"
                type="button"
                @click="openAction(action.name, row)"
              >
                {{ action.name }}
              </button>
              <button class="btn mini" type="button" @click="markReadError(row)" v-if="!row.read_error && canHaveVersion(row)">
                标记读取失败
              </button>
              <button class="btn mini" type="button" @click="recoverVersion(row)" v-if="canRecover(row)">
                恢复上一版
              </button>
              <button class="btn mini ghost" type="button" @click="openHistory(row)">流转记录</button>
            </div>
          </article>
          <div v-if="!group.tasks.length" class="board-empty">暂无任务</div>
        </section>
      </div>
    </template>

    <!-- ============ 动作弹窗（版本号 / 交付日期 / 退回原因） ============ -->
    <div v-if="dialog.open" class="modal-mask" @click.self="dialog.open = false">
      <div class="modal">
        <h3>{{ dialog.title }}</h3>
        <p class="modal-sub">{{ dialog.sub }}</p>
        <label class="form-item" v-if="dialog.needVersion">
          <span>版本号（留空自动编号）</span>
          <input v-model="dialog.version" :placeholder="dialog.versionPlaceholder" />
        </label>
        <label class="form-item" v-if="dialog.needDate">
          <span>交付日期</span>
          <input v-model="dialog.deliveryDate" type="date" />
        </label>
        <label class="form-item" v-if="dialog.needRemark">
          <span>退回原因</span>
          <textarea v-model="dialog.remark" rows="3" placeholder="说明本次退回修改的问题"></textarea>
        </label>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="dialog.open = false">取消</button>
          <button class="btn primary" type="button" :disabled="dialog.busy" @click="confirmAction">
            {{ dialog.busy ? '提交中…' : '确认' }}
          </button>
        </div>
      </div>
    </div>

    <!-- ============ 登记任务弹窗 ============ -->
    <div v-if="createDialog.open" class="modal-mask" @click.self="createDialog.open = false">
      <div class="modal">
        <h3>登记剪辑任务</h3>
        <label v-for="field in createFields" :key="field" class="form-item">
          <span>{{ field }}</span>
          <input v-model="createDialog.form[field]" :placeholder="`请输入${field}`" />
        </label>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="createDialog.open = false">取消</button>
          <button class="btn primary" type="button" :disabled="createDialog.busy" @click="submitCreate">
            {{ createDialog.busy ? '提交中…' : '登记' }}
          </button>
        </div>
      </div>
    </div>

    <!-- ============ 生命周期流转记录 ============ -->
    <div v-if="historyEntry" class="modal-mask" @click.self="historyEntry = null">
      <div class="modal wide">
        <h3>流转记录 · {{ historyEntry['任务编号'] }}</h3>
        <ol class="lifecycle">
          <li v-for="(item, index) in historyEntry.lifecycle" :key="index" class="lifecycle-item">
            <div class="lifecycle-head">
              <strong>{{ item.action }}</strong>
              <span class="lifecycle-route">{{ item.from || '—' }} → {{ item.to }}</span>
              <span v-if="item.round" class="round-chip">第 {{ item.round }} 轮</span>
            </div>
            <div class="lifecycle-meta">
              操作人：{{ item.operator }} · {{ item.time }}
              <span v-if="item['交付日期']"> · 交付日期 {{ item['交付日期'] }}</span>
            </div>
            <div class="lifecycle-note" v-if="item.note">{{ item.note }}</div>
          </li>
        </ol>
        <h4 class="snapshot-title">版本快照</h4>
        <ul class="snapshots">
          <li v-for="(snap, index) in historyEntry.versions" :key="index">
            {{ snap.stage }} · {{ snap.version }}
            <span v-if="snap.round">（第 {{ snap.round }} 轮）</span>
            —— {{ snap.operator }} · {{ snap.time }}
          </li>
          <li v-if="!historyEntry.versions || !historyEntry.versions.length" class="board-empty">暂无版本快照</li>
        </ul>
        <div class="modal-actions">
          <button class="btn primary" type="button" @click="historyEntry = null">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

interface VersionSnapshot {
  stage: string
  version: string
  round: number
  operator: string
  time: string
}

interface LifecycleRecord {
  from: string
  to: string
  action: string
  operator: string
  time: string
  交付日期?: string
  round: number
  note?: string
}

interface EditRow {
  id: number
  status: string
  pending: boolean
  abnormal: boolean
  read_error: boolean
  修改轮次: number
  交付日期?: string
  粗剪版本?: string
  精剪版本?: string
  交付版本?: string
  [key: string]: string | number | boolean | LifecycleRecord[] | VersionSnapshot[] | undefined
  lifecycle: LifecycleRecord[]
  versions: VersionSnapshot[]
}

interface BoardGroup {
  status: string
  count: number
  tasks: EditRow[]
}

const session = useSessionStore()
const ENDPOINT = '/api/edit'
const columns = ['任务编号', '所属集数', '剪辑师', '粗剪版本', '精剪版本', '交付版本', '交付日期', '修改轮次', '剪辑状态']
const statusOrder = ['待粗剪', '粗剪中', '待精剪', '精剪中', '待交付']

const rows = ref<EditRow[]>([])
const boardGroups = ref<BoardGroup[]>([])
const total = ref(0)
const errorMessage = ref('')
const view = ref<'list' | 'board'>('list')
const filters = reactive({ keyword: '', status: '', round: '' })

// 每个生命周期节点上允许执行的动作，与后端状态机保持一致；后端仍会做最终校验。
const ACTIONS_BY_STATUS: Record<string, { name: string; tone?: 'danger' }[]> = {
  待粗剪: [{ name: '开始粗剪' }],
  粗剪中: [{ name: '提交粗剪' }],
  待精剪: [{ name: '开始精剪' }],
  精剪中: [{ name: '提交精剪' }],
  待交付: [{ name: '确认交付' }, { name: '退回修改', tone: 'danger' }],
  已交付: [{ name: '退回修改', tone: 'danger' }],
  修改中: [{ name: '重新提交' }],
}

const dialog = reactive({
  open: false,
  busy: false,
  action: '',
  title: '',
  sub: '',
  row: null as EditRow | null,
  version: '',
  deliveryDate: new Date().toISOString().slice(0, 10),
  remark: '',
  needVersion: false,
  needDate: false,
  needRemark: false,
  versionPlaceholder: '',
})

const createFields = ['任务编号', '所属集数', '剪辑师']
const createDialog = reactive({
  open: false,
  busy: false,
  form: {} as Record<string, string>,
})

const historyEntry = ref<EditRow | null>(null)

const stats = computed(() => {
  const countOf = (status: string) => boardGroups.value.find((g) => g.status === status)?.count ?? 0
  return [
    { label: '粗剪环节', value: countOf('待粗剪') + countOf('粗剪中') },
    { label: '精剪环节', value: countOf('待精剪') + countOf('精剪中') },
    { label: '待交付', value: countOf('待交付') },
    { label: '退回修改中', value: countOf('修改中'), warn: true },
    { label: '已交付', value: countOf('已交付') },
  ]
})

function availableActions(row: EditRow) {
  return ACTIONS_BY_STATUS[row.status] ?? []
}

function currentStage(row: EditRow): '' | '粗剪' | '精剪' | '交付' {
  if (['粗剪中', '待精剪'].includes(row.status)) return '粗剪'
  if (['精剪中', '待交付', '修改中'].includes(row.status)) return '精剪'
  if (row.status === '已交付') return '交付'
  return ''
}

function stageVersion(row: EditRow, stage: string) {
  if (stage === '粗剪') return row.粗剪版本
  if (stage === '精剪') return row.精剪版本
  if (stage === '交付') return row.交付版本
  return ''
}

function canHaveVersion(row: EditRow) {
  return row.status !== '待粗剪'
}

function canRecover(row: EditRow) {
  const stage = currentStage(row)
  if (!stage) return false
  // 空版本或已标记读取失败时才允许恢复到上一版。
  return Boolean(row.read_error) || !String(stageVersion(row, stage) ?? '').trim()
}

function roundText(value: unknown) {
  const round = Number(value ?? 0)
  return round > 0 ? `第 ${round} 轮` : '—'
}

function statusClass(status: string) {
  if (status === '修改中') return 'st-revision'
  if (status === '已交付') return 'st-done'
  if (status === '待交付') return 'st-wait'
  return ''
}

function resetFilters() {
  filters.keyword = ''
  filters.status = ''
  filters.round = ''
  void reload()
}

function exportRows() {
  const query = new URLSearchParams()
  if (filters.keyword) query.set('keyword', filters.keyword)
  if (filters.status) query.set('status', filters.status)
  if (filters.round) query.set('round', filters.round)
  const suffix = query.toString() ? `?${query.toString()}` : ''
  window.open(`${ENDPOINT}/export${suffix}`, '_blank')
}

function openCreate() {
  createDialog.form = {}
  createDialog.open = true
}

async function submitCreate() {
  errorMessage.value = ''
  createDialog.busy = true
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: { ...createDialog.form, operator: session.operator } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || '剪辑任务登记失败')
    }
    createDialog.open = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '剪辑任务登记失败'
  } finally {
    createDialog.busy = false
  }
}

function openAction(action: string, row: EditRow) {
  const config: Record<string, { title: string; sub: string; versionPlaceholder: string }> = {
    提交粗剪: { title: '提交粗剪版本', sub: `${row.任务编号} 将从「粗剪中」流转到「待精剪」`, versionPlaceholder: '如 粗剪V1' },
    提交精剪: { title: '提交精剪版本', sub: `${row.任务编号} 将从「精剪中」流转到「待交付」`, versionPlaceholder: '如 精剪V1' },
    确认交付: { title: '确认交付', sub: `${row.任务编号} 将锁定交付版本并记录交付日期`, versionPlaceholder: '' },
    退回修改: { title: '退回修改', sub: `${row.任务编号} 将进入修改轮次，列表与流程台同步切换`, versionPlaceholder: '' },
    重新提交: { title: '修改完成重新提交', sub: `第 ${row.修改轮次} 轮修改完成后重新送交付审核`, versionPlaceholder: '如 精剪V2' },
    开始粗剪: { title: '开始粗剪', sub: `${row.任务编号} 进入粗剪中`, versionPlaceholder: '' },
    开始精剪: { title: '开始精剪', sub: `${row.任务编号} 进入精剪中`, versionPlaceholder: '' },
  }
  const meta = config[action]
  dialog.open = true
  dialog.action = action
  dialog.row = row
  dialog.title = meta.title
  dialog.sub = meta.sub
  dialog.version = ''
  dialog.remark = ''
  dialog.deliveryDate = new Date().toISOString().slice(0, 10)
  dialog.needVersion = ['提交粗剪', '提交精剪', '重新提交'].includes(action)
  dialog.needDate = action === '确认交付'
  dialog.needRemark = action === '退回修改'
  dialog.versionPlaceholder = meta.versionPlaceholder
}

async function confirmAction() {
  if (!dialog.row) return
  errorMessage.value = ''
  dialog.busy = true
  const values: Record<string, string> = { action: dialog.action, operator: session.operator }
  if (dialog.needVersion && dialog.version.trim()) values.版本号 = dialog.version.trim()
  if (dialog.needDate) values.交付日期 = dialog.deliveryDate
  if (dialog.needRemark) values.remark = dialog.remark.trim() || '交付审核未通过，退回修改'
  try {
    const response = await request(`${ENDPOINT}/${dialog.row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || '状态未变更，请检查流转条件')
    }
    dialog.open = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '剪辑版本流转操作失败'
  } finally {
    dialog.busy = false
  }
}

async function markReadError(row: EditRow) {
  errorMessage.value = ''
  const stage = currentStage(row)
  try {
    const response = await request(`${ENDPOINT}/${row.id}/read-error`, {
      method: 'POST',
      body: JSON.stringify({ values: { operator: session.operator, stage } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || '读取失败标记未生效')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '标记读取失败失败'
  }
}

async function recoverVersion(row: EditRow) {
  errorMessage.value = ''
  const stage = currentStage(row)
  try {
    const response = await request(`${ENDPOINT}/${row.id}/recover`, {
      method: 'POST',
      body: JSON.stringify({ values: { operator: session.operator, stage } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || '恢复上一版失败')
    }
    await reload()
    if (historyEntry.value && String(historyEntry.value.id) === String(row.id)) {
      historyEntry.value = payload.entry as EditRow
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '恢复上一版失败'
  }
}

async function openHistory(row: EditRow) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) throw new Error('流转记录读取失败')
    historyEntry.value = (await response.json()) as EditRow
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '流转记录读取失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (filters.keyword) query.set('keyword', filters.keyword)
  if (filters.status) query.set('status', filters.status)
  if (filters.round) query.set('round', filters.round)
  try {
    const [listResponse, boardResponse] = await Promise.all([
      request(`${ENDPOINT}?${query.toString()}`),
      request(`${ENDPOINT}/board`),
    ])
    if (!listResponse.ok) throw new Error('剪辑任务列表读取失败')
    if (!boardResponse.ok) throw new Error('剪辑流程台读取失败')
    const listPayload = await listResponse.json()
    const boardPayload = await boardResponse.json()
    rows.value = (listPayload.items ?? []) as EditRow[]
    total.value = listPayload.total ?? rows.value.length
    boardGroups.value = (boardPayload.groups ?? []) as BoardGroup[]
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '剪辑版本流转台读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.page-actions { display: flex; gap: 8px; }
.stat-card.warn .stat-value { color: #b42318; }
.view-tabs { display: flex; gap: 4px; margin-bottom: 12px; }
.tab { border: 1px solid var(--border); background: #fff; border-radius: 6px 6px 0 0; padding: 6px 16px; cursor: pointer; font-size: 13px; }
.tab.active { background: var(--brand); border-color: var(--brand); color: #fff; }
.filter-item select { padding: 4px 6px; }
tr.revision { background: #fef3f2; }
.status-tag { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 12px; background: #eef2f7; }
.status-tag.st-done { background: #e7f6ec; color: #1a7f37; }
.status-tag.st-wait { background: #fff4e0; color: #b25e09; }
.status-tag.st-revision { background: #fee4e2; color: #b42318; }
.error-badge { margin-left: 6px; padding: 0 6px; border-radius: 8px; background: #b42318; color: #fff; font-size: 11px; }
.link.danger { color: #b42318; }
.btn.danger { color: #b42318; border-color: #f3c2bf; }
.btn.mini { padding: 3px 8px; font-size: 12px; }
.board { display: flex; gap: 10px; overflow-x: auto; padding-bottom: 8px; }
.board-col { flex: 0 0 230px; background: #f1f4f9; border: 1px solid var(--border); border-radius: 8px; padding: 8px; min-height: 120px; }
.board-col.revision { background: #fef3f2; border-color: #f3c2bf; }
.board-col-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; font-size: 13px; }
.board-count { background: #fff; border: 1px solid var(--border); border-radius: 10px; padding: 0 8px; font-size: 12px; }
.task-card { background: #fff; border: 1px solid var(--border); border-radius: 6px; padding: 8px; margin-bottom: 8px; }
.task-title { font-weight: 600; font-size: 13px; }
.task-meta { color: var(--muted); font-size: 12px; margin: 2px 0 6px; }
.task-versions { display: flex; flex-direction: column; gap: 2px; font-size: 12px; }
.task-foot { display: flex; justify-content: space-between; align-items: center; margin: 6px 0; }
.round-chip { background: #fee4e2; color: #b42318; border-radius: 8px; padding: 0 6px; font-size: 11px; }
.task-date { color: var(--muted); font-size: 11px; }
.task-actions { display: flex; flex-wrap: wrap; gap: 4px; }
.board-empty { color: var(--muted); font-size: 12px; text-align: center; padding: 8px 0; }
.board-error { margin-bottom: 8px; }
.modal-mask { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45); display: flex; align-items: center; justify-content: center; z-index: 20; }
.modal { background: #fff; border-radius: 10px; padding: 18px 20px; width: 420px; max-height: 85vh; overflow-y: auto; }
.modal.wide { width: 620px; }
.modal h3 { margin: 0 0 4px; font-size: 16px; }
.modal-sub { margin: 0 0 12px; color: var(--muted); font-size: 12px; }
.form-item { display: block; margin-bottom: 12px; font-size: 13px; }
.form-item span { display: block; margin-bottom: 4px; color: var(--muted); font-size: 12px; }
.form-item input, .form-item textarea { width: 100%; padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; font-family: inherit; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }
.lifecycle { list-style: none; margin: 0; padding: 0 0 0 12px; border-left: 2px solid var(--border); }
.lifecycle-item { position: relative; padding: 0 0 14px 14px; }
.lifecycle-item::before { content: ''; position: absolute; left: -17px; top: 4px; width: 8px; height: 8px; border-radius: 50%; background: var(--brand); }
.lifecycle-head { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.lifecycle-route { color: var(--muted); font-size: 12px; }
.lifecycle-meta { color: var(--muted); font-size: 12px; margin-top: 2px; }
.lifecycle-note { font-size: 12px; margin-top: 2px; }
.snapshot-title { font-size: 13px; margin: 12px 0 6px; }
.snapshots { margin: 0; padding-left: 18px; font-size: 12px; color: #374151; }
.snapshots li { margin-bottom: 4px; }
</style>
