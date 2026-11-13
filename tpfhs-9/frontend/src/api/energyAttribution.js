import axios from 'axios'

export const energyAttributionApi = {
  listStations(params = {}) {
    return axios.get('/api/energy-attribution-stations', { params }).then(response => response.data || [])
  },
  createStation(data) {
    return axios.post('/api/energy-attribution-stations', data).then(response => response.data)
  },
  updateStation(id, data) {
    return axios.put(`/api/energy-attribution-stations/${id}`, data).then(response => response.data)
  },
  deleteStation(id) {
    return axios.delete(`/api/energy-attribution-stations/${id}`).then(response => response.data)
  },
  listDict(code) {
    return axios.get(`/api/data-dict/items/${code}`).then(response => response.data || [])
  }
}
