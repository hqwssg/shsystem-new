<template>
  <div class="version-edit">
    <el-alert title="直接修改当前选中的版本。保存后覆盖该版本的数据文件，不生成新版本号。已经用这个版本跑过的任务不会自动重算。" type="info" :closable="false" show-icon />
    <el-form label-width="120px" size="small" class="version-form">
      <el-form-item label="数据版本">
        <el-select v-model="versionKey" filterable placeholder="请选择已发布版本" style="width: 460px" @change="onVersionChange">
          <el-option v-for="item in versions" :key="item.projectCode + '/' + item.versionCode"
            :label="versionLabel(item)"
            :value="item.projectCode + '/' + item.versionCode" />
        </el-select>
      </el-form-item>
    </el-form>
    <div v-if="!versions.length" class="form-hint">当前部门没有已发布版本。</div>
    <div v-else class="edit-layout">
      <el-menu class="topic-menu" :default-active="topic" :key="menuKey" @select="onTopicSelect">
        <el-menu-item v-for="item in topics" :key="item.code" :index="item.code">
          <div class="topic-title">{{ item.title }}</div>
          <div class="topic-hint">{{ item.hint }}</div>
        </el-menu-item>
      </el-menu>
      <div class="edit-main" v-loading="loading">
        <div class="topic-head">
          <div>
            <div class="topic-name">{{ topicTitle || currentTopic.title }}</div>
            <div class="form-hint">{{ topicInstruction || currentTopic.hint }}</div>
          </div>
          <el-button type="primary" size="small" :loading="saving" :disabled="!versionKey || !loadedSheets.length" @click="saveTopic">保存该主题</el-button>
        </div>
        <el-tabs v-if="currentTopic.sheets.length > 1" v-model="activeSheet" @tab-click="onSheetTab">
          <el-tab-pane v-for="name in currentTopic.sheets" :key="name" :label="name" :name="name" />
        </el-tabs>
        <div v-if="currentSheet">
          <div v-if="currentSheet.hint" class="form-hint sheet-hint">{{ currentSheet.hint }} 数字不要带单位。</div>
          <el-form v-if="currentSheet.singleRow" label-width="160px" size="small" class="single-form">
            <el-form-item v-for="column in currentSheet.columns" :key="currentSheet.name + column" :label="column">
              <el-input v-model="currentSheet.rows[0][column]" style="width: 360px" @input="markDirty" />
            </el-form-item>
          </el-form>
          <template v-else>
            <div class="table-toolbar">
              <el-button size="mini" type="primary" @click="openAdd(currentSheet)">新增</el-button>
            </div>
            <el-table ref="sheetTable" :data="pagedRows" size="mini" border max-height="460" :row-class-name="conflictRowClass">
              <el-table-column v-for="column in currentSheet.columns" :key="column" :prop="column" :label="column" min-width="120" show-overflow-tooltip />
              <el-table-column label="操作" width="140" fixed="right">
                <template slot-scope="scope">
                  <el-button type="text" @click="openEdit(currentSheet, scope.$index)">编辑</el-button>
                  <el-button type="text" @click="removeRow(currentSheet, scope.$index)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
            <el-pagination
              v-if="currentSheet.rows.length > pageSize"
              class="sheet-pager"
              background
              layout="total, prev, pager, next"
              :current-page.sync="page"
              :page-size="pageSize"
              :total="currentSheet.rows.length" />
          </template>
        </div>
      </div>
    </div>

    <el-dialog :title="editingIndex < 0 ? '新增' : '编辑'" :visible.sync="dialogVisible" width="640px" append-to-body>
      <el-form label-width="140px" size="small">
        <el-form-item v-for="column in dialogColumns" :key="column" :label="column">
          <el-input v-model="dialogForm[column]" />
        </el-form-item>
      </el-form>
      <span slot="footer">
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="applyDialog">确定</el-button>
      </span>
    </el-dialog>
  </div>
</template>
<script>
import { getVersionTables, listVersions, saveVersionTables } from '@/api/carbon/energy'
import { versionOptionLabel } from '@/utils/energyParameters'
import { findSheetConflict } from '@/utils/energyVersionConflicts'

