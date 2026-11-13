<template>
  <el-container class="app-shell">
    <el-aside width="240px" class="app-aside">
      <div class="brand">
        <el-icon class="brand-mark"><DataAnalysis /></el-icon>
        <div>
          <div class="brand-title">碳排放趋势预测</div>
          <div class="brand-sub">智能管理平台</div>
        </div>
      </div>

      <el-menu :default-active="$route.path" router class="side-menu">
        <el-sub-menu index="data">
          <template #title>
            <el-icon><DataLine /></el-icon>
            <span>数据管理</span>
          </template>
          <el-menu-item index="/data/history">
            <el-icon><Clock /></el-icon><span>历史数据浏览</span>
          </el-menu-item>
          <el-menu-item index="/data/ingest">
            <el-icon><UploadFilled /></el-icon><span>新数据入库</span>
          </el-menu-item>
          <el-menu-item index="/data/factors">
            <el-icon><Coin /></el-icon><span>碳排放因子管理</span>
          </el-menu-item>
          <el-menu-item index="/data/policy">
            <el-icon><TrendCharts /></el-icon><span>政策/外部因子月度数据</span>
          </el-menu-item>
          <el-menu-item index="/data/calendar">
            <el-icon><Calendar /></el-icon><span>大事件日历表管理</span>
          </el-menu-item>
        </el-sub-menu>

        <el-sub-menu index="anomaly">
          <template #title>
            <el-icon><Warning /></el-icon>
            <span>异常数据管理</span>
          </template>
          <el-menu-item index="/anomaly/review">
            <el-icon><Checked /></el-icon><span>异常数据人工审核</span>
          </el-menu-item>
          <el-menu-item index="/anomaly/history">
            <el-icon><Files /></el-icon><span>历史异常数据浏览</span>
          </el-menu-item>
        </el-sub-menu>

        <el-menu-item index="/model">
          <el-icon><Cpu /></el-icon><span>模型管理</span>
        </el-menu-item>
        <el-menu-item index="/forecast">
          <el-icon><DataAnalysis /></el-icon><span>碳排放预测</span>
        </el-menu-item>
      </el-menu>

      <div class="aside-footer">
        <div class="status-dot"></div>
        <span>平台模块 · V1.0</span>
      </div>
    </el-aside>

    <el-container>
      <el-header class="app-header">
        <div class="header-left">
          <el-breadcrumb separator="/">
            <el-breadcrumb-item>{{ $route.meta.group || '平台' }}</el-breadcrumb-item>
            <el-breadcrumb-item>{{ $route.meta.title || '首页' }}</el-breadcrumb-item>
          </el-breadcrumb>
        </div>
        <div class="header-right">
          <el-button v-if="embedded" text type="primary" @click="returnHome">
            <el-icon><Back /></el-icon>返回主界面
          </el-button>
          <el-divider v-if="embedded" direction="vertical" />
          <span class="header-note">铁路碳排放趋势预测智能管理平台</span>
          <el-divider direction="vertical" />
          <span class="user-text">平台管理员</span>
        </div>
      </el-header>

      <el-main class="app-main">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { computed } from 'vue'

const embedded = computed(() => window.parent !== window)

function returnHome() {
  if (window.parent !== window) {
    window.parent.postMessage({ type: 'carbon:navigate-home' }, window.location.origin)
  } else {
    window.location.href = '/carbon/index'
  }
}
</script>

<style scoped>
.app-shell {
  min-height: 100vh;
}

.app-aside {
  position: relative;
  background: #fff;
  border-right: 1px solid #e4e7ed;
  color: #303133;
  overflow: hidden;
}

.brand {
  height: 68px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 18px;
  border-bottom: 1px solid #ebeef5;
}

.brand-mark {
  color: #4b5563;
  font-size: 19px;
}

.brand-title {
  font-size: 15px;
  font-weight: 700;
  color: #303133;
}

.brand-sub {
  margin-top: 4px;
  font-size: 11px;
  color: #909399;
  letter-spacing: 1px;
}

.side-menu {
  padding: 8px 0;
  background: #fff;
}

.side-menu :deep(.el-menu-item),
.side-menu :deep(.el-sub-menu__title) {
  color: rgba(0, 0, 0, 0.65);
  margin: 0;
  height: 44px;
  line-height: 44px;
  border-radius: 0;
  padding-left: 20px !important;
}

.side-menu :deep(.el-menu-item:hover),
.side-menu :deep(.el-sub-menu__title:hover) {
  background: rgba(0, 0, 0, 0.04);
  color: #303133;
}

.side-menu :deep(.el-menu-item.is-active) {
  background: #ecf5ff;
  color: #409eff;
  border-left: none;
  border-right: 3px solid #409eff;
}

.side-menu :deep(.el-sub-menu .el-menu) {
  background: #fff;
}

.side-menu :deep(.el-sub-menu .el-menu-item) {
  min-width: 0;
  padding-left: 50px !important;
  font-size: 14px;
}

.aside-footer {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 44px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 18px;
  color: #909399;
  font-size: 11px;
  border-top: 1px solid #ebeef5;
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #67c23a;
  box-shadow: 0 0 6px rgba(103, 194, 58, 0.45);
}

.app-header {
  height: 62px;
  background: #fff;
  border-bottom: 1px solid var(--platform-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
}

.header-right {
  display: flex;
  align-items: center;
  color: var(--platform-muted);
  font-size: 12px;
}

.header-note {
  color: #8a9aad;
}

.user-text {
  color: var(--platform-navy);
  font-weight: 600;
}

.app-main {
  padding: 0;
  background: var(--platform-bg);
  min-height: calc(100vh - 62px);
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.16s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
