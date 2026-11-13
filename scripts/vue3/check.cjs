const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm')
const assert = require('node:assert/strict'), { createRequire } = require('node:module')
const root = path.resolve(__dirname, '../..'), ui = path.join(root, 'ruoyi-ui')
const uiRequire = createRequire(path.join(ui, 'package.json'))
const { parse, compileScript, compileTemplate } = uiRequire('@vue/compiler-sfc')
const { parse: parseDom } = uiRequire('@vue/compiler-dom')
const esbuild = uiRequire('esbuild')
function load(file) {
  const result = esbuild.buildSync({ entryPoints: [path.join(ui, 'src', file)], bundle: true, write: false, platform: 'node', format: 'cjs', packages: 'external', alias: { '@': path.join(ui, 'src') } })
  const context = { module: { exports: {} }, exports: {}, require: uiRequire }
  vm.runInNewContext(result.outputFiles[0].text, context)
  return context.module.exports
}
function compileSfc(source, filename) {
  const { descriptor, errors } = parse(source, { filename })
  assert.deepEqual(errors, [], filename)
  let bindings = {}
  if (descriptor.script || descriptor.scriptSetup) bindings = compileScript(descriptor, { id: filename }).bindings
  if (descriptor.template) {
    assert.deepEqual(compileTemplate({ source: descriptor.template.content, filename, id: filename, compilerOptions: { bindingMetadata: bindings } }).errors, [], filename)
    function walk(node) {
      if (node.type === 1) for (const prop of node.props) {
        if (/^el-(select|input|input-number|switch|slider|rate|date-picker|time-picker)$/.test(node.tag)) assert.ok(!(prop.type === 7 && prop.name === 'bind' && prop.arg?.content === 'value'), `old controlled-value binding in ${filename}`)
        if (prop.type === 6 && ['value-format', 'format'].includes(prop.name)) assert.ok(!/yyyy|dd/.test(prop.value?.content || ''), `old date format in ${filename}`)
      }
      for (const child of node.children || []) walk(child)
    }
    walk(parseDom(descriptor.template.content))
  }
}
let count = 0
function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const file = path.join(dir, entry.name)
    if (entry.isDirectory()) walk(file)
    else if (file.endsWith('.vue')) { compileSfc(fs.readFileSync(file, 'utf8'), file); count++ }
  }
}
for (const project of ['ruoyi-ui', 'tpfhs-9/frontend']) {
  const p = path.join(root, project), manifest = JSON.parse(fs.readFileSync(path.join(p, 'package.json'))), lock = JSON.parse(fs.readFileSync(path.join(p, 'package-lock.json')))
  for (const [name, version] of Object.entries({ vue: '3.5.34', 'element-plus': '2.13.7', axios: '1.16.0', echarts: '^5.5.1', 'vue-router': '^4.4.5', '@element-plus/icons-vue': '^2.3.1' })) assert.equal(manifest.dependencies[name], version, `${project}/${name}`)
  for (const [name, version] of Object.entries({ '@vue/compiler-sfc': '3.5.34', '@vitejs/plugin-vue': '^5.0.4', vite: '^5.2.8' })) assert.equal(manifest.devDependencies[name], version)
  assert.equal(lock.packages['node_modules/vue'].version, '3.5.34')
  assert.equal(lock.packages['node_modules/@vue/compiler-sfc'].version, '3.5.34')
  for (const [name, entry] of Object.entries(lock.packages)) {
    assert.ok(!/(^|\/)node_modules\/(?:vue-template-compiler|@vue\/compat|element-ui|@vue\/cli-service)$/.test(name), name)
    if (/(^|\/)node_modules\/vue$/.test(name)) assert.ok(entry.version.startsWith('3.'), name)
  }
  walk(path.join(p, 'src'))
}
const routePath = load('utils/routePath.js').default
for (const parts of [['/system', 'user'], ['/system/user', '../menu'], ['/one', '/two'], ['/a', '.', 'b']]) assert.equal(routePath.resolve(...parts), path.posix.resolve(...parts))
const { inputComponents, selectComponents, layoutComponents, formConf } = load('utils/generator/config.js')
const { makeUpHtml, vueTemplate, vueScript } = load('utils/generator/html.js'), { makeUpJs } = load('utils/generator/js.js')
const fields = [...inputComponents, ...selectComponents, ...layoutComponents.filter(x => x.tag)].map((x, i) => ({ ...x, span: x.span || 24, layout: x.layout || 'colFormItem', vModel: `field${i}` }))
for (const type of ['file', 'dialog']) {
  const conf = { ...formConf, fields }, html = makeUpHtml(conf, type), js = makeUpJs(conf, type)
  assert.ok(!html.includes('$listeners') && !html.includes('slot="'))
  compileSfc(vueTemplate(html) + '\n' + vueScript(js), `Generated-${type}.vue`)
}
// Element Plus still passes h as the first tree render-content argument.
const panel = parse(fs.readFileSync(path.join(ui, 'src/views/tool/build/RightPanel.vue'), 'utf8')).descriptor.script.content
const method = panel.slice(panel.indexOf('    renderContent('), panel.indexOf('    append(data)'))
const transformed = uiRequire('@babel/core').transformSync('export default {\n' + method + '\n}', { configFile: false, babelrc: false, plugins: [uiRequire('@vue/babel-plugin-jsx')] }).code
const renderedModule = { exports: {} }
vm.runInNewContext(esbuild.transformSync(transformed, { format: 'cjs' }).code, { module: renderedModule, require: uiRequire, Plus: {}, Delete: {} })
let selected, vnode
const data = { id: 7 }, Vue = uiRequire('vue')
Vue.createRenderer({ createComment: () => ({}), insert() {} }).createApp({
  components: { ElIcon: { render: () => null }, Plus: { render: () => null }, Delete: { render: () => null } },
  render() { vnode = renderedModule.exports.default.renderContent.call({ append: x => { selected = x }, remove() {} }, Vue.h, { node: { label: '树选项' }, data }); return null }
}).mount({})
assert.equal([].concat(vnode.children[0].children).join(''), '树选项')
vnode.children[1].children[0].props.onClick()
assert.equal(selected, data)
console.log(`PASS: ${count} Vue 3 components, locked dependencies/no Vue 2 runtime, route resolution and generated Vue 3 forms`)
