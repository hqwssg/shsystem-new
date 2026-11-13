import { createRouter, createWebHistory } from 'vue-router'


/* Layout */
const Layout = () => import('@/layout')
import { getCarbonModulePermissions } from '@/utils/carbonAccess'

/**
 * Note: 路由配置项
 *
 * hidden: true                     // 当设置 true 的时候该路由不会再侧边栏出现 如401，login等页面，或者如一些编辑页面/edit/1
 * alwaysShow: true                 // 当你一个路由下面的 children 声明的路由大于1个时，自动会变成嵌套的模式--如组件页面
 *                                  // 只有一个时，会将那个子路由当做根路由显示在侧边栏--如引导页面
 *                                  // 若你想不管路由下面的 children 声明的个数都显示你的根路由
 *                                  // 你可以设置 alwaysShow: true，这样它就会忽略之前定义的规则，一直显示根路由
 * redirect: noRedirect             // 当设置 noRedirect 的时候该路由在面包屑导航中不可被点击
 * name:'router-name'               // 设定路由的名字，一定要填写不然使用<keep-alive>时会出现各种问题
 * query: '{"id": 1, "name": "ry"}' // 访问路由的默认传递参数
 * roles: ['admin', 'common']       // 访问路由的角色权限
 * permissions: ['a:a:a', 'b:b:b']  // 访问路由的菜单权限
 * meta : {
    noCache: true                   // 如果设置为true，则不会被 <keep-alive> 缓存(默认 false)
    title: 'title'                  // 设置该路由在侧边栏和面包屑中展示的名字
    icon: 'svg-name'                // 设置该路由的图标，对应路径src/assets/icons/svg
    breadcrumb: false               // 如果设置为false，则不会在breadcrumb面包屑中显示
    activeMenu: '/system/user'      // 当路由设置了该属性，则会高亮相对应的侧边栏。
  }
 */

