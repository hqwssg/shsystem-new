const fs = require('fs'), path = require('path'), vm = require('vm'), assert = require('assert');
const root = path.resolve(__dirname, '../..');
const Vue = require(path.join(root, 'ruoyi-ui/node_modules/vue'));
const compiler = require(path.join(root, 'ruoyi-ui/node_modules/vue-template-compiler'));
const parser = require(path.join(root, 'ruoyi-ui/node_modules/@babel/parser'));
const checks = [], pass = label => checks.push(label);
for (const name of ['create', 'index', 'edit', 'SubjectConfiguration', 'steps/AssetsStep', 'steps/ActivityStep']) {
  const c = compiler.parseComponent(fs.readFileSync(path.join(root, 'ruoyi-ui/src/views/carbon/report', name + '.vue'), 'utf8'));
  assert.deepStrictEqual(compiler.compile(c.template.content).errors, []);
  parser.parse(c.script.content, { sourceType: 'module' }); pass('syntax ' + name);
}
let subjects = [], calculations = [], saves = [], nodes = [];
const deferred = list => new Promise((resolve, reject) => list.push({ resolve, reject }));
let previews = [];
const box = { module: { exports: {} }, Date, Promise, SubjectConfiguration: {}, ExcelImportBox: {},
  prefillPreview: () => { previews.push(true); return Promise.resolve({ data: { gaps: [] } }); },
  listReportSubjects: () => deferred(subjects),
  listCalculations: params => { const p = deferred(calculations); calculations.at(-1).params = params; return p; },
  createTask: body => { const p = deferred(saves); saves.at(-1).body = body; return p; },
  listReportSubjectNodes: () => deferred(nodes), saveReportSubject: () => Promise.resolve({}) };
