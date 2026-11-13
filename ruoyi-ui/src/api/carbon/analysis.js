import request from '@/utils/request'

export function analysisOptions() {
  return request({ url: '/carbon/analysis/options', method: 'get' })
}

export function analysisQuery(params) {
  return request({ url: '/carbon/analysis/query', method: 'get', params })
}

export function analysisCompare(params) {
  return request({ url: '/carbon/analysis/compare', method: 'get', params })
}
