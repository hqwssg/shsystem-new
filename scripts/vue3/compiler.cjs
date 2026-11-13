const { parse, compileTemplate, compileScript } = require('../../ruoyi-ui/node_modules/@vue/compiler-sfc')

// Shared Vue 3 compiler entry for the existing frontend business regression checks.
function parseComponent(source) {
  const result = parse(source)
  if (result.errors.length) throw new Error(result.errors.join('\n'))
  return result.descriptor
}
function compile(source) {
  return compileTemplate({ source, filename: 'Regression.vue', id: 'regression' })
}
module.exports = { parseComponent, compile, compileScript }
