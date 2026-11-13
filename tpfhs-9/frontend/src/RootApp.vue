<template>
  <div id="app-root">
    <Login v-if="currentView === 'login' && !embedded" @login-success="handleLoginSuccess" />
    <div v-else-if="embedded && authState === 'loading'" class="embedded-auth-state">
      正在验证主系统登录状态...
    </div>
    <div v-else-if="embedded && authState === 'unavailable'" class="embedded-auth-state">
      <p>碳排放模型服务暂时不可用</p>
      <button type="button" @click="reloadPage">重新连接</button>
    </div>
    <div v-else-if="embedded && authState === 'forbidden'" class="embedded-auth-state">
      当前账号没有访问碳排放模型的权限
    </div>
    <HomePage 
      v-else-if="currentView === 'home'" 
      :current-user="currentUser"
      @navigate="handleNavigate"
      @logout="handleLogout"
    />
    <TemplateList
      v-else-if="currentView === 'template-list'"
      :current-user="currentUser"
      :embedded="embedded"
      @open-template="handleOpenTemplate"
      @edit-factor-template="handleEditFactorTemplate"
      @back="handleBackToHome"
      @logout="handleLogout"
    />
    <CarbonParamsSettings
      v-else-if="currentView === 'params-settings'"
      :current-user="currentUser"
      :embedded="embedded"
      :initial-factor-template-id="autoOpenFactorTemplateId"
      @back="handleBackToHome"
      @logout="handleLogout"
    />
    <App 
      v-else-if="currentView === 'design'" 
      :current-template="currentTemplate"
      :current-user="currentUser"
      @back="handleBackToTemplateList"
    />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { getAuthToken, requestAuthToken } from './auth-token'
import Login from './components/Login.vue'
import HomePage from './components/HomePage.vue'
import TemplateList from './components/TemplateList.vue'
import CarbonParamsSettings from './components/CarbonParamsSettings.vue'
import App from './App.vue'

const currentView = ref('login')
const currentUser = ref(null)
const currentTemplate = ref(null)
// 从模版管理页跳转"编辑因子"时携带的因子模版ID（CarbonParamsSettings 据此自动打开对应因子模版）
const autoOpenFactorTemplateId = ref(null)
const embedded = ref(false)
const authState = ref('loading')

const loadCurrentUser = async () => {
  const { data } = await axios.get('/api/security/me')
  currentUser.value = data
  localStorage.setItem('user', JSON.stringify(data))
}

const notifyAuthExpired = () => {
  if (!embedded.value || window.parent === window) return
  const parentOrigin = document.referrer ? new URL(document.referrer).origin : '*'
  window.parent.postMessage({ type: 'carbon:auth-expired' }, parentOrigin)
}

onMounted(async () => {
  const params = new URLSearchParams(window.location.search)
  embedded.value = params.get('embedded') === '1'

  try {
    if (embedded.value && !getAuthToken()) await requestAuthToken()
    try {
      await loadCurrentUser()
    } catch (error) {
      // 页面复用或主系统刚刷新令牌时，强制向父页面索取一次最新令牌再重试。
      if (!embedded.value || ![401, 403].includes(error?.response?.status)) throw error
      if (error?.response?.status === 401) {
        await requestAuthToken(3000, true)
        await loadCurrentUser()
      } else {
        throw error
      }
    }
    authState.value = 'ready'
    currentView.value = params.get('view') === 'params' ? 'params-settings' : 'template-list'
    if (!embedded.value) currentView.value = 'home'
    return
  } catch (error) {
    if (embedded.value) {
      if (error?.response?.status === 403) {
        authState.value = 'forbidden'
        ElMessage.error('当前账号没有访问该模块的权限')
      } else if (error?.response?.status === 401) {
        authState.value = 'expired'
        notifyAuthExpired()
      } else {
        authState.value = 'unavailable'
        ElMessage.error('碳排放模型服务暂时不可用，请稍后重试')
        return
      }
      return
    }
  }
  
  const savedUser = localStorage.getItem('user')
  if (savedUser) {
    try {
      currentUser.value = JSON.parse(savedUser)
      currentView.value = 'home'
      console.log('Found saved user, navigating to home')
    } catch (e) {
      console.error('Failed to parse saved user:', e)
      localStorage.removeItem('user')
    }
  }
})

const reloadPage = () => window.location.reload()

const handleLoginSuccess = (user) => {
  console.log('Login success:', user)
  currentUser.value = user
  localStorage.setItem('user', JSON.stringify(user))
  currentView.value = 'home'
}

const handleNavigate = (view) => {
  console.log('Navigate to:', view)
  if (view === 'template-list') {
    currentView.value = 'template-list'
  } else if (view === 'params-settings') {
    currentView.value = 'params-settings'
  }
}

const handleOpenTemplate = (template) => {
  console.log('Open template:', template)
  currentTemplate.value = template
  currentView.value = 'design'
}

const handleBackToTemplateList = () => {
  console.log('Back to template list')
  currentTemplate.value = null
  currentView.value = 'template-list'
}

const handleBackToHome = () => {
  autoOpenFactorTemplateId.value = null
  if (embedded.value) {
    const parentOrigin = document.referrer ? new URL(document.referrer).origin : '*'
    window.parent.postMessage({ type: 'carbon:navigate-home' }, parentOrigin)
    return
  }
  currentView.value = 'home'
}

// 从核算模版编辑弹窗跳转编辑某个因子模版的因子配置
const handleEditFactorTemplate = (factorTemplateId) => {
  console.log('Edit factor template:', factorTemplateId)
  autoOpenFactorTemplateId.value = factorTemplateId
  currentView.value = 'params-settings'
}

const handleLogout = () => {
  console.log('Logout')
  localStorage.removeItem('user')
  currentUser.value = null
  currentTemplate.value = null
  currentView.value = 'login'
}
</script>
