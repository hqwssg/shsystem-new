<template>
  <div class="app-container">
    <el-form :inline="true" size="small">
      <el-form-item>
        <el-button :icon="$icon('el-icon-back')" @click="$router.push('/carbon')">返回上级菜单</el-button>
        <el-button type="primary" v-hasPermi="['carbon:energy:run']" @click="$router.push('/carbon/energy/create')">新建任务</el-button>
        <el-button v-hasPermi="['carbon:energy:version']" @click="$router.push('/carbon/energy/versions')">数据版本</el-button>
        <el-button :disabled="!rows.length" @click="selectAll">全选</el-button>
        <el-button type="danger" plain :disabled="!selected.length" v-hasPermi="['carbon:energy:remove']" @click="removeSelected">删除</el-button>
      </el-form-item>
      <el-form-item label="任务类型">
        <el-select v-model="runType" clearable placeholder="全部" @change="fetch">
          <el-option v-for="item in runTypes" :key="item.value" :label="item.label" :value="item.value" :title="item.tip" />
        </el-select>
      </el-form-item>
      <el-form-item label="状态">
        <el-select v-model="status" clearable placeholder="全部" @change="fetch">
          <el-option label="排队" value="pending" />
          <el-option label="校验中" value="validating" />
          <el-option label="计算中" value="running" />
          <el-option label="成功" value="succeeded" />
          <el-option label="失败" value="failed" />
          <el-option label="已取消" value="cancelled" />
        </el-select>
      </el-form-item>
    </el-form>
    <el-table ref="runTable" v-loading="loading" :data="rows" row-key="runId" @selection-change="onSelectionChange">
      <el-table-column type="selection" width="50" align="center" />
      <el-table-column prop="runId" label="任务编号" min-width="220" />
      <el-table-column prop="runType" label="类型" width="160">
        <template #default="scope">{{ typeText(scope.row.runType) }}</template>
      </el-table-column>
      <el-table-column prop="projectCode" label="项目" width="120" />
      <el-table-column prop="versionCode" label="版本" width="120" />
      <el-table-column prop="status" label="状态" width="110" />
      <el-table-column label="排队时间" width="170">
        <template #default="scope">{{ formatTime(scope.row.queuedAt) }}</template>
      </el-table-column>
      <el-table-column label="开始时间" width="170">
        <template #default="scope">{{ formatTime(scope.row.startedAt) }}</template>
      </el-table-column>
      <el-table-column label="结束时间" width="170">
        <template #default="scope">{{ formatTime(scope.row.finishedAt) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="scope">
          <el-button link @click="$router.push('/carbon/energy/runs/' + scope.row.runId)">查看</el-button>
          <el-button link class="el-button--danger" v-hasPermi="['carbon:energy:remove']" @click="remove(scope.row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-if="!loading && !rows.length" description="暂无任务" />
  </div>
</template>
<script>
import { listRuns, deleteRun } from '@/api/carbon/energy'
import { formatEnergyTime } from '@/utils/energyTime'
import { ENERGY_RUN_TYPES, energyRunTypeLabel } from '@/utils/energyParameters'
export default {
  name: 'CarbonEnergyIndex',
  data() {
    return {
      loading: false,
      rows: [],
      selected: [],
      runType: '',
      status: '',
      runTypes: ENERGY_RUN_TYPES
    }
  },
  created() {
    this.fetch()
  },
  methods: {
    typeText(type) {
      return energyRunTypeLabel(type) || type
    },
    formatTime(value) {
      return formatEnergyTime(value)
    },
    onSelectionChange(rows) {
      this.selected = rows || []
    },
    selectAll() {
      if (!this.$refs.runTable) {
        return
      }
      this.rows.forEach(row => {
        this.$refs.runTable.toggleRowSelection(row, true)
      })
    },
    remove(row) {
      this.$confirm('删除后不可恢复，结果工件也会一并删除。是否继续？', '删除任务', {
        type: 'warning'
      }).then(() => deleteRun(row.runId)).then(() => {
        this.$message.success('已删除')
        this.fetch()
      }).catch(err => {
        if (err !== 'cancel' && err !== 'close') {
          this.$message.error('删除失败')
        }
      })
    },
    removeSelected() {
      const ids = this.selected.map(item => item.runId).filter(Boolean)
      if (!ids.length) {
        this.$message.warning('请先选择任务')
        return
      }
      this.$confirm('将删除选中的 ' + ids.length + ' 条任务，结果工件也会一并删除。是否继续？', '删除任务', {
        type: 'warning'
      }).then(() => {
        this.loading = true
        let ok = 0
        let fail = 0
        const deleteNext = index => {
          if (index >= ids.length) {
            return Promise.resolve()
          }
          return deleteRun(ids[index]).then(() => {
            ok += 1
          }).catch(() => {
            fail += 1
          }).then(() => deleteNext(index + 1))
        }
        return deleteNext(0).then(() => {
          if (fail) {
            this.$message.warning('已删除 ' + ok + ' 条，失败 ' + fail + ' 条')
          } else {
            this.$message.success('已删除 ' + ok + ' 条')
          }
          this.selected = []
          this.fetch()
        })
      }).catch(err => {
        if (err !== 'cancel' && err !== 'close') {
          this.$message.error('删除失败')
        }
      })
    },
    fetch() {
      this.loading = true
      listRuns({
        runType: this.runType || undefined,
        status: this.status || undefined
      }).then(res => {
        this.rows = res.data || []
      }).catch(() => {
        this.rows = []
        this.$message.error('加载任务列表失败')
      }).finally(() => { this.loading = false })
    }
  }
}
</script>
