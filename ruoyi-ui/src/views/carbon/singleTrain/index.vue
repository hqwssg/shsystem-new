<template>
  <div class="app-container">
    <h2>单列车能量回收</h2>
    <p class="hint">仿真列车制动电能回收，比较控制方案并验证不同工况。</p>
    <el-button v-hasPermi="['carbon:singleTrain:run']" type="primary" @click="$router.push('/carbon/single-train/create')">新建任务</el-button>
    <el-button v-hasPermi="['carbon:singleTrain:version']" @click="$router.push('/carbon/single-train/versions')">数据维护</el-button>
    <el-button :loading="loading" @click="load">刷新</el-button>
    <el-table :data="items" style="margin-top:24px" v-loading="loading">
      <el-table-column prop="versionName" label="数据版本" min-width="240" />
      <el-table-column label="功能" width="160"><template #default="s">{{ taskNames[s.row.run_type] }}</template></el-table-column>
      <el-table-column label="状态" width="140"><template #default="s"><el-tag>{{ statusNames[s.row.status] }}</el-tag></template></el-table-column>
      <el-table-column label="进度" width="130"><template #default="s">{{ s.row.completed_cases }} / {{ s.row.total_cases }}</template></el-table-column>
      <el-table-column prop="created_at" label="创建时间" min-width="190" />
      <el-table-column label="操作" width="110"><template #default="s"><el-button link @click="$router.push('/carbon/single-train/runs/'+s.row.run_id)">查看结果</el-button></template></el-table-column>
    </el-table>
    <el-empty v-if="!loading && !items.length" description="尚无任务，请先选择数据版本并新建任务" />
  </div>
</template>
<script>
import { runs, taskNames, statusNames } from '@/api/carbon/singleTrain'
import { requestResult } from '@/utils/singleTrainRequests'
export default {
  name: 'CarbonSingleTrain', data: () => ({ items: [], loading: false, taskNames, statusNames }),
  created() { this.load() }, methods: { async load() { if (this.loading) return; this.loading = true; try { const result = await requestResult(runs()); if (result.ok) this.items = result.response.data } finally { this.loading = false } } }
}
</script>
<style scoped>.hint{color:#606266;margin-bottom:24px}</style>
