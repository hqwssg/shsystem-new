const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path'), vm = require('node:vm'), http = require('node:http')
const root = path.resolve(__dirname, '../..'), axios = require(path.join(root, 'ruoyi-ui/node_modules/axios/dist/node/axios.cjs'))
const messages = [], cacheValues = new Map()
const message = Object.assign(value => messages.push(value), { error: value => messages.push(value) })
let source = fs.readFileSync(path.join(root, 'ruoyi-ui/src/utils/request.js'), 'utf8').replace(/^import .*$/gm, '').replaceAll('import.meta.env.VUE_APP_BASE_API', "''").replace(/export (let|function) /g, '$1 ').replace('export default service', 'module.exports = service')
const context = { module: { exports: {} }, axios, FormData, Blob, console: { log() {}, warn() {}, error() {} }, Message: message, Notification: { error: message }, MessageBox: { confirm: async () => {} }, Loading: {}, store: { dispatch: async () => {} }, getToken: () => 'migration-test', errorCode: { default: 'test' }, tansParams: params => new URLSearchParams(params).toString() + '&', cache: { session: { getJSON: key => cacheValues.get(key), setJSON: (key, value) => cacheValues.set(key, value) } }, saveAs() {} }
vm.runInNewContext(source, context)
const service = context.module.exports
async function main() {
  const requests = []
  const server = http.createServer((req, res) => { const chunks = []; req.on('data', c => chunks.push(c)); req.on('end', () => { requests.push({ url: req.url, headers: req.headers, body: Buffer.concat(chunks).toString() }); res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(req.url === '/failure' ? { code: 500, msg: 'expected failure' } : { code: 200, data: 'ok' })) }) })
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  try {
    service.defaults.baseURL = `http://127.0.0.1:${server.address().port}`
    const data = new FormData(); data.append('file', new Blob(['Vue3 multipart regression']), 'test.txt')
    await service.post('/upload', data)
    assert.match(requests[0].headers['content-type'], /^multipart\/form-data; boundary=/)
    assert.ok(requests[0].body.includes('Vue3 multipart regression'))
    assert.equal(requests[0].headers.authorization, 'Bearer migration-test')
    await service.get('/query', { params: { year: 2025, name: '机辆' }, headers: { isToken: false } })
    assert.equal(new URL('http://local' + requests[1].url).searchParams.get('name'), '机辆')
    assert.equal(requests[1].headers.authorization, undefined)
    await service.post('/json', { quantity: 0 })
    assert.match(requests[2].headers['content-type'], /^application\/json/)
    assert.equal(JSON.parse(requests[2].body).quantity, 0)
    const before = messages.length
    await assert.rejects(service.get('/failure', { errorMode: 'silent' }))
    if (source.includes("errorMode === 'silent'")) assert.equal(messages.length, before)
    console.log('PASS: Axios 1.16 real HTTP multipart boundary, JSON zero, authorization and query encoding' + (source.includes("errorMode === 'silent'") ? ', preserved local silent errors' : ''))
  } finally { await new Promise(resolve => server.close(resolve)) }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
