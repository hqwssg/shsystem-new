import request from '@/utils/request'

export function listBindings() {
  return request({ url: '/carbon/energy/bindings', method: 'get' })
}

export function bindProject(data) {
  return request({ url: '/carbon/energy/bindings', method: 'post', data })
}

export function listVersions() {
  return request({ url: '/carbon/energy/versions', method: 'get' })
}

export function publishVersion(form) {
  return request({ url: '/carbon/energy/versions', method: 'post', data: form, headers: { 'Content-Type': 'multipart/form-data' }, timeout: 120000 })
}

export function publishExcelVersion(form) {
  return request({
    url: '/carbon/energy/versions/excel',
    method: 'post',
    data: form,
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
    errorMode: 'silent'
  })
}

export function listExcelTemplates() {
  return request({ url: '/carbon/energy/excel-templates', method: 'get' })
}

export function downloadExcelTemplate(code) {
  return request({
    url: '/carbon/energy/excel-templates/' + code,
    method: 'get',
    responseType: 'blob'
  })
}

export function downloadExcelTemplateZip() {
  return request({
    url: '/carbon/energy/excel-template-zip',
    method: 'get',
    responseType: 'blob'
  })
}

export function getVersionTables(query) {
  return request({ url: '/carbon/energy/version-tables', method: 'get', params: query, timeout: 120000 })
}

export function saveVersionTables(data) {
  return request({ url: '/carbon/energy/version-tables', method: 'put', data, timeout: 120000 })
}

export function listVersionFiles(query) {
  return request({ url: '/carbon/energy/version-files', method: 'get', params: query })
}

export function getParameterPreset(query) {
  return request({ url: '/carbon/energy/parameter-preset', method: 'get', params: query })
}

export function listRuns(query) {
  return request({ url: '/carbon/energy/runs', method: 'get', params: query })
}

export function createRun(data) {
  return request({ url: '/carbon/energy/runs', method: 'post', data })
}

export function getRun(runId) {
  return request({ url: '/carbon/energy/runs/' + runId, method: 'get' })
}

export function cancelRun(runId, data) {
  return request({ url: '/carbon/energy/runs/' + runId + '/cancel', method: 'post', data })
}

export function deleteRun(runId) {
  return request({ url: '/carbon/energy/runs/' + runId, method: 'delete' })
}

export function getSummary(runId) {
  return request({ url: '/carbon/energy/runs/' + runId + '/summary', method: 'get' })
}

export function getTimetable(runId) {
  return request({ url: '/carbon/energy/runs/' + runId + '/timetable', method: 'get' })
}

export function getOptimization(runId) {
  return request({ url: '/carbon/energy/runs/' + runId + '/optimization', method: 'get' })
}

export function getRolling(runId) {
  return request({ url: '/carbon/energy/runs/' + runId + '/rolling', method: 'get' })
}

export function getRobustness(runId) {
  return request({ url: '/carbon/energy/runs/' + runId + '/robustness', method: 'get' })
}

export function listArtifacts(runId) {
  return request({ url: '/carbon/energy/runs/' + runId + '/artifacts', method: 'get' })
}

export function downloadArtifact(runId, path) {
  return request({
    url: '/carbon/energy/artifacts',
    method: 'get',
    params: { runId, path },
    responseType: 'blob',
    timeout: 60000
  })
}
