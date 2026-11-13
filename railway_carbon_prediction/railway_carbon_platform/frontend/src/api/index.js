import http from './http'

export const getMeta = () => http.get('/meta/all')
export const getOrgs = () => http.get('/meta/orgs')
export const getVars = () => http.get('/meta/vars')

export const getActivity = (params) => http.get('/activity', { params })
export const ingestActivity = (data) => http.post('/activity/ingest', data)

export const getFactors = (params) => http.get('/factors', { params })
export const saveFactor = (data) => http.post('/factors', data)

export const getCaliberRules = (params) => http.get('/caliber-rules', { params })
export const saveCaliberRule = (data) => http.post('/caliber-rules', data)

export const getPolicyFactors = (params) => http.get('/policy-factors', { params })
export const savePolicyFactors = (data) => http.post('/policy-factors', data)

export const getCalendarEvents = () => http.get('/calendar-events')
export const saveCalendarEvent = (data) => http.post('/calendar-events', data)
export const deleteCalendarEvent = (id) => http.delete(`/calendar-events/${id}`)

export const getAnomalies = (params) => http.get('/anomalies', { params })
export const getAnomaly = (id, params) => http.get(`/anomalies/${id}`, { params })
export const reviewAnomaly = (id, data) => http.post(`/anomalies/${id}/review`, data)

export const getModels = (params) => http.get('/models', { params })
export const getModel = (id) => http.get(`/models/${id}`)
export const deleteModel = (id, operator = 'platform') => http.delete(`/models/${id}`, { params: { operator } })
export const getJobs = (params) => http.get('/jobs', { params })
export const getJob = (id) => http.get(`/jobs/${id}`)
export const trainModels = (data) => http.post('/models/train', data)

export const getForecast = (params) => http.get('/forecast', { params })
export const getHistory = (params) => http.get('/history', { params })
export const generateForecast = (data) => http.post('/forecast/generate', data)
export const getDashboard = () => http.get('/dashboard')
export const getApiInfo = () => http.get('/api-info')
