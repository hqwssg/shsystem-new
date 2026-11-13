import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { readFileSync } from 'node:fs'
import { parseMonitoringWorkbook, mergeMonitoringRows, monitoringWarnings, readMonitoringFile } from '../../ruoyi-ui/src/views/carbon/report/steps/monitoringImport.js'
const require = createRequire(new URL('../../ruoyi-ui/package.json', import.meta.url))
const XLSX = require('xlsx')
const headers = ['名称', '型号', '精度', '量程', '安装位置', '检定周期']
const makeBook = rows => {
  const book = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(book, XLSX.utils.aoa_to_sheet([headers, ...rows]), '监测设备')
  return book
}
const same = ['牵引电表', 'DTZ188', '0', '1#进线', '神池南站', '每年']
const blankName = ['', 'DTZ188', '', '2#进线', '神池南站', '']
const long = ['设备', 'DTZ188', '', '测'.repeat(65), '', '']
const book = makeBook([same, same, blankName, [], long])
const parsed = parseMonitoringWorkbook(book)
assert.equal(parsed.rows.length, 4)
assert.equal(parsed.rows[0].accuracy, '0')
assert.equal(parsed.rows[2].name, '')
assert.equal(parsed.rows[3].measurementRange.length, 65)
const warnings = monitoringWarnings(parsed.rows)
assert.ok(warnings[0].messages.some(text => text.includes('相同')))
assert.equal(warnings[0].errors.length, 0)
assert.ok(warnings[2].messages.some(text => text.includes('名称未填写')))
assert.equal(warnings[2].errors.length, 0)
assert.equal(warnings[3].errors.length, 1)
parsed.rows[3].measurementRange = '测'.repeat(64)
assert.equal(monitoringWarnings(parsed.rows)[3].errors.length, 0)
assert.equal(mergeMonitoringRows(parsed.rows, parsed.rows, 'append').length, 8)
assert.equal(mergeMonitoringRows(parsed.rows, parsed.rows.slice(0, 2), 'overwrite').length, 2)
const merged = makeBook([['设备', 'DTZ188', '', '上半段', '站点', '每年'], ['', '', '', '下半段']])
merged.Sheets['监测设备']['!merges'] = [{ s: { r: 1, c: 0 }, e: { r: 2, c: 0 } }]
const continued = parseMonitoringWorkbook(merged)
assert.equal(continued.rows.length, 1)
assert.equal(continued.rows[0].measurementRange, '上半段\n下半段')
assert.equal(continued.mergedContinuationRows, 1)
const missing = XLSX.utils.book_new()
XLSX.utils.book_append_sheet(missing, XLSX.utils.aoa_to_sheet([['型号'], ['A']]), 'test')
assert.throws(() => parseMonitoringWorkbook(missing), /名称.*表头/)
const file = new File([XLSX.write(book, { type: 'buffer', bookType: 'xlsx' })], 'monitoring.xlsx')
assert.equal((await readMonitoringFile(file)).rows.length, 4)
await assert.rejects(() => readMonitoringFile(new File(['x'], 'bad.txt')), /只支持/)
if (process.argv[2]) {
  const actual = parseMonitoringWorkbook(XLSX.read(readFileSync(process.argv[2]), { type: 'buffer' }))
  assert.equal(actual.rows.length, 49)
  assert.equal(actual.rows[0].name, '牵引电表')
  assert.equal(actual.rows[1].name, '牵引电表')
  assert.equal(actual.mergedContinuationRows, 1)
  assert.ok(actual.rows.some(row => row.measurementRange.includes('站馈一）')))
  console.log('Supplied workbook passed: 49 device rows; duplicate names/rows preserved; merged continuation retained.')
}
console.log('Monitoring preview checks passed: duplicates, blank names, zero, length warnings and correction, append/overwrite, merges and malformed headers.')
