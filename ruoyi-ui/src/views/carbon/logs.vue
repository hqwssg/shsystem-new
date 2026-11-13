<template>
  <div class="app-container carbon-logs">
    <section v-if="visibleTabs.length" class="log-workspace">
      <el-tabs v-model="activeTab" type="card">
        <el-tab-pane
          v-for="tab in visibleTabs"
          :key="tab.key"
          :name="tab.key"
          :label="tab.label"
        >
          <component :is="tab.component" v-if="activeTab === tab.key" class="embedded-log-view" />
        </el-tab-pane>
      </el-tabs>
    </section>
    <el-empty v-else description="暂无日志查看权限" />
  </div>
</template>

<script>
import { hasAnyPermission, hasAnyRole } from '@/utils/permissionMatch'
import SystemOperlog from '@/views/system/operlog/index'
import SystemLogininfor from '@/views/system/logininfor/index'
import SystemJobLog from '@/views/monitor/job/log'

const logTabs = [
  { key: 'operation', label: '操作日志', component: SystemOperlog, permissions: ['system:operlog:list'] },
  { key: 'login', label: '登录日志', component: SystemLogininfor, permissions: ['system:logininfor:list'] },
  { key: 'job', label: '任务日志', component: SystemJobLog, permissions: ['monitor:job:list'] }
]

export default {
  name: 'CarbonLogs',
  data() {
    return { activeTab: '' }
  },
  computed: {
    visibleTabs() {
      if (hasAnyRole(this.$store.getters.roles, ['admin'])) return logTabs
      return logTabs.filter(tab => hasAnyPermission(this.$store.getters.permissions, tab.permissions))
    }
  },
  watch: {
    visibleTabs: {
      immediate: true,
      handler(tabs) {
        if (!tabs.some(tab => tab.key === this.activeTab)) {
          this.activeTab = tabs[0] ? tabs[0].key : ''
        }
      }
    }
  }
}
</script>

<style scoped lang="scss">
.carbon-logs {
  min-height: calc(100vh - 84px);
  background: #f6f8fb;
}

.log-workspace {
  min-height: 720px;
  padding: 16px;
  overflow: hidden;
  border: 1px solid #e5eaf1;
  border-radius: 6px;
  background: #fff;
}

.embedded-log-view {
  min-height: 650px;
  padding: 8px 0 0;
}

</style>
