<template>
  <section class="page" data-module="edit">
    <header class="page-head">
      <div>
        <h2>后期剪辑管理</h2>
        <p class="page-desc">维护剪辑任务，围绕任务编号、所属集数、剪辑师、粗剪版本做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记剪辑任务</button>
        <button class="btn" type="button" @click="exportRows">导出后期剪辑清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <section class="flow-board">
      <div class="flow-head">
        <h3>剪辑版本流转台</h3>
        <span class="flow-tip">按 待粗剪→粗剪中→待精剪→已交付 顺序流转，退回修改后列表、流转台与导出同步切换</span>
      </div>
      <div class="flow-stages">
        <article v-for="stage in flowStages" :key="stage.stage" class="flow-column">
          <header class="flow-column-head">
            <strong>{{ stage.stage }}</strong>
            <span class="flow-count">{{ stage.count }}</span>
          </header>
          <ul class="flow-items">
            <li v-for="item in stage.items" :key="item.id" class="flow-item">
              <span class="flow-task">{{ item.任务编号 }}</span>
              <span class="flow-meta">{{ item.当前版本 }} · {{ item.status }} · 修改{{ item.修改轮次 }}轮</span>
            </li>
            <li v-if="!stage.items.length" class="flow-empty">暂无任务</li>
          </ul>
        </article>
      </div>
      <table class="data-table flow-log">
        <thead>
          <tr>
            <th v-for="column in flowLogColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="log in flowLogs" :key="log.序号">
            <td>{{ log.时间 || '—' }}</td>
            <td>{{ log.任务编号 }}</td>
            <td>{{ log.操作人 }}</td>
            <td>{{ log.动作 }}</td>
            <td>{{ log.从状态 || '—' }} → {{ log.到状态 || '—' }}</td>
            <td>{{ log.版本 || '—' }}</td>
            <td>{{ log.交付日期 || '—' }}</td>
            <td>{{ log.修改轮次 }}</td>
          </tr>
          <tr v-if="!flowLogs.length">
            <td :colspan="flowLogColumns.length" class="empty-state">暂无流转记录，执行剪辑动作后在此展示</td>
          </tr>
        </tbody>
      </table>
      <p v-if="flowError" class="error-text flow-error">{{ flowError }}</p>
    </section>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>任务编号</span>
        <input v-model="keyword" placeholder="按任务编号检索" />
      </label>
      <label class="filter-item">
        <span>剪辑状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无后期剪辑数据，可先登记剪辑任务</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条后期剪辑记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Row = Record<string, string | number | null>

interface FlowItem {
  id: number
  任务编号: string
  所属集数: string
  剪辑师: string
  status: string
  当前版本: string | null
  修改轮次: number
  交付日期: string | null
}

interface FlowStage {
  stage: string
  statuses: string[]
  count: number
  items: FlowItem[]
}

interface FlowLog {
  序号: number
  时间: string
  任务编号: string
  操作人: string
  动作: string
  从状态: string
  到状态: string
  版本: string
  交付日期: string | null
  修改轮次: number
}

const ENDPOINT = '/api/edit'
const columns = ["任务编号", "所属集数", "剪辑师", "粗剪版本", "精剪版本", "交付日期", "修改轮次", "剪辑状态"]
const actions = ["开始粗剪", "提交精剪", "确认交付", "退回修改", "恢复上一版"]
const statuses = ["待粗剪", "粗剪中", "待精剪", "已交付"]
const flowLogColumns = ["时间", "任务编号", "操作人", "动作", "状态流转", "版本", "交付日期", "修改轮次"]

const session = useSessionStore()

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const flowStages = ref<FlowStage[]>([])
const flowLogs = ref<FlowLog[]>([])
const flowError = ref('')

const stats = computed(() => [
  { label: '粗剪阶段任务', value: stageCount('粗剪') },
  { label: '精剪阶段任务', value: stageCount('精剪') },
  { label: '已交付集数', value: stageCount('交付') },
])

function stageCount(stage: string): number {
  return flowStages.value.find((item) => item.stage === stage)?.count ?? 0
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '剪辑任务登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action, 操作人: session.operator } }),
    })
    const payload: { ok?: boolean; message?: string } | null = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message ?? '后期剪辑动作未生效，请稍后重试')
    }
    // 列表与流转台读的是同一份数据，动作生效后一起刷新，保证同步切换
    await Promise.all([reload(), reloadFlow()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '后期剪辑操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value) {
    query.set('keyword', keyword.value)
  }
  if (statusFilter.value) {
    query.set('status', statusFilter.value)
  }
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('剪辑任务列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    // 读取失败时保留上一版列表数据，只提示原因
    errorMessage.value = error instanceof Error ? error.message : '后期剪辑列表读取失败'
  }
}

async function reloadFlow() {
  flowError.value = ''
  try {
    const response = await request(`${ENDPOINT}/flow`)
    if (!response.ok) {
      throw new Error('剪辑版本流转台读取失败')
    }
    const payload = await response.json()
    flowStages.value = payload.stages ?? []
    flowLogs.value = (payload.logs ?? []).slice(0, 10)
  } catch (error) {
    // 读取失败时保留上一版流转台数据，只提示原因
    flowError.value = error instanceof Error ? error.message : '剪辑版本流转台读取失败'
  }
}

onMounted(() => {
  void reload()
  void reloadFlow()
})
</script>

<style scoped>
.flow-board { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 12px; margin-bottom: 12px; }
.flow-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 10px; }
.flow-head h3 { margin: 0; font-size: 14px; }
.flow-tip { color: var(--muted); font-size: 12px; }
.flow-stages { display: flex; gap: 10px; margin-bottom: 10px; }
.flow-column { flex: 1; border: 1px solid var(--border); border-radius: 6px; padding: 8px; background: #f8fafc; }
.flow-column-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.flow-count { background: var(--brand); color: #fff; border-radius: 10px; padding: 0 8px; font-size: 12px; }
.flow-items { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.flow-item { background: #fff; border: 1px solid var(--border); border-radius: 6px; padding: 6px 8px; display: flex; flex-direction: column; }
.flow-task { font-size: 13px; }
.flow-meta { color: var(--muted); font-size: 12px; }
.flow-empty { color: var(--muted); font-size: 12px; text-align: center; padding: 6px 0; }
.flow-log th, .flow-log td { font-size: 12px; }
.flow-error { margin: 8px 0 0; }
.filter-item select { padding: 4px 8px; }
</style>
