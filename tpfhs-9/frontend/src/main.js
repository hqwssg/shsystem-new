import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import axios from 'axios'
import 'element-plus/dist/index.css'
import './style.css'
import RootApp from './RootApp.vue'
import { getAuthToken } from './auth-token'

axios.interceptors.request.use(config => {
  const token = getAuthToken()
  if (token) {
    config.headers = config.headers || {}
    if (typeof config.headers.set === 'function') {
      config.headers.set('Authorization', `Bearer ${token}`)
    } else {
      config.headers.Authorization = `Bearer ${token}`
    }
  }
  return config
})

const nativeFetch = window.fetch.bind(window)
window.fetch = (input, init = {}) => {
  const inheritedHeaders = input instanceof Request ? input.headers : undefined
  const headers = new Headers(init.headers || inheritedHeaders)
  const token = getAuthToken()
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`)
  }
  return nativeFetch(input, { ...init, headers })
}

const app = createApp(RootApp)
app.use(ElementPlus)
app.mount('#app')
