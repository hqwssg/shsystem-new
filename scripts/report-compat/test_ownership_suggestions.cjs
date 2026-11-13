const fs=require('fs'),vm=require('vm'),assert=require('assert/strict'),path=require('path');
const root=path.resolve(__dirname,'../..');
const sfc=fs.readFileSync(path.join(root,'ruoyi-ui/src/views/carbon/report/steps/BoundaryStep.vue'),'utf8');
const code=sfc.match(/<script>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm,'').replace('export default','module.exports=');
const ctx={module:{exports:{}},prefillPreview:()=>Promise.reject(new Error('offline'))};vm.runInNewContext(code,ctx);
const def=ctx.module.exports;
function instance(draft){const self={draft,$message:{warning:()=>{self.warned=true;}}};Object.assign(self,def.data.call(self));for(const [key,fn]of Object.entries(def.methods))self[key]=fn.bind(self);return self;}
(async()=>{
 const self=instance({task:{id:1,metadataJson:JSON.stringify({_source_snapshot:{gaps:['已有热力核对项']}})},fuels:[{fuelType:'gasoline'},{fuelType:'diesel'},{fuelType:'natural_gas'}],electricity:[{sourceName:'牵引用电'},{sourceName:'生活用电'}],heat:[{site:'供热站'}]});
 self.suggestRows();assert.equal(self.form.emission_source_rows.length,6);assert.ok(self.form.emission_source_rows.some(r=>r.source==='柴油'));assert.equal(self.form.emission_sources.length,3);
 await self.loadGaps();assert.equal(self.gaps.length,2);assert.ok(self.gaps.includes('已有热力核对项'));
 const empty=instance({task:{id:2},fuels:[],electricity:[],heat:[]});empty.form.emission_source_rows=[{source:'原人工排放源'}];empty.form.emission_sources=['化石燃料燃烧'];
 empty.suggestRows();assert.equal(empty.form.emission_source_rows[0].source,'原人工排放源');assert.equal(empty.form.emission_sources.length,1);assert.ok(empty.warned);
 console.log('PASS six accepted activities generate six suggestions including diesel; empty data and failed preview preserve input and warnings');
})().catch(e=>{console.error(e);process.exit(1);});
