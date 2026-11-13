import { buildManagementDashboardStorage } from './generate-management-dashboard.mjs'
const base = process.env.GOVIEW_API_BASE || 'http://localhost:8083/api/goview'
const api = async (path, body, auth = {}) => {
  const form = body instanceof FormData
  const response = await fetch(base + path, { method: 'POST', headers: form ? auth : { 'Content-Type': 'application/json', ...auth }, body: form ? body : JSON.stringify(body) })
  const data = await response.json()
  if (!response.ok || data.code !== 200) throw new Error(`${path}: ${data.msg || data.message || response.status}`)
  return data.data
}
const login = await api('/sys/login', { username: process.env.GOVIEW_USERNAME || 'admin', password: process.env.GOVIEW_PASSWORD || 'admin' })
const auth = { [login.token.tokenName]: login.token.tokenValue }
const storage = buildManagementDashboardStorage()
const project = await api('/project/create', { projectName: storage.editCanvasConfig.projectName, remarks: storage.editCanvasConfig.remarks, indexImage: null }, auth)
storage.editCanvasConfig.projectId = String(project.id)
const form = new FormData(); form.append('projectId', String(project.id)); form.append('content', JSON.stringify(storage))
await api('/project/save/data', form, auth)
console.log(`Created NEW unpublished management project: ${project.id}\nEditor: http://localhost:3000/#/chart/home/${project.id}\nOpen the editor and click 预览; publishing is a separate action.`)
