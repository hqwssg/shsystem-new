<template>
  <div class="app-container energy-versions">
    <div class="page-actions">
      <el-button :icon="$icon('el-icon-back')" size="small" @click="$router.push('/carbon/energy')">返回重空协同</el-button>
    </div>
    <el-tabs v-model="pageTab" :before-leave="beforeTabLeave">
      <el-tab-pane label="上传 Excel 发布" name="excel">
    <el-alert title="只上传你改过的 Excel。没上传的主题会沿用下面选中的底稿版本，发布后生成一个新版本，不会覆盖旧版。" type="info" :closable="false" show-icon class="hint" />

    <el-form label-width="140px" size="small">
      <el-form-item label="基于已有版本">
        <el-select v-model="baseKey" filterable placeholder="请选择底稿" style="width: 460px" @change="onBaseChange">
          <el-option v-for="item in versions" :key="item.projectCode + '/' + item.versionCode"
            :label="versionLabel(item)"
            :value="item.projectCode + '/' + item.versionCode" />
        </el-select>
        <div class="form-hint">新版本 = 该底稿的全部文件 + 本次上传的表。默认是最新已发布版本。</div>
      </el-form-item>
      <el-form-item label="项目名称">
        <el-input v-model="form.projectName" style="width: 460px" />
      </el-form-item>
      <el-form-item label="新版本编码">
        <el-input v-model="form.versionCode" style="width: 220px" />
        <span class="inline-hint">已发布的编码不能再用，例如 v1 之后用 v2</span>
      </el-form-item>
      <el-form-item label="备注">
        <el-input v-model="form.sourceNote" style="width: 460px" placeholder="可选，说明这次改了什么" />
      </el-form-item>
      <el-form-item label="数据文件">
        <el-button size="small" @click="downloadZip">全部模板打包下载</el-button>
        <div class="form-hint">每种文件单独下载模板、单独上传。不传的主题继续用底稿。数字不要带单位。</div>
        <div class="topic-list">
          <div v-for="item in templates" :key="item.code" class="topic-row">
            <div class="topic-meta">
              <div class="topic-title">{{ item.title }}</div>
              <div class="topic-hint">{{ item.hint }}</div>
            </div>
            <el-button size="small" @click="downloadOne(item)">下载模板</el-button>
            <el-upload
              action="#"
              accept=".xlsx"
              :auto-upload="false"
              :show-file-list="false"
              :limit="1"
              :on-change="function(file) { onTopicFile(item, file) }"
              :on-exceed="function(files) { replaceTopicFile(item, files[0]) }"
            >
              <el-button size="small" type="primary">{{ uploads[item.code] ? '重新选择' : '上传该文件' }}</el-button>
            </el-upload>
            <span v-if="uploads[item.code]" class="topic-file">
              {{ displayUploadName(uploads[item.code].name) }}
              <el-button link @click="clearTopic(item)">清除</el-button>
            </span>
            <span v-else class="topic-empty">未上传，沿用底稿</span>
          </div>
        </div>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="saving" @click="submitExcel">发布新版本</el-button>
      </el-form-item>
    </el-form>

    <el-collapse class="advanced">
      <el-collapse-item title="高级：项目编码、数据状态、整目录导入">
        <el-form label-width="140px" size="small">
          <el-form-item label="项目编码"><el-input v-model="form.projectCode" style="width: 320px" /></el-form-item>
          <el-form-item label="线路名称"><el-input v-model="form.routeName" style="width: 320px" /></el-form-item>
          <el-form-item label="数据状态">
            <el-select v-model="form.dataStatus" style="width: 220px">
              <el-option label="正式" value="official" />
              <el-option label="由正式派生" value="derived_from_official" />
              <el-option label="规划占位" value="planning_placeholder" />
              <el-option label="合成" value="synthetic" />
            </el-select>
          </el-form-item>
          <el-form-item label="整目录导入">
            <input ref="dirInput" type="file" multiple webkitdirectory @change="onDir" />
            <div class="form-hint">已选 {{ files.length }} 个文件。这是运维入口，会整包替换，不叠底稿。</div>
          </el-form-item>
          <el-form-item>
            <el-button :loading="saving" @click="submitDirectory">按目录发布</el-button>
          </el-form-item>
        </el-form>
      </el-collapse-item>
    </el-collapse>

    <el-table :data="versions" style="margin-top: 24px">
      <el-table-column prop="projectName" label="项目" />
      <el-table-column label="版本">
        <template #default="scope">{{ versionName(scope.row) }}</template>
      </el-table-column>
      <el-table-column label="数据状态">
        <template #default="scope">{{ statusName(scope.row.dataStatus) }}</template>
      </el-table-column>
      <el-table-column prop="lifecycleStatus" label="生命周期" />
      <el-table-column prop="publishedAt" label="发布时间" />
    </el-table>
      </el-tab-pane>
      <el-tab-pane label="在线编辑当前版本" name="edit" lazy>
        <version-edit />
      </el-tab-pane>
      <el-tab-pane label="复用其他模块基础数据" name="shared" lazy>
        <version-maintenance ref="maintenance" target="energy" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>
