import axios from 'axios'
import { ElMessage } from 'element-plus'

const http = axios.create({
  baseURL: '/prediction-api/platform',
  timeout: 30000
})

let authToken = ''
let tokenWaiter = null

function requestParentToken() {
  if (window.parent === window) return Promise.resolve('')
  if (!tokenWaiter) {
    tokenWaiter = new Promise((resolve) => {
      const timeout = window.setTimeout(() => resolve(''), 5000)
      const listener = (event) => {
        if (event.origin !== window.location.origin || event.data?.type !== 'carbon:set-auth-token') return
        authToken = String(event.data.token || '')
        window.clearTimeout(timeout)
        window.removeEventListener('message', listener)
        resolve(authToken)
      }
      window.addEventListener('message', listener)
      window.parent.postMessage({ type: 'carbon:request-auth-token' }, window.location.origin)
    }).finally(() => { tokenWaiter = null })
  }
  return tokenWaiter
}

window.addEventListener('message', (event) => {
  if (event.origin !== window.location.origin || event.data?.type !== 'carbon:set-auth-token') return
  authToken = String(event.data.token || '')
})

http.interceptors.request.use(async (config) => {
  const token = authToken || await requestParentToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

http.interceptors.response.use(
  (response) => {
    const body = response.data
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code !== 0) {
        ElMessage.error(body.message || '请求失败')
        return Promise.reject(new Error(body.message || '请求失败'))
      }
      return body.data
    }
    return body
  },
  (error) => {
    if (error?.response?.status === 401 && window.parent !== window) {
      window.parent.postMessage({ type: 'carbon:auth-expired' }, window.location.origin)
    }
    const message = error?.response?.data?.message || error?.message || '网络请求失败'
    ElMessage.error(message)
    return Promise.reject(error)
  }
)

export default http
