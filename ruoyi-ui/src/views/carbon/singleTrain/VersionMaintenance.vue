<template>
  <div v-loading="busy">
    <h3>{{ target === 'energy' ? '从基础数据创建重空协同版本' : '单列车数据版本维护' }}</h3>
    <el-alert title="从空白版本开始，只复制兼容基础数据。补齐本模块专用数据后发布，来源版本保持原样。" type="info" :closable="false" />
    <el-form label-width="140px" style="margin-top:20px;max-width:1000px">
      <el-form-item label="基础数据来源"><el-select v-model="sourceKey" style="width:100%" @change="previewSource">
        <el-option v-for="s in sources" :key="s.module+s.version_id" :value="s.module+s.version_id" :label="(s.module==='single'?'单列车回收':'重空协同')+' / '+s.project_code+' / '+s.version_name" />
      </el-select></el-form-item>
      <el-form-item v-if="preview" label="导入内容">
        <el-tag v-for="f in preview.files" :key="f.name" style="margin:3px">{{ f.name }}</el-tag>
        <p>来源版本：{{ preview.source.version_code }}。未复制本模块专用参数。</p>
      </el-form-item>
      <el-form-item label="新版本编码"><el-input v-model="versionCode" placeholder="例如 single_v2；不能与已有版本重复" /></el-form-item>
      <el-form-item label="新版本名称"><el-input v-model="versionName" placeholder="便于员工识别的名称" /></el-form-item>
      <el-form-item><el-button type="primary" :disabled="!preview || !versionCode || !versionName" @click="derive">创建草稿</el-button></el-form-item>
    </el-form>
    <el-table :data="versions" @row-click="open" highlight-current-row>
      <el-table-column prop="version_name" label="版本名称" />
      <el-table-column prop="version_code" label="编码" />
      <el-table-column label="状态"><template #default="s">{{ s.row.status==='published'?'已发布':s.row.status==='publishing'?'发布待确认':'草稿' }}</template></el-table-column>
      <el-table-column label="可运行"><template #default="s">{{ s.row.readiness.ready?'数据齐全':'需要补齐' }}</template></el-table-column>
      <el-table-column label="操作"><template #default="s"><el-button link @click.stop="open(s.row)">查看 / 维护</el-button></template></el-table-column>
    </el-table>
    <div v-if="selected" style="margin-top:28px">
      <h3>{{ selected.version_name }}</h3>
      <el-alert :title="selected.readiness.ready?'数据校验通过，可发布后使用':'待补齐：'+selected.readiness.missing.join('、')" :type="selected.readiness.ready?'success':'warning'" :closable="false" />
      <p v-for="error in selected.readiness.errors" :key="error" class="error">{{ error }}</p>
      <p v-if="target==='single' && selected.readiness.missing.includes('locomotive_curves.json')" class="hint">此版本缺少新版必需的机车曲线。请创建新草稿，核对编组资料后使用默认模板或上传曲线文件；已发布版本保留原始内容。</p>
      <p class="hint">来源：{{ selected.provenance.sourceModule==='single'?'单列车回收':'重空协同' }} / {{ selected.provenance.sourceVersionCode }}；基础事实已冻结。</p>
      <el-button v-if="selected.status==='publishing'" type="primary" @click="publish">确认发布结果</el-button>
      <el-table v-if="target==='energy'" :data="featureRows" size="small"><el-table-column prop="name" label="功能" width="220" /><el-table-column label="准备状态"><template #default="s">{{ s.row.ready?'可运行':s.row.missing.join('、') }}</template></el-table-column></el-table>
      <div v-if="selected.status==='draft'" style="margin:20px 0">
        <el-button v-if="target==='single'" @click="defaults">使用算法默认参数模板</el-button>
        <label class="upload"><input type="file" multiple accept=".xlsx,.csv,.json" @change="upload" />上传数据文件</label>
        <label v-if="target==='energy'" class="upload"><input type="file" multiple webkitdirectory @change="upload" />上传本模块数据目录</label>
        <el-button type="primary" @click="save">保存草稿</el-button>
        <el-button type="success" :disabled="!selected.readiness.ready || dirty" @click="publish">发布新版本</el-button>
        <p class="hint">{{ target==='single'?'默认模板含电气占位和假设参数，状态标识保留。也可上传四类参数 JSON。':'可上传重空协同现有 Excel 模板或专用 CSV/JSON 文件；上传内容由管理员提供，不自动继承其他版本。' }}</p>
      </div>
      <el-tabs v-model="topic">
        <el-tab-pane v-if="target==='single'" v-for="(label, key) in parameterNames" :key="key" :label="label" :name="key">
          <el-empty v-if="!selected.parameters[key]" description="缺少此类参数，请采用默认模板或上传参数文件" />
          <el-form v-else label-width="290px" size="small" :disabled="selected.status!=='draft'">
            <el-form-item v-for="field in numericFields(selected.parameters[key], key)" :key="field.path" :label="field.label">
              <el-input-number :model-value="field.value" :step="field.step" @change="value => changeNumber(key, field.path, value)" />
              <span style="margin-left:8px">{{ field.unit }}</span>
              <el-tag size="small" :type="['assumed','placeholder','unknown'].includes(field.dataStatus)?'warning':'info'" style="margin-left:8px">{{ field.dataStatus }}</el-tag>
              <p class="hint">{{ field.provenance }}</p>
            </el-form-item>
            <el-alert :title="selected.parameters[key].note || selected.parameters[key].data_status || '模型参数'" type="info" :closable="false" />
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="基础 / 补充文件" name="files">
          <el-select v-model="fileName" @change="readFile"><el-option v-for="name in selected.fileNames" :key="name" :label="name" :value="name" /></el-select>
          <div v-if="fileName && !fileName.endsWith('.xlsx')" style="margin-top:16px">
            <p class="hint">CSV 保留表头；JSON 保留字段状态和来源。保存草稿时校验。</p>
            <el-input type="textarea" :rows="16" v-model="fileText" :disabled="selected.status!=='draft'" @input="dirty=true" />
          </div><p v-else-if="fileName" class="hint">运行图 Excel 已保存；需修改时重新上传该文件。</p>
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>
<script>
import { versionApi } from '@/api/carbon/singleTrain'
import { requestResult } from '@/utils/singleTrainRequests'
function encode(text) { return btoa(Array.from(new TextEncoder().encode(text), x => String.fromCharCode(x)).join('')) }
function decode(text) { return new TextDecoder().decode(Uint8Array.from(atob(text), x => x.charCodeAt(0))) }
function copy(value) { return value ? JSON.parse(JSON.stringify(value)) : value }
export default {
  props: { target: { type: String, default: 'single' } },
  data: () => ({ mutating: false, loadingList: false, loadingDetail: false, listLoaded: false, listRequest: 0, detailRequest: 0, previewRequest: 0, viewActive: true, disposed: false, savedSelection: null, leavePrompt: null, sources: [], versions: [], sourceKey: '', preview: null, versionCode: '', versionName: '', selected: null, topic: 'train', fileName: '', previousFileName: '', fileText: '', dirty: false, parameterNames: { train: '列车参数', motor: '电机参数', dc_dc: '变流器参数', storage: '储能参数' } }),
  computed: { busy() { return this.mutating || this.loadingList || this.loadingDetail }, api() { return versionApi(this.target) }, featureRows() { const names = { timetable_audit: '运行图审查', timetable_optimization: '运行图优化', rolling_rescheduling: '滚动重排', joint_parameter_robustness: '联合参数验证', historical_disturbance_replay: '历史扰动回放', storage_planning: '储能规划' }; return Object.entries(this.selected.readiness.features).map(([key, value]) => ({ name: names[key] || key, ...value })) } },
  created() { this.load() },
  mounted() { window.addEventListener('beforeunload', this.beforeUnload) },
  activated() { this.viewActive = true; if (!this.listLoaded) this.load() },
  deactivated() { this.viewActive = false; this.listRequest++; this.detailRequest++; this.previewRequest++; this.loadingList = false; this.loadingDetail = false },
  beforeUnmount() { this.disposed = true; this.viewActive = false; this.listRequest++; this.detailRequest++; this.previewRequest++; window.removeEventListener('beforeunload', this.beforeUnload) },
  methods: {
    beforeUnload(event) { if (!this.viewActive || !this.dirty) return; event.preventDefault(); event.returnValue = '' },
    async confirmLeave() { if (this.mutating) return false; if (!this.dirty) return true; if (this.leavePrompt) return this.leavePrompt; this.leavePrompt = this.$confirm('当前草稿有未保存的修改，是否放弃修改并继续？', '未保存的草稿', { confirmButtonText: '放弃修改并继续', cancelButtonText: '继续编辑', type: 'warning', distinguishCancelAndClose: true }).then(() => { this.selected = copy(this.savedSelection); this.resetEditor(); return true }, () => false); try { return await this.leavePrompt } finally { this.leavePrompt = null } },
    async load() { if (this.loadingList) return; const request = ++this.listRequest; this.loadingList = true; const [v, s] = await Promise.all([requestResult(this.api.list()), requestResult(this.api.sources())]); if (this.disposed || !this.viewActive || request !== this.listRequest) return; this.loadingList = false; if (v.ok) this.versions = v.response.data; if (s.ok) this.sources = s.response.data; this.listLoaded = v.ok && s.ok },
    sourceBody() { const s = this.sources.find(s => s.module + s.version_id === this.sourceKey); return s ? { sourceModule: s.module, sourceVersionId: s.version_id } : null },
    async previewSource() { const request = ++this.previewRequest; const key = this.sourceKey; const body = this.sourceBody(); this.preview = null; if (!body) return; const result = await requestResult(this.api.preview(body)); if (!this.disposed && this.viewActive && request === this.previewRequest && key === this.sourceKey && result.ok) this.preview = result.response.data },
    acceptVersion(version) { this.selected = version; this.savedSelection = copy(version); this.resetEditor() },
    async mutate(action, message) { if (this.mutating || this.loadingDetail || this.disposed || !this.viewActive) return; this.mutating = true; try { const result = await requestResult(action()); if (!result.ok || this.disposed || !this.viewActive) return; this.acceptVersion(result.response.data); if (message) this.$message.success(message); await this.load() } finally { this.mutating = false } },
    async derive() { const body = this.sourceBody(); if (!body || !this.preview || !(await this.confirmLeave())) return; await this.mutate(() => this.api.derive({ ...body, versionCode: this.versionCode, versionName: this.versionName })) },
    async open(row) { if (this.selected && row.version_id === this.selected.version_id) return; const request = ++this.detailRequest; if (!(await this.confirmLeave()) || request !== this.detailRequest || this.disposed || !this.viewActive) return; this.loadingDetail = true; const result = await requestResult(this.api.get(row.version_id)); if (this.disposed || !this.viewActive || request !== this.detailRequest) return; this.loadingDetail = false; if (result.ok) this.acceptVersion(result.response.data) },
    resetEditor() { this.fileName = ''; this.previousFileName = ''; this.fileText = ''; this.dirty = false; if (this.target === 'energy') this.topic = 'files' },
    async defaults() { if (!this.selected || this.selected.status !== 'draft' || !(await this.confirmLeave())) return; await this.mutate(() => this.api.defaults(this.selected.version_id)) },
    readFile() { if (this.previousFileName && !this.previousFileName.endsWith('.xlsx') && this.selected.status === 'draft') this.selected.files[this.previousFileName] = encode(this.fileText); this.fileText = this.fileName.endsWith('.xlsx') ? '' : decode(this.selected.files[this.fileName]); this.previousFileName = this.fileName },
    numericFields(obj, topic) { const fields = (this.selected.parameterMetadata || {})[topic] || []; return fields.map(field => { const value = field.path.split('.').reduce((item, key) => item && item[key], obj); return { ...field, value, step: Math.abs(value) < 1 ? 0.001 : 1 } }).filter(field => typeof field.value === 'number') },
    changeNumber(topic, path, value) { const keys = path.split('.'); let obj = this.selected.parameters[topic]; keys.slice(0, -1).forEach(k => { obj = obj[k] }); obj[keys[keys.length - 1]] = value; if (topic === 'storage' && path === 'capacity_kwh') obj.capacity_j = value * 3600000; if (topic === 'storage' && path === 'capacity_j') obj.capacity_kwh = value / 3600000; this.dirty = true },
    async save() { if (!this.selected || this.selected.status !== 'draft') return; if (this.fileName && !this.fileName.endsWith('.xlsx')) this.selected.files[this.fileName] = encode(this.fileText); await this.mutate(() => this.api.save(this.selected.version_id, { files: this.selected.files, parameters: this.selected.parameters }), '草稿已保存') },
    async publish() { if (!this.selected || this.dirty || !this.selected.readiness.ready) return; await this.mutate(() => this.api.publish(this.selected.version_id), '新版本已发布') },
    async upload(event) { try { const files = Array.from(event.target.files || []); if (!files.length || !this.selected || this.selected.status !== 'draft' || !(await this.confirmLeave())) return; const form = new FormData(); files.forEach(f => { form.append('files', f); const path = f.webkitRelativePath ? f.webkitRelativePath.split('/').slice(1).join('/') : f.name; form.append('relativePaths', path) }); await this.mutate(() => this.api.upload(this.selected.version_id, form)) } finally { event.target.value = '' } }
  }
}
</script>
<style scoped>.hint{color:#606266;line-height:1.7}.error{color:#f56c6c}.upload{display:inline-block;border:1px solid #dcdfe6;border-radius:4px;padding:11px 16px;margin:0 10px;cursor:pointer;color:#606266}.upload input{display:none}</style>
