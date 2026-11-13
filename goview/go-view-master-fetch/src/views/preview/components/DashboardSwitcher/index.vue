<template>
  <div class="dashboard-switcher" @mousedown.stop @click.stop>
    <n-button class="dashboard-switcher__home" size="small" @click="returnToMain">
      <template #icon>
        <n-icon><HomeIcon /></n-icon>
      </template>
      返回主界面
    </n-button>
    <n-tooltip v-if="!opened" placement="left">
      <template #trigger>
        <n-button
          class="dashboard-switcher__trigger"
          :class="{ 'is-error': dashboardLoadError }"
          size="small"
          @click="opened = true"
        >
          <template #icon>
            <n-icon><BrowsersOutlineIcon /></n-icon>
          </template>
          切换大屏
        </n-button>
      </template>
      选择大屏项目
    </n-tooltip>

    <section v-else class="dashboard-switcher__panel">
      <header>
        <span>大屏展示</span>
        <div class="dashboard-switcher__panel-actions">
          <n-button quaternary size="tiny" title="返回主界面" @click="returnToMain">返回主界面</n-button>
          <n-button quaternary circle size="tiny" title="收起" @click="opened = false">
            <template #icon><n-icon><CloseIcon /></n-icon></template>
          </n-button>
        </div>
      </header>

      <n-select
        v-model:value="selectedId"
        :options="options"
        :loading="loading"
        filterable
        size="small"
        placeholder="选择已发布项目"
        @update:value="switchProject"
      />

      <div class="dashboard-switcher__manual">
        <n-input v-model:value="manualId" size="small" placeholder="项目 ID" @keyup.enter="openManual" />
        <n-button size="small" type="primary" :disabled="!validManualId" @click="openManual">打开</n-button>
      </div>

      <p v-if="listError" class="dashboard-switcher__error">{{ listError }}</p>
      <p v-if="dashboardLoadError" class="dashboard-switcher__error">{{ dashboardLoadError }}</p>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { projectListApi } from '@/api/path'
import { icon } from '@/plugins'
import { dashboardLoadError } from '@/assets/dashboard/dashboardLiveData'
import { loginCheck } from '@/utils'
import { mainApplicationUrl } from '@/utils/mainApplication'
import { PreviewEnum } from '@/enums/pageEnum'
import type { ProjectItem } from '@/api/path/project'

const { BrowsersOutlineIcon, CloseIcon, HomeIcon } = icon.ionicons5
const route = useRoute()
const router = useRouter()
const opened = ref(false)
const loading = ref(false)
const listError = ref('')
const options = ref<Array<{ label: string; value: string }>>([])

const routeProjectId = computed(() => {
  const raw = route.params.id
  return String(Array.isArray(raw) ? raw[0] : raw || '').trim()
})
const selectedId = ref(routeProjectId.value)
const manualId = ref(routeProjectId.value)
const validManualId = computed(() => /^\d+$/.test(manualId.value.trim()))
const DEFAULT_PROJECT_KEY = 'carbon-dashboard-default-project'
const DEFAULT_PROJECT_COOKIE = 'carbon-dashboard-project'

const rememberDefaultProject = (projectId: string) => {
  if (!/^\d+$/.test(projectId)) return
  try {
    localStorage.setItem(DEFAULT_PROJECT_KEY, projectId)
    // Cookies are host-scoped (unlike localStorage, which is port-scoped),
    // so the management UI can use the choice made on the GoView port.
    document.cookie = `${DEFAULT_PROJECT_COOKIE}=${encodeURIComponent(projectId)}; Max-Age=31536000; Path=/; SameSite=Lax`
  } catch {
    // Private browsing may deny storage; the current route still switches.
  }
}

watch(routeProjectId, value => {
  selectedId.value = value
  manualId.value = value
})

const loadProjects = async () => {
  if (!loginCheck()) {
    listError.value = '请先登录后查看项目列表，或使用有权限的项目ID'
    return
  }
  loading.value = true
  listError.value = ''
  try {
    const response = await projectListApi({ page: 1, limit: 200 })
    if (!response || response.code !== 200 || !Array.isArray(response.data)) {
      throw new Error('project-list')
    }
    const projects = response.data
    options.value = projects
      .filter((project: ProjectItem) => project.state === 1)
      .map((project: ProjectItem) => ({ label: project.projectName, value: String(project.id) }))
    if (routeProjectId.value && !options.value.some(item => item.value === routeProjectId.value)) {
      options.value.unshift({ label: `当前大屏 (${routeProjectId.value})`, value: routeProjectId.value })
    }
  } catch {
    listError.value = '项目列表加载失败'
  } finally {
    loading.value = false
  }
}

const switchProject = async (projectId: string) => {
  if (!projectId || projectId === routeProjectId.value) return
  await router.push({ name: PreviewEnum.CHART_PREVIEW_NAME, params: { id: projectId }, query: route.query })
  rememberDefaultProject(projectId)
  opened.value = false
}

const openManual = () => {
  const projectId = manualId.value.trim()
  if (validManualId.value) void switchProject(projectId)
}

const returnToMain = () => {
  window.location.assign(mainApplicationUrl())
}

watch(opened, value => {
  if (value) void loadProjects()
})
</script>

<style scoped lang="scss">
.dashboard-switcher {
  position: fixed;
  top: 12px;
  right: 12px;
  z-index: 10000;
  font-size: 13px;
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.dashboard-switcher__home {
  border: 1px solid rgba(66, 190, 255, 0.65);
  background: rgba(4, 22, 36, 0.88);
  color: #e8f7ff;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.3);
  backdrop-filter: blur(8px);
}

.dashboard-switcher__trigger {
  border: 1px solid rgba(66, 190, 255, 0.65);
  background: rgba(4, 22, 36, 0.88);
  color: #e8f7ff;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.3);
  backdrop-filter: blur(8px);
}

.dashboard-switcher__trigger.is-error {
  border-color: #ff7875;
}

.dashboard-switcher__panel {
  width: 320px;
  padding: 12px;
  border: 1px solid rgba(66, 190, 255, 0.65);
  border-radius: 6px;
  background: rgba(4, 22, 36, 0.94);
  color: #e8f7ff;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.42);
  backdrop-filter: blur(10px);
}

.dashboard-switcher__panel header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 28px;
  margin-bottom: 8px;
  font-weight: 600;
}

.dashboard-switcher__panel-actions {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.dashboard-switcher__manual {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  margin-top: 8px;
}

.dashboard-switcher__error {
  margin: 8px 0 0;
  color: #ff9c9c;
  font-size: 12px;
  line-height: 18px;
}

@media (max-width: 480px) {
  .dashboard-switcher__panel {
    width: min(320px, calc(100vw - 24px));
  }
}
</style>