// 公共路由
export const constantRoutes = [
  {
    path: '/redirect',
    component: Layout,
    hidden: true,
    children: [
      {
        path: '/redirect/:path(.*)',
        component: () => import('@/views/redirect')
      }
    ]
  },
  {
    path: '/login',
    component: () => import('@/views/login'),
    hidden: true
  },
  {
    path: '/register',
    component: () => import('@/views/register'),
    hidden: true
  },
  {
    path: '/404',
    component: () => import('@/views/error/404'),
    hidden: true
  },
  {
    path: '/401',
    component: () => import('@/views/error/401'),
    hidden: true
  },
  {
    path: '',
    component: Layout,
    redirect: 'index',
    children: [
      {
        path: 'index',
        component: () => import('@/views/index'),
        name: 'Index',
        meta: { title: '首页', icon: 'dashboard', affix: true, plain: true }
      }
    ]
  },
  {
    path: '/carbon',
    component: Layout,
    redirect: '/carbon/index',
    name: 'Carbon',
    hidden: true,
    meta: { title: '碳排放管理', icon: 'dashboard' },
    children: [
      {
        path: 'index',
        component: () => import('@/views/carbon/index'),
        name: 'CarbonIndex',
        meta: { title: '碳排放首页', icon: 'dashboard', plain: true }
      },
      {
        path: 'model',
        component: () => import('@/views/carbon/model'),
        name: 'CarbonModel',
        meta: { title: '碳排放模型设置', icon: 'tree', permissions: getCarbonModulePermissions('model') }
      },
      {
        path: 'params',
        component: () => import('@/views/carbon/params'),
        name: 'CarbonParams',
        meta: { title: '碳排放核算参数设置', icon: 'component', permissions: getCarbonModulePermissions('params') }
      },
      {
        path: 'screen',
        component: () => import('@/views/carbon/screen'),
        name: 'CarbonScreen',
        meta: { title: '碳排放大屏展示', icon: 'chart', permissions: getCarbonModulePermissions('screen') }
      },
      {
        path: 'data-entry',
        component: () => import('@/views/carbon/data-entry'),
        name: 'CarbonDataEntry',
        meta: { title: '人工数据录入', icon: 'edit', permissions: getCarbonModulePermissions('dataEntry') }
      },
      {
        path: 'statistics',
        component: () => import('@/views/carbon/statistics'),
        name: 'CarbonStatistics',
        meta: { title: '统计查询', icon: 'form', permissions: getCarbonModulePermissions('statistics') }
      },
      {
        path: 'energy-analysis',
        component: () => import('@/views/carbon/energyAnalysis'),
        name: 'CarbonEnergyAnalysis',
        meta: { title: '能耗统计分析', icon: 'chart', permissions: getCarbonModulePermissions('analysis') }
      },
      {
        path: 'report',
        component: () => import('@/views/carbon/report/index'),
        name: 'CarbonReport',
        meta: { title: '碳排放报告生成', icon: 'documentation', permissions: getCarbonModulePermissions('report') }
      },
      {
        path: 'uncertainty',
        component: () => import('@/views/carbon/uncertainty'),
        name: 'CarbonUncertainty',
        meta: { title: '碳排放报告不确定性分析', icon: 'data-analysis', permissions: getCarbonModulePermissions('uncertainty') }
      },
      {
        path: 'prediction',
        component: () => import('@/views/carbon/prediction'),
        name: 'CarbonPrediction',
        meta: { title: '碳排放趋势预测', icon: 'data-line', permissions: getCarbonModulePermissions('prediction') }
      },
      {
        path: 'energy',
        component: () => import('@/views/carbon/energy/index'),
        name: 'CarbonEnergy',
        meta: { title: '重空协同与能量优化', icon: 'chart', permissions: getCarbonModulePermissions('energy') }
      },
      {
        path: 'single-train',
        component: () => import('@/views/carbon/singleTrain/index'),
        name: 'CarbonSingleTrain',
        meta: { title: '单列车能量回收', icon: 'chart', permissions: getCarbonModulePermissions('singleTrain') }
      },
      {
        path: 'single-train/versions',
        component: () => import('@/views/carbon/singleTrain/versions'),
        name: 'CarbonSingleTrainVersions', hidden: true,
        meta: { title: '单列车数据维护', activeMenu: '/carbon/single-train', permissions: ['carbon:singleTrain:version'] }
      },
      {
        path: 'single-train/create',
        component: () => import('@/views/carbon/singleTrain/create'),
        name: 'CarbonSingleTrainCreate', hidden: true,
        meta: { title: '新建回收任务', activeMenu: '/carbon/single-train', permissions: ['carbon:singleTrain:run'] }
      },
      {
        path: 'single-train/runs/:runId',
        component: () => import('@/views/carbon/singleTrain/run'),
        name: 'CarbonSingleTrainRun', hidden: true,
        meta: { title: '回收任务结果', activeMenu: '/carbon/single-train', permissions: ['carbon:singleTrain:query'] }
      },
      {
        path: 'energy/versions',
        hidden: true,
        component: () => import('@/views/carbon/energy/versions'),
        name: 'CarbonEnergyVersions',
        meta: { title: '能量数据版本', activeMenu: '/carbon/energy', permissions: getCarbonModulePermissions('energy') }
      },
      {
        path: 'energy/create',
        hidden: true,
        component: () => import('@/views/carbon/energy/create'),
        name: 'CarbonEnergyCreate',
        meta: { title: '新建能量任务', activeMenu: '/carbon/energy', permissions: getCarbonModulePermissions('energy') }
      },
      {
        path: 'energy/runs/:runId',
        hidden: true,
        component: () => import('@/views/carbon/energy/run'),
        name: 'CarbonEnergyRun',
        meta: { title: '能量任务详情', activeMenu: '/carbon/energy', permissions: getCarbonModulePermissions('energy') }
      },
      {
        path: 'report/create',
        hidden: true,
        component: () => import('@/views/carbon/report/create'),
        name: 'CarbonReportCreate',
        meta: { title: '新建碳排放报告', icon: 'documentation', activeMenu: '/carbon/report', permissions: getCarbonModulePermissions('report') }
      },
      {
        path: 'report/edit/:id(\\d+)',
        hidden: true,
        component: () => import('@/views/carbon/report/edit'),
        name: 'CarbonReportEdit',
        meta: { title: '填报碳排放报告', icon: 'edit', activeMenu: '/carbon/report', permissions: getCarbonModulePermissions('report') }
      },
      {
        path: 'report/query',
        hidden: true,
        component: () => import('@/views/carbon/report/query'),
        name: 'CarbonReportQuery',
        meta: { title: '核算结果查询', icon: 'search', activeMenu: '/carbon/statistics', permissions: getCarbonModulePermissions('statistics') }
      },
      {
        path: 'system',
        component: () => import('@/views/carbon/system'),
          name: 'CarbonSystem',
          meta: { title: '系统管理', icon: 'system', permissions: getCarbonModulePermissions('system') }
        },
        {
          path: 'scopes',
          component: () => import('@/views/carbon/scopes'),
          name: 'CarbonScopes',
          meta: { title: '采集范围分配', icon: 'tree', permissions: ['carbon:scope:view'] }
        },
      {
        path: 'logs',
        component: () => import('@/views/carbon/logs'),
        name: 'CarbonLogs',
        meta: { title: '日志审计', icon: 'log', permissions: getCarbonModulePermissions('logs') }
      }
    ]
  },
  {
    path: '/lock',
    component: () => import('@/views/lock'),
    hidden: true,
    meta: { title: '锁定屏幕' }
  },
  {
    path: '/user',
    component: Layout,
    hidden: true,
    redirect: 'noredirect',
    children: [
      {
        path: 'profile',
        component: () => import('@/views/system/user/profile/index'),
        name: 'Profile',
        meta: { title: '个人中心', icon: 'user' }
      }
    ]
  }
]

