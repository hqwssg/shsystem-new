import axiosInstance from '@/api/axios'

const DASHBOARD_URL = '/carbon-screen/carbon/screen/dashboard'

export function requestDashboard(params: Record<string, string> = {}, signal?: AbortSignal) {
  return axiosInstance<any>({
    url: DASHBOARD_URL,
    method: 'get',
    params,
    signal,
    baseURL: ''
  })
}
