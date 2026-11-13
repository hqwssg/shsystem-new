import hasRole from './permission/hasRole'
import hasPermi from './permission/hasPermi'
import clipboard from './module/clipboard'

const install = function(app) {
  app.directive('hasRole', hasRole)
  app.directive('hasPermi', hasPermi)
  app.directive('clipboard', clipboard)
}

export default install