function component(name) {
  const src = compiler.parseComponent(fs.readFileSync(path.join(root, 'ruoyi-ui/src/views/carbon/report', name + '.vue'), 'utf8')).script.content;
  vm.runInNewContext(src.replace(/^import .*$/gm, '').replace('export default', 'module.exports ='), box);
  return box.module.exports;
}
const page = component('create');
const configured = [{ deptId: 303, configured: true, subjectNodeId: 3171, subjectName: '机辆', deptName: '机辆' }, { deptId: 301, configured: true, subjectNodeId: 3, subjectName: '肃宁', deptName: '肃宁' }];
function setup() {
  subjects = []; calculations = []; saves = [];
  const c = new Vue({ ...page, created: undefined, data() { const d = page.data(); d.subjects = configured; d.form.deptId = 303; return d; } });
  c.$message = { warning() {} }; c.$router = { push() {} }; return c;
}
(async () => {
  let c = setup(); let p = c.loadSubjects(); subjects[0].resolve({ data: configured }); await p;
  assert.equal(c.form.deptId, 303); assert(c.ready); c.$destroy(); pass('keep valid explicit subject');
  c = setup(); c.form.deptId = null; await Vue.nextTick(); p = c.loadSubjects(); subjects[0].resolve({ data: configured }); await p;
  assert.equal(c.form.deptId, null); assert(!c.ready); c.$destroy(); pass('multiple subjects require explicit choice');
  c = setup(); p = c.loadSubjects(); subjects[0].resolve({ data: [{ deptId: 302, configured: true }] }); await p;
  assert.equal(c.form.deptId, 302); assert(c.ready); c.$destroy(); pass('single allowed subject selects automatically');
  c = setup(); p = c.loadSubjects(); subjects[0].resolve({ data: [{ deptId: 303, configured: false }] }); await p;
  assert.equal(c.form.deptId, null); assert(!c.ready); c.$destroy(); pass('unconfigured departments cannot submit');
  c = setup(); let a = c.loadSubjects(), b = c.loadSubjects(); subjects[1].resolve({ data: [{ deptId: 301, configured: true }] }); await b;
  subjects[0].resolve({ data: configured }); await a; assert.equal(c.form.deptId, 301); assert.equal(c.subjects.length, 1); c.$destroy(); pass('late subject response ignored');
  c = setup(); p = c.loadSubjects(); subjects[0].reject(new Error('offline')); await p;
  assert(c.subjectsError); assert(!c.ready); assert(!c.subjectsLoading); await c.submit(false); assert.equal(saves.length, 0); c.$destroy(); pass('subject load failure disables creation and settles');
  c = setup(); p = c.loadCalcs(); assert.equal(calculations[0].params.deptId, 303);
  c.form.deptId = 301; await Vue.nextTick(); calculations[0].resolve({ data: [{ id: 4172 }] }); await p;
  assert.equal(c.calcs.length, 0); assert.equal(c.form.calculationTemplateId, null); assert(!c.calcsLoading); c.$destroy(); pass('switching subject invalidates old calculation response');
  c = setup(); a = c.loadCalcs(); c.form.deptId = 301; await Vue.nextTick(); b = c.loadCalcs();
  calculations[0].reject(new Error('old failure')); await a; assert(c.calcsLoading); assert.equal(c.calcsError, '');
  calculations[1].resolve({ data: [{ id: 4171 }] }); await b; assert.equal(c.calcs[0].id, 4171); c.$destroy(); pass('old subject error cannot clear new loading/data');
  c = setup(); assert.equal(c.subjectLabel(configured[0]), '机辆');
  assert(!c.subjectLabel(configured[0]).includes('3171'));
  assert(c.subjectLabel({ deptName: '未配置公司', configured: false }).includes('未配置报告数据来源'));
  c.$destroy(); pass('company label hides technical nodes and explains missing data source');
  c = setup(); p = c.loadCalcs(); calculations[0].resolve({ data: [{ id: 4172 }] }); await p;
  assert.equal(c.form.calculationTemplateId, 4172); c.$destroy(); pass('single successful task selects automatically');
  c = setup(); p = c.loadCalcs(); calculations[0].resolve({ data: [{ id: 4172 }, { id: 4173 }] }); await p;
  assert.equal(c.form.calculationTemplateId, null); c.$destroy(); pass('multiple successful tasks still require explicit choice');
  c = setup(); p = c.loadCalcs(); calculations[0].resolve({ data: [] }); await p;
  assert.equal(c.form.calculationTemplateId, null); assert(c.calcsQueried); c.$destroy(); pass('empty company result cannot retain previous task');
  c = setup(); c.calcs = [{ id: 4172 }]; c.form.calculationTemplateId = 999; await c.submit(true);
  assert.equal(saves.length, 0); c.$destroy(); pass('stale/forged task not submitted by page');
  c = setup(); c.calcs = [{ id: 4172 }]; c.form.calculationTemplateId = 4172; p = c.submit(true);
  await c.submit(true); assert.equal(saves.length, 1); assert.equal(saves[0].body.deptId, 303); assert.equal(saves[0].body.calculationTemplateId, 4172);
  c.form.reportYear = 2026; assert.equal(saves[0].body.reportYear, 2025);
  saves[0].reject(new Error('rejected')); await p; assert(!c.saving); assert.equal(c.form.deptId, 303); c.$destroy(); pass('submit freezes selected context, prevents duplicates and retains failed form');
  c = setup(); c.form.calculationTemplateId = 4172; p = c.submit(false); assert.equal(saves[0].body.calculationTemplateId, null);
  saves[0].resolve({ data: { id: 100 } }); await p; c.$destroy(); pass('blank report is an explicit separate action');
  c = setup(); p = c.loadSubjects(); c.$destroy(); subjects[0].resolve({ data: [] }); await p;
  assert.equal(c.subjects.length, 2); pass('destroyed page ignores subject responses');
  const config = component('SubjectConfiguration'); nodes = [];
  c = new Vue({ ...config, propsData: { visible: true, subjects: configured } });
  p = c.loadNodes(); c.$destroy(); nodes[0].resolve({ data: [{ subjectNodeId: 3 }] }); await p;
  assert.equal(c.nodes.length, 0); pass('configuration ignores late node response');
  const activity = component('steps/ActivityStep');
  c = new Vue({ ...activity, created: undefined, propsData: { draft: { task: { id: 1 } } } });
  c.loadGaps(); assert.equal(previews.length, 0); c.$destroy(); pass('blank report does not request missing calculation preview');
  c = new Vue({ ...activity, created: undefined, propsData: { draft: { task: { id: 1, calculationTemplateId: 11 } } } });
  c.loadGaps(); assert.equal(previews.length, 0); assert(c.sourceNotice.includes('历史报告')); assert.equal(c.gaps.length, 0); c.$destroy(); pass('legacy report reads saved activities without reimporting old task');
  c = new Vue({ ...activity, created: undefined, propsData: { draft: { task: { id: 1, calculationTemplateId: 11, metadataJson: '{"_report_subject":{"subjectNodeId":3171}}' } } } });
  c.loadGaps(); assert.equal(previews.length, 1); c.$destroy(); pass('new frozen report requests validated preview');
  const requests = [], api = { module: { exports: {} }, request: value => requests.push(value) };
  const apiSource = fs.readFileSync(path.join(root, 'ruoyi-ui/src/api/carbon/report.js'), 'utf8');
  vm.runInNewContext(apiSource.replace(/^import .*$/gm, '').replace(/export function/g, 'function') + '\nmodule.exports = { prefillPreview, prefillCommit };', api);
  api.module.exports.prefillPreview(33, {}); api.module.exports.prefillCommit(33, {});
  assert.equal(requests[0].headers.repeatSubmit, false); assert.equal(requests[1].headers, undefined);
  pass('only read preview bypasses duplicate guard; write commit keeps protection');
  console.log(JSON.stringify({ passed: checks.length, checks }, null, 2));
})().catch(error => { console.error(error); process.exitCode = 1; });