// 动态路由，基于用户权限动态去加载
export const dynamicRoutes = [
  {
    path: '/system/user-auth',
    component: Layout,
    hidden: true,
    permissions: ['system:user:edit'],
    children: [
      {
        path: 'role/:userId(\\d+)',
        component: () => import('@/views/system/user/authRole'),
        name: 'AuthRole',
        meta: { title: '分配角色', activeMenu: '/system/user' }
      }
    ]
  },
  {
    path: '/system/role-auth',
    component: Layout,
    hidden: true,
    permissions: ['system:role:edit'],
    children: [
      {
        path: 'user/:roleId(\\d+)',
        component: () => import('@/views/system/role/authUser'),
        name: 'AuthUser',
        meta: { title: '分配用户', activeMenu: '/system/role' }
      }
    ]
  },
  {
    path: '/system/dict-data',
    component: Layout,
    hidden: true,
    permissions: ['system:dict:list'],
    children: [
      {
        path: 'index/:dictId(\\d+)',
        component: () => import('@/views/system/dict/data'),
        name: 'Data',
        meta: { title: '字典数据', activeMenu: '/system/dict' }
      }
    ]
  },
  {
    path: '/monitor/job-log',
    component: Layout,
    hidden: true,
    permissions: ['monitor:job:list'],
    children: [
      {
        path: 'index/:jobId(\\d+)',
        component: () => import('@/views/monitor/job/log'),
        name: 'JobLog',
        meta: { title: '调度日志', activeMenu: '/monitor/job' }
      }
    ]
  },
  {
    path: '/tool/gen-edit',
    component: Layout,
    hidden: true,
    permissions: ['tool:gen:edit'],
    children: [
      {
        path: 'index/:tableId(\\d+)',
        component: () => import('@/views/tool/gen/editTable'),
        name: 'GenEdit',
        meta: { title: '修改生成配置', activeMenu: '/tool/gen' }
      }
    ]
  }
]


export function normalizeRoute(route) {
  return { ...route, meta: { ...route.meta, ...(route.permissions ? { permissions: route.permissions } : {}), ...(route.roles ? { roles: route.roles } : {}) },
    ...(route.children ? { children: route.children.filter(isInternalRoute).map(normalizeRoute) } : {}) }
}
const isInternalRoute = route => !/^(https?:|mailto:|tel:)/i.test(route.path || '')
const router = createRouter({ history: createWebHistory(import.meta.env.BASE_URL),
  scrollBehavior: () => ({ top: 0 }), routes: constantRoutes.map(normalizeRoute) })
const removeDynamicRoutes = []
export function addDynamicRoutes(routes) {
  routes.filter(isInternalRoute).forEach(route => removeDynamicRoutes.push(router.addRoute(normalizeRoute(route))))
}
export function resetRouter() {
  removeDynamicRoutes.splice(0).forEach(remove => remove())
}
export default router