export default {
  name: 'CarbonEnergyVersionEdit',
  data() {
    return {
      loading: false,
      saving: false,
      dirty: false,
      versions: [],
      versionKey: '',
      loadedKey: '',
      menuKey: 0,
      topic: 'geometry',
      activeSheet: '线路参数',
      topicTitle: '',
      topicInstruction: '',
      sheetCache: {},
      loadToken: 0,
      page: 1,
      pageSize: 50,
      dialogVisible: false,
      dialogSheet: null,
      dialogColumns: [],
      dialogForm: {},
      editingIndex: -1,
      conflictIndex: -1,
      topics: [
        { code: 'geometry', title: '线路几何', hint: '线路总长、车站、区间坡度限速', sheets: ['线路参数', '车站', '区间'] },
        { code: 'trains', title: '列车参数', hint: '重车、空车质量与牵引制动', sheets: ['列车'] },
        { code: 'storage', title: '储能设备', hint: '容量功率电价和储能区段', sheets: ['储能参数', '储能区段'] },
        { code: 'timetable', title: '运行图', hint: '列车时刻到发', sheets: ['列车', '时刻表', '元数据'] },
        { code: 'operations', title: '追踪与作业', hint: '追踪间隔和技术作业时分', sheets: ['追踪间隔', '技术作业时分', '作业适用范围'] },
        { code: 'power_arm', title: '供电臂', hint: '供电臂起终点和储能接入', sheets: ['供电臂'] },
        { code: 'disturbance', title: '滚动扰动', hint: '历史晚点、限速、储能状态回放', sheets: ['回放说明', '周期', '事件'] },
        { code: 'joint_params', title: '联合参数', hint: '稳健性参数上下限', sheets: ['参数区间', '抽样'] }
      ]
    }
  },
  computed: {
    currentTopic() {
      return this.topics.find(item => item.code === this.topic) || this.topics[0]
    },
    currentSheet() {
      const key = this.cacheKey(this.activeSheet)
      return key ? this.sheetCache[key] : null
    },
    loadedSheets() {
      return this.currentTopic.sheets
        .map(name => this.sheetCache[this.cacheKey(name)])
        .filter(Boolean)
    },
    pagedRows() {
      const sheet = this.currentSheet
      if (!sheet) {
        return []
      }
      if (sheet.singleRow) {
        return sheet.rows
      }
      const start = (this.page - 1) * this.pageSize
      return sheet.rows.slice(start, start + this.pageSize)
    }
  },
  created() {
    this.reloadVersions()
  },
  methods: {
    versionLabel(item) {
      return versionOptionLabel(item)
    },
    cacheKey(name) {
      if (!this.versionKey || !name) {
        return ''
      }
      return this.versionKey + '/' + this.topic + '/' + name
    },
    blankRow(columns) {
      const row = {}
      ;(columns || []).forEach(column => { row[column] = '' })
      return row
    },
    normalizeSheet(sheet) {
      const columns = sheet.columns || []
      const rows = (sheet.rows || []).map(row => {
        const next = this.blankRow(columns)
        columns.forEach(column => {
          next[column] = row && row[column] != null ? String(row[column]) : ''
        })
        return next
      })
      if (sheet.singleRow && !rows.length) {
        rows.push(this.blankRow(columns))
      }
      return { name: sheet.name, columns, hint: sheet.hint || '', singleRow: !!sheet.singleRow, rows }
    },
    markDirty() {
      this.dirty = true
    },
    confirmDiscard() {
      if (!this.dirty) {
        return Promise.resolve(true)
      }
      return this.$confirm('当前主题有未保存的修改，离开后会丢弃。', '提示', { type: 'warning' }).then(() => true).catch(() => false)
    },
    selectedVersion() {
      return (this.versions || []).find(item => item.projectCode + '/' + item.versionCode === this.versionKey)
    },
    clearTopicCache() {
      const prefix = this.versionKey + '/' + this.topic + '/'
      Object.keys(this.sheetCache).forEach(key => {
        if (key.indexOf(prefix) === 0) {
          this.$delete(this.sheetCache, key)
        }
      })
    },
    clampPage() {
      const sheet = this.currentSheet
      if (!sheet || sheet.singleRow) {
        this.page = 1
        return
      }
      const pages = Math.max(1, Math.ceil(sheet.rows.length / this.pageSize))
      if (this.page > pages) {
        this.page = pages
      }
    },
    absoluteIndex(pageIndex) {
      const sheet = this.currentSheet
      if (!sheet || sheet.singleRow) {
        return pageIndex
      }
      return (this.page - 1) * this.pageSize + pageIndex
    },
    reloadVersions() {
      listVersions().then(res => {
        this.versions = res.data || []
        if (!this.versionKey && this.versions.length) {
          const first = this.versions[0]
          this.versionKey = first.projectCode + '/' + first.versionCode
          this.loadedKey = this.versionKey
          this.loadFirstSheet()
        }
      }).catch(() => {
        this.versions = []
        this.$message.error('加载版本失败')
      })
    },
    onVersionChange(value) {
      const previous = this.loadedKey
      this.confirmDiscard().then(ok => {
        if (!ok) {
          this.versionKey = previous
          return
        }
        this.dirty = false
        this.loadedKey = value
        this.sheetCache = {}
        this.topicTitle = ''
        this.topicInstruction = ''
        this.conflictIndex = -1
        this.loadFirstSheet()
      })
    },
    onTopicSelect(next) {
      if (next === this.topic) {
        return
      }
      this.confirmDiscard().then(ok => {
        if (!ok) {
          this.menuKey += 1
          return
        }
        if (this.dirty) {
          this.clearTopicCache()
        }
        this.topic = next
        this.dirty = false
        this.topicTitle = ''
        this.topicInstruction = ''
        this.conflictIndex = -1
        this.loadFirstSheet()
      })
    },
    onSheetTab(tab) {
      const name = (tab && (tab.name || tab.paneName)) || this.activeSheet
      this.page = 1
      this.conflictIndex = -1
      this.loadSheet(name)
    },
    loadFirstSheet() {
      const name = this.currentTopic.sheets[0]
      this.page = 1
      this.activeSheet = name
      this.loadSheet(name)
    },
    loadSheet(name) {
      const item = this.selectedVersion()
      const versionKey = this.versionKey
      const topic = this.topic
      if (!item || !name) {
        return
      }
      const key = versionKey + '/' + topic + '/' + name
      this.loadToken += 1
      const token = this.loadToken
      this.activeSheet = name
      if (this.sheetCache[key]) {
        this.loading = false
        return
      }
      this.loading = true
      getVersionTables({
        projectCode: item.projectCode,
        versionCode: item.versionCode,
        topic,
        sheet: name
      }).then(res => {
        if (this.versionKey !== versionKey || this.topic !== topic) {
          return
        }
        const data = res.data || {}
        const raw = (data.sheets || []).find(sheet => sheet.name === name) || (data.sheets || [])[0]
        if (!raw) {
          this.$message.error('加载表格失败')
          return
        }
        this.$set(this.sheetCache, key, this.normalizeSheet(raw))
        this.topicTitle = data.title || this.currentTopic.title
        this.topicInstruction = data.instruction || this.currentTopic.hint
        this.clampPage()
      }).catch(() => {
        if (this.versionKey === versionKey && this.topic === topic && this.activeSheet === name) {
          this.$message.error('加载表格失败')
        }
      }).finally(() => {
        if (token === this.loadToken) {
          this.loading = false
        }
      })
    },
    openAdd(sheet) {
      this.dialogSheet = sheet
      this.dialogColumns = sheet.columns
      this.dialogForm = this.blankRow(sheet.columns)
      this.editingIndex = -1
      this.dialogVisible = true
    },
    openEdit(sheet, pageIndex) {
      const index = this.absoluteIndex(pageIndex)
      this.dialogSheet = sheet
      this.dialogColumns = sheet.columns
      this.dialogForm = Object.assign(this.blankRow(sheet.columns), sheet.rows[index] || {})
      this.editingIndex = index
      this.dialogVisible = true
    },
    conflictRowClass(argument) {
      const pageIndex = argument && argument.rowIndex
      if (pageIndex == null || this.conflictIndex < 0) {
        return ''
      }
      return this.absoluteIndex(pageIndex) === this.conflictIndex ? 'conflict-row' : ''
    },
    showConflict(conflict) {
      if (conflict.index != null && conflict.index >= 0) {
        this.conflictIndex = conflict.index
        this.page = Math.floor(conflict.index / this.pageSize) + 1
        this.$nextTick(() => {
          if (!this.scrollConflictRow()) {
            this.$nextTick(() => this.scrollConflictRow())
          }
        })
      } else {
        this.conflictIndex = -1
      }
      this.$alert(conflict.message, '数据冲突', { type: 'error' })
    },
    scrollConflictRow() {
      const table = this.$refs.sheetTable
      const body = table && table.bodyWrapper
      if (!body) {
        return false
      }
      const row = body.querySelector('tr.conflict-row')
      if (!row) {
        return false
      }
      const rowTop = row.getBoundingClientRect().top
      const bodyTop = body.getBoundingClientRect().top
      body.scrollTop += rowTop - bodyTop - 8
      this.scrollPageTo(row, body)
      return true
    },
    scrollPageTo(element, skip) {
      let node = element.parentElement
      while (node) {
        if (node !== skip) {
          const overflowY = window.getComputedStyle(node).overflowY
          const canScroll = (overflowY === 'auto' || overflowY === 'scroll' || overflowY === 'overlay')
            && node.scrollHeight > node.clientHeight + 1
          if (canScroll) {
            const delta = element.getBoundingClientRect().top - node.getBoundingClientRect().top - 12
            node.scrollTop += delta
            return
          }
        }
        node = node.parentElement
      }
      const top = element.getBoundingClientRect().top
      if (Math.abs(top) > 12) {
        window.scrollBy(0, top - 12)
      }
    },
    applyDialog() {
      const sheet = this.dialogSheet
      if (!sheet) {
        return
      }
      const row = Object.assign(this.blankRow(sheet.columns), this.dialogForm)
      const conflict = findSheetConflict(sheet.name, sheet.rows, row, this.editingIndex, sheet.columns)
      if (conflict) {
        this.showConflict(conflict)
        return
      }
      this.conflictIndex = -1
      if (this.editingIndex < 0) {
        sheet.rows.push(row)
        this.page = Math.max(1, Math.ceil(sheet.rows.length / this.pageSize))
      } else {
        this.$set(sheet.rows, this.editingIndex, row)
      }
      this.dirty = true
      this.dialogVisible = false
    },
    removeRow(sheet, pageIndex) {
      const index = this.absoluteIndex(pageIndex)
      this.$confirm('删除这一行？确定后还要点「保存该主题」才会写入当前版本。', '提示', { type: 'warning' }).then(() => {
        sheet.rows.splice(index, 1)
        this.conflictIndex = -1
        this.dirty = true
        this.clampPage()
      }).catch(() => {})
    },
    saveTopic() {
      const item = this.selectedVersion()
      if (!item) {
        this.$message.error('请选择数据版本')
        return
      }
      const sheets = this.loadedSheets.map(sheet => ({
        name: sheet.name,
        rows: sheet.singleRow ? (sheet.rows || []).slice(0, 1) : sheet.rows
      }))
      if (!sheets.length) {
        this.$message.error('当前主题还没有加载完成')
        return
      }
      const versionName = this.versionLabel(item)
      const activeName = this.activeSheet
      this.$confirm('会覆盖当前版本「' + versionName + '」。已有任务仍指向该版本，重新计算会用新数据。', '覆盖当前版本', { type: 'warning' }).then(() => {
        this.saving = true
        return saveVersionTables({
          projectCode: item.projectCode,
          versionCode: item.versionCode,
          topic: this.topic,
          sourceNote: '在线编辑 ' + (this.topicTitle || this.currentTopic.title),
          sheets
        })
      }).then(result => {
        if (!result) {
          return
        }
        this.$message.success('已覆盖当前版本')
        this.dirty = false
        this.clearTopicCache()
        this.loadSheet(activeName)
      }).catch(error => {
        if (error === 'cancel' || error === 'close') {
          return
        }
        this.$message.error('保存失败')
      }).finally(() => { this.saving = false })
    }
  }
}
</script>
<style scoped>
.version-form {
  margin-top: 16px;
}
.form-hint {
  color: #909399;
  font-size: 12px;
  line-height: 1.5;
}
.edit-layout {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  margin-top: 8px;
}
.topic-menu {
  width: 240px;
  flex-shrink: 0;
  border-right: 1px solid #ebeef5;
}
.topic-title {
  line-height: 20px;
  font-weight: 600;
}
.topic-hint {
  color: #909399;
  font-size: 12px;
  line-height: 16px;
  white-space: normal;
}
.topic-menu >>> .el-menu-item {
  height: auto;
  line-height: 1.3;
  padding-top: 8px;
  padding-bottom: 8px;
  white-space: normal;
}
.edit-main {
  flex: 1;
  min-width: 0;
  min-height: 280px;
}
.topic-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 8px;
}
.topic-name {
  font-size: 16px;
  font-weight: 600;
}
.sheet-hint {
  margin: 8px 0;
}
.single-form {
  max-width: 640px;
  margin-top: 8px;
}
.table-toolbar {
  margin: 8px 0;
}
.sheet-pager {
  margin-top: 12px;
  text-align: right;
}
.edit-main >>> .conflict-row > td {
  background-color: #fde2e2 !important;
  box-shadow: inset 0 0 0 2px #f56c6c;
}
</style>
