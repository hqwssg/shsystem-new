import { PublicConfigClass } from '@/packages/public'
import { cloneDeep } from 'lodash'
import { ManagementStatusConfig } from './index'
export default class Config extends PublicConfigClass {
  public key = ManagementStatusConfig.key
  public chartConfig = cloneDeep(ManagementStatusConfig)
  public option = { mode: 'coverage', dataMode: 'real' }
}
