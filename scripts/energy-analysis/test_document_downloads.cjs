const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const root = path.resolve(__dirname, '../..')
const compiler = require('../vue3/compiler.cjs')
const source = fs.readFileSync(path.join(root, 'ruoyi-ui/src/views/carbon/energy/run.vue'), 'utf8')
const page = compiler.parseComponent(source)
assert.deepEqual(compiler.compile(page.template.content).errors, [])
let response = new Blob(['pdf bytes'], { type: 'application/pdf' })
const saved = [], errors = [], calls = []
const scope = { module: { exports: {} }, StoragePlanningResults: {},
  exportReport: async (...args) => { calls.push(args); return response },
  blobValidate: b => b.type !== 'application/json',
  saveAs: (blob, name) => saved.push({ blob, name }) }
vm.runInNewContext(page.script.content.replace(/^import .*$/gm, '').replace('export default', 'module.exports ='), scope)
const row = { relativePath: 'DISPATCH_CASE_REPORT.md', downloadName: '重空调度报告.md' }
const component = { exporting: '', run: { runId: 'original' }, $message: { error: m => errors.push(m) } }
async function main() {
  const download = scope.module.exports.methods.exportDocument
  await download.call(component, row, 'pdf')
  assert.equal(saved[0].name, '重空调度报告.pdf')
  assert.deepEqual(calls[0], ['original', row.relativePath, 'pdf'])
  assert.equal(component.exporting, '')
  assert.equal(component.run.runId, 'original')
  response = new Blob([JSON.stringify({ code: 500, msg: '中文字体组件未就绪' })], { type: 'application/json' })
  await download.call(component, row, 'docx')
  assert.equal(errors[0], '中文字体组件未就绪')
  assert.equal(saved.length, 1, 'Errors must never be saved as fake Word files')
  assert.equal(component.exporting, '')
  component.exporting = 'busy'
  await download.call(component, row, 'pdf')
  assert.equal(calls.length, 2, 'A duplicate click must not start another conversion')
  console.log('PASS: Word/PDF actions, Chinese names, source binding, error blobs and duplicate-click handling')
}
main().catch(error => { console.error(error); process.exitCode = 1 })