<script>
import { saveAs } from 'file-saver'
import { bindProject, downloadExcelTemplate, downloadExcelTemplateZip, listVersions, publishExcelVersion, publishVersion } from '@/api/carbon/energy'
import { DATA_STATUS_LABELS, stripVersionFileExtension, versionDisplayName, versionOptionLabel } from '@/utils/energyParameters'
import VersionEdit from './versionEdit'
import VersionMaintenance from '../singleTrain/VersionMaintenance'

export default {
  name: 'CarbonEnergyVersions',
  components: { VersionEdit, VersionMaintenance },
  data() {
    return {
      pageTab: 'excel',
      saving: false,
      files: [],
      uploads: {},
      versions: [],
      templates: [
        { code: 'geometry', filename: '线路几何.xlsx', title: '线路几何', hint: '线路总长、车站、区间坡度限速' },
        { code: 'trains', filename: '列车参数.xlsx', title: '列车参数', hint: '重车、空车质量与牵引制动' },
        { code: 'storage', filename: '储能设备.xlsx', title: '储能设备', hint: '容量功率电价和储能区段' },
        { code: 'timetable', filename: '运行图.xlsx', title: '运行图', hint: '列车时刻到发' },
        { code: 'operations', filename: '追踪与作业.xlsx', title: '追踪与作业', hint: '追踪间隔和技术作业时分' },
        { code: 'power_arm', filename: '供电臂.xlsx', title: '供电臂', hint: '供电臂起终点和储能接入' },
        { code: 'disturbance', filename: '滚动扰动.xlsx', title: '滚动扰动', hint: '历史晚点、限速、储能状态回放' },
        { code: 'storage_planning', filename: '储能规划.xlsx', title: '储能规划', hint: '候选站点、技术、场景和规划策略' },
        { code: 'joint_params', filename: '联合参数.xlsx', title: '联合参数', hint: '稳健性参数上下限' }
      ],
      baseKey: '',
      form: {
        projectCode: 'shuohuang_demo',
        projectName: '朔黄演示',
        routeName: 'shuohuang',
        versionCode: 'v2',
        dataStatus: 'planning_placeholder',
        sourceNote: '',
        baseProjectCode: 'shuohuang_demo',
        baseVersionCode: 'v1'
      }
    }
  },
  created() {
    this.reload()
  },
  beforeRouteLeave(to, from, next) { const editor = this.$refs.maintenance; if (this.pageTab === 'shared' && editor) editor.confirmLeave().then(allowed => next(allowed)); else next() },
  methods: {
    beforeTabLeave(next, current) {
      const editor = this.$refs.maintenance
      if (current !== 'shared' || !editor) return true
      // Element UI cancels an asynchronous tab change only when this promise rejects.
      return editor.confirmLeave().then(allowed => allowed ? true : Promise.reject(new Error('继续编辑')))
    },
    versionLabel(item) {
      return versionOptionLabel(item)
    },
    versionName(item) {
      return versionDisplayName(item)
    },
    statusName(value) {
      return DATA_STATUS_LABELS[value] || value
    },
    onDir(event) {
      this.files = Array.from(event.target.files || [])
    },
    selectedFiles() {
      return this.templates.map(item => this.uploads[item.code]).filter(Boolean)
    },
    displayUploadName(name) {
      return stripVersionFileExtension(name)
    },
    onTopicFile(item, file) {
      const raw = file && (file.raw || file)
      if (!raw) {
        return
      }
      const name = String(raw.name || item.filename)
      if (!/\.xlsx$/i.test(name)) {
        this.$message.error('请上传 .xlsx 文件')
        return
      }
      (this.uploads)[item.code] = new File([raw], name, { type: raw.type || 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
    },
    replaceTopicFile(item, file) {
      this.onTopicFile(item, file)
    },
    clearTopic(item) {
      delete (this.uploads)[item.code]
    },
    onBaseChange(value) {
      const item = this.findVersion(value)
      if (!item) {
        return
      }
      this.form.baseProjectCode = item.projectCode
      this.form.baseVersionCode = item.versionCode
      this.form.projectCode = item.projectCode
      this.form.projectName = item.projectName
      this.form.routeName = item.routeName || this.form.routeName
      this.form.versionCode = this.nextVersionCode(item.projectCode, item.versionCode)
    },
    findVersion(key) {
      return (this.versions || []).find(item => item.projectCode + '/' + item.versionCode === key)
    },
    nextVersionCode(projectCode, current) {
      const same = (this.versions || []).filter(item => item.projectCode === projectCode).map(item => String(item.versionCode || ''))
      const match = String(current || '').match(/^(.*?)(\d+)$/)
      if (!match) {
        return (current || 'v') + '2'
      }
      let next = Number(match[2]) + 1
      let code = match[1] + next
      while (same.indexOf(code) >= 0) {
        next += 1
        code = match[1] + next
      }
      return code
    },
    downloadOne(item) {
      downloadExcelTemplate(item.code).then(blob => {
        saveAs(blob, item.filename)
      }).catch(() => this.$message.error('下载模板失败'))
    },
    downloadZip() {
      downloadExcelTemplateZip().then(blob => {
        saveAs(blob, '能量数据Excel模板.zip')
      }).catch(() => this.$message.error('下载打包模板失败'))
    },
    reload() {
      listVersions().then(res => {
        this.versions = res.data || []
        if (!this.baseKey && this.versions.length) {
          const first = this.versions[0]
          this.baseKey = first.projectCode + '/' + first.versionCode
          this.onBaseChange(this.baseKey)
        }
      }).catch(() => {
        this.versions = []
        this.$message.error('加载版本失败')
      })
    },
    submitExcel() {
      if (!this.form.baseProjectCode || !this.form.baseVersionCode) {
        this.$message.error('请选择基于哪个已有版本')
        return
      }
      if (!this.form.projectCode || !this.form.versionCode) {
        this.$message.error('请填写项目和版本编码')
        return
      }
      const files = this.selectedFiles()
      if (!files.length) {
        this.$message.error('请至少上传一种 Excel')
        return
      }
      const data = new FormData()
      data.append('projectCode', this.form.projectCode)
      data.append('projectName', this.form.projectName || this.form.projectCode)
      data.append('routeName', this.form.routeName || 'shuohuang')
      data.append('versionCode', this.form.versionCode)
      data.append('dataStatus', this.form.dataStatus || 'planning_placeholder')
      data.append('sourceNote', this.form.sourceNote || '')
      data.append('baseProjectCode', this.form.baseProjectCode)
      data.append('baseVersionCode', this.form.baseVersionCode)
      files.forEach(file => data.append('files', file))
      this.saving = true
      bindProject({ projectCode: this.form.projectCode }).then(() => publishExcelVersion(data)).then(() => {
        this.$message.success('已发布新版本')
        this.uploads = {}
        this.form.versionCode = this.nextVersionCode(this.form.projectCode, this.form.versionCode)
        this.reload()
      }).catch(error => {
        const message = (error && error.message) || '发布失败'
        this.$alert(message, '无法发布', { type: 'error', customClass: 'excel-conflict-alert' })
      }).finally(() => { this.saving = false })
    },
    submitDirectory() {
      if (!this.form.projectCode || !this.form.versionCode) {
        this.$message.error('请填写项目和版本编码')
        return
      }
      if (!this.files.length) {
        this.$message.error('请选择输入目录')
        return
      }
      const data = new FormData()
      Object.keys(this.form).forEach(key => {
        if (key.indexOf('base') === 0) {
          return
        }
        data.append(key, this.form[key] || '')
      })
      this.files.forEach(file => {
        const relative = file.webkitRelativePath || file.name
        const slash = relative.indexOf('/')
        const stored = slash >= 0 ? relative.slice(slash + 1) : relative
        data.append('files', file)
        data.append('relativePaths', stored)
      })
      this.saving = true
      bindProject({ projectCode: this.form.projectCode }).then(() => publishVersion(data)).then(() => {
        this.$message.success('已发布')
        this.reload()
      }).catch(() => {
        this.$message.error('发布失败')
      }).finally(() => { this.saving = false })
    }
  }
}
</script>
<style scoped>
.hint {
  margin-bottom: 16px;
}
.form-hint {
  color: #909399;
  font-size: 12px;
  line-height: 1.5;
  margin-top: 4px;
}
.inline-hint {
  margin-left: 8px;
  color: #909399;
  font-size: 12px;
}
.advanced {
  margin-top: 8px;
}
.topic-list {
  margin-top: 8px;
  border: 1px solid #ebeef5;
  border-radius: 4px;
}
.topic-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-bottom: 1px solid #ebeef5;
}
.topic-row:last-child {
  border-bottom: none;
}
.topic-meta {
  width: 220px;
  flex-shrink: 0;
}
.topic-title {
  font-weight: 600;
}
.topic-hint {
  color: #909399;
  font-size: 12px;
  line-height: 1.4;
}
.topic-file {
  color: #67c23a;
  font-size: 12px;
}
.topic-empty {
  color: #c0c4cc;
  font-size: 12px;
}
</style>
<style>
.excel-conflict-alert .el-message-box__message p {
  white-space: pre-wrap;
  max-height: 320px;
  overflow: auto;
  text-align: left;
}
</style>
