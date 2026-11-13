const fs = require('fs'), path = require('path'), vm = require('vm'), assert = require('assert');
const root = path.resolve(__dirname, '../..');
const compiler = require(path.join(root, 'tpfhs-9/frontend/node_modules/@vue/compiler-sfc'));
const vue = require(path.join(root, 'tpfhs-9/frontend/node_modules/vue'));
const source = fs.readFileSync(path.join(root, 'tpfhs-9/frontend/src/components/TemplateList.vue'), 'utf8');
const parsed = compiler.parse(source).descriptor;
assert.deepEqual(compiler.compileTemplate({ source: parsed.template.content, filename: 'TemplateList.vue', id: 'test' }).errors, []);
compiler.compileScript(parsed, { id: 'test' });
const checks = ['template and setup compile'];
const deferred = () => { let resolve, reject; const promise = new Promise((a,b) => { resolve=a; reject=b; }); return { promise, resolve, reject }; };
function setup() {
  const requests = [], writes = [], errors = [], hooks = [];
  const api = { getCompanies: () => { const d = deferred(); requests.push(d); return d.promise; }, getAllTemplates: () => Promise.resolve({data:[]}),
    createTemplate: (...args) => { const d=deferred(); writes.push({args,...d}); return d.promise; },
    copyTemplate: (...args) => { const d=deferred(); writes.push({args,...d}); return d.promise; },
    assignCompany: (...args) => { const d=deferred(); writes.push({args,...d}); return d.promise; } };
  const context = { module:{exports:{}}, ref:vue.ref, computed:vue.computed, onMounted:()=>{}, onBeforeUnmount:fn=>hooks.push(fn),
    defineProps:()=>({currentUser:{userId:8}}), defineEmits:()=>()=>{}, hasPermission:()=>true,
    ElMessage:{error:e=>errors.push(e),warning:e=>errors.push(e),success:()=>{}}, templateApi:api, factorTemplateApi:{}, console, Date, JSON, Map, Set };
  vm.runInNewContext(parsed.scriptSetup.content.replace(/^import .*$/gm,'') + '\nmodule.exports={loadCompanies,companies,companiesLoading,companiesReady,handleNewTemplate,confirmNewTemplate,newTemplateForm,showNewModal,selectedTemplate,openCompanyOwnership,saveCompanyOwnership,ownershipForm,companyVisible,handleSaveAs,confirmSaveAs,saveAsForm};', context);
  return { c:context.module.exports,requests,writes,errors,hooks };
}
const companies = [{deptId:302,deptName:'A'},{deptId:303,deptName:'B'}];
(async()=>{
  let t=setup(), p=t.c.handleNewTemplate(2); t.requests[0].resolve({data:companies}); await p;
  assert.equal(t.c.newTemplateForm.value.companyDeptId,null); t.c.newTemplateForm.value.name='A'; await t.c.confirmNewTemplate(); assert.equal(t.writes.length,0); checks.push('multiple companies require explicit choice');
  t.c.newTemplateForm.value.companyDeptId=302; p=t.c.confirmNewTemplate(); await t.c.confirmNewTemplate(); assert.equal(t.writes.length,1);assert.equal(t.writes[0].args[4],302);
  t.writes[0].reject(new Error('offline')); await p; assert(t.c.showNewModal.value); assert.equal(t.c.newTemplateForm.value.companyDeptId,302); checks.push('create sends company, blocks duplicate, retains failed form');
  t=setup();p=t.c.handleNewTemplate(2);t.requests[0].resolve({data:[companies[0]]});await p;assert.equal(t.c.newTemplateForm.value.companyDeptId,302);checks.push('single authorized company selects automatically');
  t=setup();p=t.c.handleNewTemplate(2);t.requests[0].reject(new Error('offline'));await p;t.c.newTemplateForm.value.name='A';await t.c.confirmNewTemplate();assert.equal(t.writes.length,0);assert(!t.c.companiesReady.value);checks.push('company option failure settles and prevents submission');
  t=setup();let a=t.c.loadCompanies(), b=t.c.loadCompanies();t.requests[1].resolve({data:[companies[1]]});await b;t.requests[0].resolve({data:[companies[0]]});await a;assert.equal(t.c.companies.value[0].deptId,303);checks.push('late company response cannot overwrite latest');
  t=setup();p=t.c.loadCompanies();t.hooks[0]();t.requests[0].resolve({data:companies});await p;assert.equal(t.c.companies.value.length,0);checks.push('destroyed component ignores response');
  t=setup();t.c.selectedTemplate.value={id:5,name:'Old',companyDeptId:302,templateType:2};p=t.c.openCompanyOwnership();t.requests[0].resolve({data:companies});await p;
  assert.equal(t.c.ownershipForm.value.confirmLegacyTasks,false);p=t.c.saveCompanyOwnership();assert.deepEqual(t.writes[0].args,[5,302,false]);t.writes[0].reject(new Error('conflict'));await p;assert(t.c.companyVisible.value);checks.push('history confirmation defaults off, failed ownership save retains input');
  t.c.ownershipForm.value.confirmLegacyTasks=true;p=t.c.saveCompanyOwnership();assert.deepEqual(t.writes[1].args,[5,302,true]);t.writes[1].resolve({data:{}});await p;checks.push('explicit history confirmation is sent separately');
  t=setup();t.c.selectedTemplate.value={id:5,name:'Copy',companyDeptId:302,templateType:2};p=t.c.handleSaveAs();t.requests[0].resolve({data:companies});await p;t.c.saveAsForm.value.companyDeptId=303;p=t.c.confirmSaveAs();assert.equal(t.writes[0].args[3],303);t.writes[0].resolve({});await p;checks.push('copy sends chosen destination company');
  console.log(JSON.stringify({passed:checks.length,checks},null,2));
})().catch(e=>{console.error(e);process.exitCode=1;});
