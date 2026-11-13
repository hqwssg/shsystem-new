import { ConfigType, PackagesCategoryEnum, ChartFrameEnum } from '@/packages/index.d'
export const ManagementStatusConfig: ConfigType = {
  key: 'ManagementStatus', chartKey: 'VManagementStatus', conKey: 'VCManagementStatus',
  title: '能碳管理筛选与覆盖', category: 'Mores', categoryName: '更多',
  package: PackagesCategoryEnum.INFORMATIONS, chartFrame: ChartFrameEnum.COMMON, image: 'table.png'
}
