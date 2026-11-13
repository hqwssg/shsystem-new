import request from '@/utils/request'

export function versionApi(target = 'single') {
  const base = target === 'energy' ? '/carbon/energy' : '/carbon/single-train'
  const versions = target === 'energy' ? base + '/shared-versions' : base + '/versions'
  const sources = target === 'energy' ? base + '/data-sources' : base + '/sources'
  return {
    list: () => request({ url: versions }), sources: () => request({ url: sources }),
    preview: data => request({ url: sources + '/preview', method: 'post', data }),
    derive: data => request({ url: versions, method: 'post', data }),
    get: id => request({ url: versions + '/' + id }),
    save: (id, data) => request({ url: versions + '/' + id, method: 'put', data }),
    defaults: id => request({ url: versions + '/' + id + '/defaults', method: 'post' }),
    publish: id => request({ url: versions + '/' + id + '/publish', method: 'post', timeout: 180000 }),
    upload: (id, data) => request({ url: versions + '/' + id + '/files', method: 'post', data, timeout: 180000 })
  }
}
const base = '/carbon/single-train'
export const runs = () => request({ url: base + '/runs' })
export const run = id => request({ url: base + '/runs/' + id })
export const createRun = data => request({ url: base + '/runs', method: 'post', data, timeout: 180000 })
export const cancelRun = id => request({ url: base + '/runs/' + id + '/cancel', method: 'post' })
export const preset = versionId => request({ url: base + '/parameter-preset', params: { versionId }, timeout: 180000 })
export const trace = id => request({ url: base + '/cases/' + id + '/trace' })
export const download = id => request({ url: base + '/artifacts/' + id, responseType: 'blob', timeout: 180000 })
export const taskNames = { simulation: '主算法仿真', comparison: '控制器对比', validation: '多场景验证', eco_driving: '节能驾驶' }
export const statusNames = { queued: '排队中', running: '计算中', completed: '计算完成', partial: '部分完成', failed: '执行失败', cancelled: '已取消' }
