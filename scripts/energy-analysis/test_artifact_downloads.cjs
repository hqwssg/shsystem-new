const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const root = path.resolve(__dirname, '../..')
const source = fs.readFileSync(path.join(root, 'ruoyi-ui/src/utils/energyArtifactNames.js'), 'utf8')
const scope = { reportNames: JSON.parse(fs.readFileSync(path.join(root, 'ruoyi-modules/ruoyi-energy/src/main/resources/energy-report-names.json'), 'utf8')) }
vm.createContext(scope)
vm.runInContext(source.replace(/^import .*$/gm, '').replace(/export /g, ''), scope)
const files = [
  'joint_parameter_scenarios.csv', 'joint_robustness_results.csv',
  'joint_robustness_summary.json', 'JOINT_PARAMETER_ROBUSTNESS_REPORT.md',
  'database_worker_stderr.txt', 'new_algorithm_output.parquet', 'figures/state.png'
].map(relativePath => ({ relativePath }))
const original = JSON.stringify(files)
const sorted = scope.sortEnergyArtifacts(files)
assert.equal(sorted.length, files.length, 'Unknown outputs and logs must not be filtered')
assert.equal(JSON.stringify(files), original, 'Sorting cannot mutate API data')
assert.equal(sorted[0].relativePath, 'JOINT_PARAMETER_ROBUSTNESS_REPORT.md')
assert.equal(scope.artifactDisplayName('joint_parameter_scenarios.csv'), '联合参数场景')
assert.equal(scope.artifactDisplayName('new_algorithm_output.parquet'), 'new_algorithm_output.parquet')
const report = `## 输入文件
- \`input.csv\`
## 输出文件
- \`joint_parameter_scenarios.csv\`
- \`joint_robustness_results.csv\`
- [汇总](joint_robustness_summary.json)
- \`missing.csv\` / \`missing.csv\`
- \`energy_flow_*.png\`
- [外部说明](https://example.invalid/guide.pdf)
### 图表
![状态](figures/state.png)
## 结论
\`not-an-output.json\`
`
const translated = scope.localizeEnergyReportFiles(report, files)
for (const name of ['joint_parameter_scenarios.csv', 'joint_robustness_results.csv', 'joint_robustness_summary.json']) {
  assert.ok(!translated.includes(name))
  assert.ok(translated.includes(scope.artifactDownloadName(name)), 'Report name must equal saved filename')
}
assert.equal(scope.localizeEnergyReportFiles('`summary.json` `audit_summary.json`', files), '`调度结果总览.json` `运行图审查总览.json`')
assert.equal(scope.localizeEnergyReportFiles('`./joint_robustness_results.csv`', files), '`联合稳健性结果.csv`')
assert.equal(scope.localizeEnergyReportFiles('https://example.invalid/?file=summary.json', files), 'https://example.invalid/?file=summary.json')
assert.equal(scope.localizeEnergyReportFiles('![状态](figures/state.png)', files), '![状态](示意图：state.png)')
assert.equal(scope.localizeEnergyReportFiles('`new_algorithm_output.parquet`', files), '`new_algorithm_output.parquet`')
assert.equal(scope.localizeEnergyReportFiles(translated, files), translated, 'Repeated rendering is idempotent')
const compiler = require('../vue3/compiler.cjs')
const page = compiler.parseComponent(fs.readFileSync(path.join(root, 'ruoyi-ui/src/views/carbon/energy/run.vue'), 'utf8'))
assert.deepEqual(compiler.compile(page.template.content).errors, [])
async function checkDownload() {
  let saved, content = new Blob([report])
  const context = { module: { exports: {} }, Blob, StoragePlanningResults: {},
    downloadArtifact: async () => content, blobValidate: () => true,
    localizeEnergyReportFiles: scope.localizeEnergyReportFiles,
    saveAs: (blob, name) => saved({ blob, name }) }
  vm.runInNewContext(page.script.content.replace(/^import .*$/gm, '').replace('export default', 'module.exports ='), context)
  const download = relativePath => new Promise((resolve, reject) => {
    saved = resolve
    context.module.exports.methods.download.call({ artifacts: files, run: { runId: 'test' }, $message: { error: reject } },
      { relativePath, downloadName: scope.artifactDownloadName(relativePath) })
  })
  const md = await download('JOINT_PARAMETER_ROBUSTNESS_REPORT.md')
  assert.equal(await md.blob.text(), translated, 'Downloaded Markdown and preview use the same mapping')
  assert.equal(md.name, scope.artifactDownloadName('JOINT_PARAMETER_ROBUSTNESS_REPORT.md'))
  content = new Blob(['original,csv'])
  const csv = await download('joint_robustness_results.csv')
  assert.equal(csv.blob, content, 'Other file contents must remain byte-identical')
  console.log('PASS: complete downloads, Chinese report/download filenames, Markdown download integration, unchanged CSV bytes, external URLs, idempotence and Vue compilation')
}
checkDownload().catch(error => { console.error(error); process.exitCode = 1 })
