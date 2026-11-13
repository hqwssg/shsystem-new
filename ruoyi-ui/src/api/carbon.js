import axios from 'axios'
import { ElMessage as Message } from 'element-plus'
import { getToken } from '@/utils/auth'

const carbonRequest = axios.create({
  baseURL: import.meta.env.VUE_APP_CARBON_API || '/carbon-api',
  timeout: 15000
})

carbonRequest.interceptors.request.use(config => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

carbonRequest.interceptors.response.use(
  response => response.data,
  error => {
    const response = error.response || {}
    const data = response.data || {}
    const isProxyError = typeof data === 'string' && data.indexOf('Proxy error') !== -1
    const message = data.error || data.message || (isProxyError ? '碳排放服务未启动或代理配置异常' : error.message) || '碳排放服务连接异常'
    if (!error.config || !error.config.silent) {
      Message.error(message)
    }
    return Promise.reject(error)
  }
)

function cleanParams(params) {
  const result = {}
  Object.keys(params || {}).forEach(key => {
    const value = params[key]
    if (value !== undefined && value !== null && value !== '') {
      result[key] = value
    }
  })
  return result
}

// Read-only POST endpoints use analysis:view, including comparison and export.
export const monthlyAnalysisApi = {
  options: () => carbonRequest.get('/monthly-analysis/options', { silent: true, timeout: 60000 }),
  query: data => carbonRequest.post('/monthly-analysis/query', data, { timeout: 60000, silent: true }),
  compare: data => carbonRequest.post('/monthly-analysis/compare', data, { timeout: 60000, silent: true }),
  details: data => carbonRequest.post('/monthly-analysis/details', data, { timeout: 60000, silent: true }),
  export: data => carbonRequest.post('/monthly-analysis/export', data, { timeout: 120000, responseType: 'blob', silent: true })
}

// The carbon service is deployed both directly and behind a gateway.  Direct
// responses are arrays/trees, while older gateway routes may wrap them in a
// `data` or `rows` property.  Keep callers on one stable shape.
function unwrapArray(payload) {
  if (Array.isArray(payload)) return payload
  if (payload && Array.isArray(payload.data)) return payload.data
  if (payload && Array.isArray(payload.rows)) return payload.rows
  return []
}

function unwrapTree(payload) {
  if (payload && payload.data && !payload.children && !payload.nodeType && !payload.typeId) {
    return payload.data
  }
  return payload
}

function unwrapObject(payload) {
  if (payload && payload.data && !Array.isArray(payload.data)
    && typeof payload.data === 'object' && !payload.content && !payload.summary) {
    return payload.data
  }
  return payload
}

export function pickDefaultCalculationTemplate(templates, baselines) {
  const list = Array.isArray(templates) ? templates : []
  const availableIds = new Set(list.map(item => String(item.id)))
  const baseline = (Array.isArray(baselines) ? baselines : []).find(item =>
    item && item.templateId != null && availableIds.has(String(item.templateId))
  )
  if (baseline) return list.find(item => String(item.id) === String(baseline.templateId)) || null
  return list.find(item => Number(item.templateType) === 2 && item.enabled !== false) || null
}

export const templateApi = {
  list(config = {}) {
    return carbonRequest.get('/template/list', config).then(unwrapArray)
  },
  detail(id) {
    return carbonRequest.get(`/template/${id}`)
  },
  create(data) {
    return carbonRequest.post('/template/create', data)
  },
  update(id, data) {
    return carbonRequest.put(`/template/${id}`, data)
  },
  updateProperties(id, data) {
    return carbonRequest.put(`/template/${id}/properties`, data)
  },
  statisticsBaselines() {
    return carbonRequest.get('/template/statistics-baseline').then(unwrapArray)
  },
  copy(id, data) {
    return carbonRequest.post(`/template/copy/${id}`, data)
  },
  remove(id) {
    return carbonRequest.delete(`/template/${id}`)
  }
}

export const nodeApi = {
  tree(templateId, config = {}) {
    return carbonRequest.get('/nodes/tree', Object.assign({}, config, { params: cleanParams({ templateId }) })).then(unwrapTree)
  },
  detail(id) {
    return carbonRequest.get(`/nodes/${id}`)
  },
  create(data) {
    return carbonRequest.post('/nodes', data)
  },
  update(id, data) {
    return carbonRequest.put(`/nodes/${id}`, data)
  },
  remove(id) {
    return carbonRequest.delete(`/nodes/${id}`)
  },
  config(id) {
    return carbonRequest.get(`/nodes/${id}/config`)
  },
  updateConfig(id, data) {
    return carbonRequest.put(`/nodes/${id}/config`, data)
  },
  options() {
    return carbonRequest.get('/nodes/options')
  }
}

export const emissionApi = {
  create(data) {
    return carbonRequest.post('/emission-data', data)
  },
  batchCreate(data) {
    return carbonRequest.post('/emission-data/batch', data)
  },
  update(id, data) {
    return carbonRequest.put(`/emission-data/${id}`, data)
  },
  remove(id) {
    return carbonRequest.delete(`/emission-data/${id}`)
  },
  detail(id) {
    return carbonRequest.get(`/emission-data/${id}`)
  },
  query(params, config = {}) {
    return carbonRequest.get('/emission-data/query', Object.assign({}, config, { params: cleanParams(params) })).then(unwrapObject)
  },
  statistics(params) {
    const config = { params: cleanParams(params) }
    // Older carbon jars exposed the same dashboard payload only at /dashboard.
    // Keep the canonical endpoint first, then use the compatible alias on 404.
    return carbonRequest.get('/emission-data/statistics', config).then(unwrapObject).catch(error => {
      if (error && error.response && [404, 405].includes(error.response.status)) {
        return carbonRequest.get('/emission-data/dashboard', config).then(unwrapObject)
      }
      return Promise.reject(error)
    })
  },
  submit(id, data) {
    return carbonRequest.post(`/emission-data/${id}/submit`, data)
  },
  approve(id, data) {
    return carbonRequest.post(`/emission-data/${id}/approve`, data)
  },
  reject(id, data) {
    return carbonRequest.post(`/emission-data/${id}/reject`, data)
  },
  lock(id, data) {
    return carbonRequest.post(`/emission-data/${id}/lock`, data)
  },
  voidEntry(id, data) {
    return carbonRequest.post(`/emission-data/${id}/void`, data)
  },
  audits(id) {
    return carbonRequest.get(`/emission-data/${id}/audits`)
  },
  totalEmission(nodeId, params) {
    return carbonRequest.get(`/emission-data/${nodeId}/total-emission`, { params: cleanParams(params) })
  },
  averageQuality(nodeId, params) {
    return carbonRequest.get(`/emission-data/${nodeId}/average-quality`, { params: cleanParams(params) })
  },
  monthlyStatistics(nodeId) {
    return carbonRequest.get(`/emission-data/${nodeId}/monthly-statistics`)
  }
}

// 物理采集点树和人工采集记录，和“能耗数据采集点设置”使用同一套数据源。
export const collectionApi = {
  async trees(templateId, config = {}) {
    const requests = [
      carbonRequest.get('/meter-settings/tree', config),
      carbonRequest.get('/fossil-fuel-collection/tree', config),
      carbonRequest.get('/purchased-heat-collection/tree', config),
      templateId
        ? carbonRequest.get('/nodes/tree', Object.assign({}, config, { params: { templateId } }))
        : Promise.resolve(null)
    ]
    const settled = await Promise.allSettled(requests)
    const warnings = []
    const values = settled.map((item, index) => {
      if (item.status === 'fulfilled') return index === 3 ? unwrapTree(item.value) : unwrapTree(item.value)
      warnings.push({ index, error: item.reason })
      return null
    })
    const [electricity, fossil, heat, templateTree] = values
    if (!electricity && !fossil && !heat) {
      const error = warnings[0] && warnings[0].error
      throw error || new Error('采集点树为空，请检查碳排放模型服务和采集点数据')
    }
    const linkedNodes = new Map()
    const collectLinkedNodes = node => {
      if (!node) return
      const nodeConfig = node.config || {}
      if (Number(node.typeId) === 3 && nodeConfig.collectionPointType && nodeConfig.collectionPointId) {
        const key = `${nodeConfig.collectionPointType}:${nodeConfig.collectionPointId}`
        linkedNodes.set(key, linkedNodes.has(key) ? null : node.id)
      }
      ;(node.children || []).forEach(collectLinkedNodes)
    }
    collectLinkedNodes(templateTree)
    const annotate = (node, type, rootKey) => {
      if (!node) return null
      const result = Object.assign({}, node, {
        id: `${rootKey}:${node.id}`,
        sourceId: node.id,
        collectionPointType: node.nodeType === 'meter' ? type : null,
        collectionPointId: node.nodeType === 'meter' ? node.id : null,
        sourceType: rootKey,
        children: (node.children || []).map(child => annotate(child, type, rootKey))
      })
      if (result.nodeType === 'meter') {
        result.id = `${rootKey}:meter:${node.id}`
        result.collectionPointId = node.id
        result.emissionNodeId = linkedNodes.get(`${type}:${node.id}`) || null
      }
      return result
    }
    const result = [
      annotate(electricity, 1, 'electricity'),
      annotate(fossil, 2, 'fossil'),
      annotate(heat, 3, 'heat')
    ].filter(Boolean)
    // Non-enumerable keeps the return value backwards compatible with callers
    // that expect a plain array while allowing the entry page to show a useful
    // warning when one optional source is unavailable.
    Object.defineProperty(result, 'warnings', { value: warnings, enumerable: false })
    return result
  },
  manual(data) {
    return carbonRequest.post('/collection-records/manual', data)
  },
  pending(type, id, config = {}) {
    return carbonRequest.get('/collection-records/pending', Object.assign({}, config, { params: cleanParams({ collectionPointType: type, collectionPointId: id }) }))
  },
  approve(id, data) {
    return carbonRequest.post(`/collection-records/${id}/approve`, data || {})
  },
  reject(id, data) {
    return carbonRequest.post(`/collection-records/${id}/reject`, data || {})
  },
  voidRecord(id, data) {
    return carbonRequest.post(`/collection-records/${id}/void`, data || {})
  },
  latest(type, id) {
    return carbonRequest.get(`/collection-records/latest/${type}/${id}`)
  },
  factor(nodeId, type, id, config = {}) {
    return carbonRequest.get('/collection-records/factor', Object.assign({}, config, {
      params: cleanParams({ nodeId, collectionPointType: type, collectionPointId: id })
    }))
  },
  audits(id) {
    return carbonRequest.get(`/collection-records/${id}/audits`)
  }
}

export const calcSummaryApi = {
  tasks(params) {
    return carbonRequest.get('/calc-summary/tasks', { params: cleanParams(params) }).then(unwrapObject)
  },
  details(taskId, params) {
    return carbonRequest.get(`/calc-summary/by-template/${taskId}/page`, { params: cleanParams(params) }).then(unwrapObject)
  },
  voidTask(taskId) {
    return carbonRequest.post(`/calc-summary/tasks/${taskId}/void`)
  },
  exportExcel(params) {
    return carbonRequest.get('/calc-summary/export', { params: cleanParams(params), responseType: 'blob', timeout: 120000 })
  }
}

export function defaultCarbonOptions() {
  return {
    locomotiveTypes: ['HXN3型内燃机车', '国能八轴交流机车', '国能十二轴交流机车'],
    statisticalCalibers: ['生产排放', '生产辅助排放', '附属办公排放'],
    emissionCategories: ['购入的电力', '购入的热力', '化石燃料', '废弃物处理'],
    emissionSubcategories: {
      '购入的电力': ['生产设施用电', '辅助生产系统用电', '附属生产系统用电'],
      '购入的热力': ['热力数据', '质量单位计量的热水', '质量单位计量的蒸汽'],
      '化石燃料': ['汽油', '柴油', '原油', '燃料油', '天然气'],
      '废弃物处理': ['固体废弃物处理排放', '废水处理排放']
    },
    dataSources: ['手工录入', '数据库', 'API输入']
  }
}

export function normalizeCarbonOptions(options) {
  const defaults = defaultCarbonOptions()
  const result = Object.assign({}, defaults, options || {})
  Object.keys(result).forEach(key => {
    if (key !== 'emissionSubcategories' && !Array.isArray(result[key])) {
      result[key] = Array.from(result[key] || [])
    }
  })
  result.emissionSubcategories = result.emissionSubcategories || defaults.emissionSubcategories
  return result
}

export function flattenCarbonTree(tree) {
  const list = []
  const walk = (node, level) => {
    if (!node) return
    list.push(Object.assign({}, node, { level }))
    ;(node.children || []).forEach(child => walk(child, level + 1))
  }
  walk(tree, 0)
  return list
}
