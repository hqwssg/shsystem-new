import { ModuleTypeEnum } from '@/enums/httpEnum'

// 接口白名单（免登录）
export const fetchAllowList = [
  // 登录
  `${ModuleTypeEnum.SYSTEM}/login`,
  // 获取 OSS 接口
  `${ModuleTypeEnum.SYSTEM}/getOssInfo`,
  // 预览获取数据
  `${ModuleTypeEnum.PROJECT}/getData`,
  '/carbon-screen/carbon/screen/dashboard',
]

// 接口黑名单
export const fetchBlockList = []