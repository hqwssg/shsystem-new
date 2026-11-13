import { createRouter, createWebHistory } from 'vue-router'
import AppLayout from '../layout/AppLayout.vue'

const routes = [
  {
    path: '/',
    component: AppLayout,
    redirect: '/data/history',
    children: [
      { path: 'data/history', component: () => import('../views/HistoryDataView.vue'), meta: { title: '历史数据浏览', group: '数据管理' } },
      { path: 'data/ingest', component: () => import('../views/DataIngestView.vue'), meta: { title: '新数据入库', group: '数据管理' } },
      { path: 'data/factors', component: () => import('../views/FactorManagement.vue'), meta: { title: '碳排放因子管理', group: '数据管理' } },
      { path: 'data/policy', component: () => import('../views/PolicyFactorManagement.vue'), meta: { title: '政策/外部因子月度数据', group: '数据管理' } },
      { path: 'data/calendar', component: () => import('../views/CalendarEventManagement.vue'), meta: { title: '大事件日历表管理', group: '数据管理' } },
      { path: 'anomaly/review', component: () => import('../views/AnomalyReview.vue'), meta: { title: '异常数据人工审核', group: '异常数据管理' } },
      { path: 'anomaly/history', component: () => import('../views/AnomalyHistory.vue'), meta: { title: '历史异常数据浏览', group: '异常数据管理' } },
      { path: 'model', component: () => import('../views/ModelManagement.vue'), meta: { title: '模型版本与训练', group: '模型管理' } },
      { path: 'forecast', component: () => import('../views/ForecastView.vue'), meta: { title: '预测结果与历史数据', group: '碳排放预测' } }
    ]
  }
]

const router = createRouter({
  history: createWebHistory('/prediction/'),
  routes
})

router.afterEach((to) => {
  document.title = `${to.meta?.title || '平台'} - 铁路碳排放趋势预测平台`
})

export default router
