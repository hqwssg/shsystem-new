<template>
  <div class="app-container carbon-data-entry">
    <div class="carbon-toolbar">
      <div>
        <h2>人工数据录入</h2>
        <span>按节点口径完成手工填报、校验、审核与追溯</span>
      </div>
      <div class="toolbar-actions">
        <el-button icon="el-icon-refresh" :loading="loadingTree" @click="loadTree">刷新节点</el-button>
        <el-button v-if="canEditData" type="primary" icon="el-icon-download" :disabled="!canEnterSelected" @click="downloadImportTemplate">下载导入模板</el-button>
      </div>
    </div>

    <el-alert
      v-if="serviceError"
      class="service-alert"
      type="warning"
      :title="serviceError"
      show-icon
      :closable="false"
    />

    <div class="entry-workbench">
      <aside class="node-panel">
        <div class="panel-title">
          <span>录入对象</span>
          <small>{{ entryNodeCount }} 个采集点</small>
        </div>
        <div class="tree-source-tip">电表、化石燃料表、外购热能表</div>
        <div class="tree-actions">
          <el-button size="mini" icon="el-icon-arrow-down" @click="setTreeExpansion(true)">展开全部</el-button>
          <el-button size="mini" icon="el-icon-arrow-up" @click="setTreeExpansion(false)">收起全部</el-button>
        </div>
        <el-input
          v-model="treeKeyword"
          class="tree-search"
          clearable
          prefix-icon="el-icon-search"
          placeholder="搜索节点"
        />
        <el-checkbox v-model="manualOnly" class="manual-filter" @change="selectFirstNode">只看手工录入采集点</el-checkbox>

        <el-tree
          ref="nodeTree"
          v-loading="loadingTree"
          class="node-tree"
          :data="filteredTree"
          :props="treeProps"
          node-key="id"
          :default-expanded-keys="expandedKeys"
          highlight-current
          :filter-node-method="filterNode"
          @node-click="handleNodeClick"
        >
          <span slot-scope="{ node, data }" class="tree-node" :class="{ 'is-entry': isEntryNode(data) }">
            <i :class="nodeIcon(data)"></i>
            <span>{{ node.label }}</span>
            <el-tag v-if="isEntryNode(data)" size="mini" :type="isManualNode(data) ? 'success' : 'info'">
              {{ isManualNode(data) ? '手工' : '其他' }}
            </el-tag>
          </span>
        </el-tree>
      </aside>

      <main class="entry-main">
        <el-empty v-if="!selectedNode" description="请选择左侧采集点后录入数据" />

        <template v-else>
          <section class="caliber-card">
            <div class="caliber-head">
              <div>
                <span class="eyebrow">当前采集点</span>
                <h3>{{ selectedNode.name }}</h3>
              </div>
              <el-tag :type="isManualNode(selectedNode) ? 'success' : 'warning'">
                {{ isManualNode(selectedNode) ? '手工录入' : '非手工来源' }}
              </el-tag>
            </div>
            <div class="caliber-grid">
              <div>
                <span>排放大类</span>
                <strong>{{ selectedConfig.emissionCategory || '-' }}</strong>
              </div>
              <div>
                <span>排放小类</span>
                <strong>{{ selectedConfig.emissionSubcategory || '-' }}</strong>
              </div>
              <div>
                <span>计量单位</span>
                <strong>{{ selectedConfig.measurementUnit || '-' }}</strong>
              </div>
              <div>
                <span>排放因子</span>
                <strong>{{ formatNumber(selectedConfig.carbonEmissionFactor) }}</strong>
              </div>
              <div>
                <span>分摊比例</span>
                <strong>{{ formatRatio(selectedConfig.allocationRatio) }}</strong>
              </div>
              <div>
                <span>采集编码</span>
                <strong>{{ selectedConfig.equipmentCode || '-' }}</strong>
              </div>
              <div>
                <span>采集方式</span>
                <strong>{{ selectedNode.isCumulative === 1 ? '累加型（按读数时间）' : '周期型（按计量周期）' }}</strong>
              </div>
            </div>
          </section>

          <el-tabs v-model="activeTab" class="entry-tabs" @tab-click="handleTabClick">
            <el-tab-pane label="单条录入" name="single">
              <section class="entry-section">
                <el-alert
                  v-if="!canEnterSelected"
                  class="entry-disabled-alert"
                  type="info"
                  show-icon
                  :closable="false"
                  title="自动采集节点仅供查看，不能进行人工数据录入"
                />
                <el-form ref="entryForm" :model="form" :rules="rules" label-width="104px">
                  <el-row :gutter="16">
                    <el-col :xs="24" :md="8">
                      <el-form-item :label="selectedNode.isCumulative === 1 ? '采集类型' : '计量周期'" prop="periodType">
                        <el-select v-model="form.periodType" :disabled="!canEnterSelected" style="width: 100%" @change="syncPeriodEnd">
                          <el-option v-for="item in periodOptions" :key="item.value" :label="item.label" :value="item.value" />
                        </el-select>
                      </el-form-item>
                    </el-col>
                    <el-col :xs="24" :md="8">
                      <el-form-item :label="selectedNode.isCumulative === 1 ? '读数日期' : '周期开始'" prop="periodStart">
                        <el-date-picker
                          v-model="form.periodStart"
                          type="date"
                          value-format="yyyy-MM-dd"
                          style="width: 100%"
                          :disabled="!canEnterSelected"
                          @change="syncPeriodEnd"
                        />
                      </el-form-item>
                    </el-col>
                    <el-col :xs="24" :md="8">
                      <el-form-item v-if="selectedNode.isCumulative !== 1" label="周期结束" prop="periodEnd">
                        <el-input :value="form.periodEnd" readonly class="readonly-control" />
                      </el-form-item>
                    </el-col>
                  </el-row>

                  <el-row :gutter="16">
                    <el-col :xs="24" :md="8">
                      <el-form-item label="活动数据" prop="activityValue">
                        <el-input-number v-model="form.activityValue" :min="0" :precision="6" :disabled="!canEnterSelected" style="width: 100%" />
                      </el-form-item>
                    </el-col>
                    <el-col :xs="24" :md="8">
                      <el-form-item label="计量单位" prop="activityUnit">
                        <el-input :value="selectedConfig.measurementUnit || form.activityUnit || '-'" readonly class="readonly-control" />
                      </el-form-item>
                    </el-col>
                    <el-col :xs="24" :md="8">
                      <el-form-item label="换算系数" prop="unitConvertRate">
                        <el-input :value="formatNumber(form.unitConvertRate)" readonly class="readonly-control" />
                      </el-form-item>
                    </el-col>
                  </el-row>

                  <el-row :gutter="16">
                    <el-col :xs="24" :md="8">
                      <el-form-item label="排放因子" prop="emissionFactor">
                        <el-input :value="formatNumber(form.emissionFactor)" readonly class="readonly-control" />
                      </el-form-item>
                    </el-col>
                    <el-col :xs="24" :md="8">
                      <el-form-item label="因子单位">
                        <el-input :value="form.factorUnit || '-'" readonly class="readonly-control" />
                      </el-form-item>
                    </el-col>
                    <el-col :xs="24" :md="8">
                      <el-form-item label="分摊比例">
                        <el-input :value="formatRatio(form.allocationRatio)" readonly class="readonly-control" />
                      </el-form-item>
                    </el-col>
                  </el-row>

                  <el-row :gutter="16">
                    <el-col :xs="24" :md="8">
                      <el-form-item label="碳排放量">
                        <el-input :value="formatNumber(estimatedEmission)" readonly class="readonly-control">
                          <template slot="append">tCO2e</template>
                        </el-input>
                      </el-form-item>
                    </el-col>
                    <el-col :xs="24" :md="8">
                      <el-form-item label="凭证编号">
                        <el-input :value="form.sourceNo || '-'" readonly class="readonly-control" />
                      </el-form-item>
                    </el-col>
                    <el-col :xs="24" :md="8">
                      <el-form-item label="凭证地址">
                        <el-input :value="form.evidenceUrl || '-'" readonly class="readonly-control" />
                      </el-form-item>
                    </el-col>
                  </el-row>

                  <el-form-item label="备注说明">
                    <el-input :value="form.remark || '-'" type="textarea" :rows="3" readonly class="readonly-control" />
                  </el-form-item>
                </el-form>

                <div class="form-actions">
                  <el-button @click="resetEntryForm">重置</el-button>
                  <el-button v-if="canEditData" type="primary" plain :loading="saving" :disabled="!canEnterSelected" @click="saveEntry('DRAFT')">保存数据</el-button>
                  <el-button v-if="canSubmitData" type="success" :loading="saving" :disabled="!canEnterSelected" @click="saveEntry('SUBMITTED')">提交数据</el-button>
                </div>
              </section>
            </el-tab-pane>

            <el-tab-pane label="批量导入" name="batch" :disabled="!canEnterSelected">
              <section class="entry-section">
                <div class="batch-toolbar">
                  <input ref="importFile" type="file" accept=".csv,text/csv" class="file-input" @change="handleImportFile">
                  <el-button v-if="canEditData" icon="el-icon-upload2" @click="$refs.importFile.click()">选择 CSV 文件</el-button>
                  <el-button v-if="canEditData" type="primary" :disabled="!validImportRows.length" :loading="importing" @click="importBatch">导入有效数据</el-button>
                  <span>{{ importRows.length }} 行预览，{{ validImportRows.length }} 行有效</span>
                </div>
                <el-alert
                  v-if="importErrors.length"
                  class="import-alert"
                  type="warning"
                  show-icon
                  :closable="false"
                  :title="importErrors.slice(0, 3).join('；')"
                />
                <el-table :data="importRows" border max-height="420">
                  <el-table-column label="状态" width="90" align="center">
                    <template slot-scope="scope">
                      <el-tag size="mini" :type="scope.row._error ? 'danger' : 'success'">
                        {{ scope.row._error ? '异常' : '有效' }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="节点" prop="nodeName" min-width="150" show-overflow-tooltip />
                  <el-table-column label="周期" width="120">
                    <template slot-scope="scope">{{ periodLabel(scope.row.periodType) }}</template>
                  </el-table-column>
                  <el-table-column label="开始日期" prop="periodStart" width="120" />
                  <el-table-column label="结束日期" prop="periodEnd" width="120" />
                  <el-table-column label="活动数据" prop="activityValue" width="120" align="right" />
                  <el-table-column label="单位" prop="activityUnit" width="90" />
                  <el-table-column label="问题" prop="_error" min-width="200" show-overflow-tooltip />
                </el-table>
              </section>
            </el-tab-pane>

            <el-tab-pane v-if="canReviewData" :label="`待审核(${pendingRecords.length})`" name="review">
              <section class="entry-section">
                <el-table v-loading="loadingRecords" :data="pendingRecords" border>
                  <el-table-column label="提交人" prop="submitterName" width="120" show-overflow-tooltip />
                  <el-table-column label="周期" width="180">
                    <template slot-scope="scope">{{ periodText(scope.row) }}</template>
                  </el-table-column>
                  <el-table-column label="活动数据" min-width="130" align="right">
                    <template slot-scope="scope">{{ formatNumber(scope.row.activityValue) }} {{ scope.row.activityUnit }}</template>
                  </el-table-column>
                  <el-table-column label="碳排放量" prop="carbonEmission" width="130" align="right">
                    <template slot-scope="scope">{{ formatNumber(scope.row.carbonEmission) }}</template>
                  </el-table-column>
                  <el-table-column label="凭证" min-width="160" show-overflow-tooltip>
                    <template slot-scope="scope">{{ scope.row.sourceNo || scope.row.evidenceUrl || '-' }}</template>
                  </el-table-column>
                  <el-table-column label="提交时间" prop="submittedAt" width="170" />
                  <el-table-column label="操作" width="210" align="center" fixed="right">
                    <template slot-scope="scope">
                      <el-button v-if="canReviewData" type="text" icon="el-icon-check" @click="approveRecord(scope.row)">通过</el-button>
                      <el-button v-if="canReviewData" type="text" icon="el-icon-close" @click="openReject(scope.row)">驳回</el-button>
                      <el-button type="text" icon="el-icon-document" @click="viewAudits(scope.row)">流水</el-button>
                    </template>
                  </el-table-column>
                </el-table>
              </section>
            </el-tab-pane>

            <el-tab-pane label="历史记录" name="history">
              <section class="entry-section">
                <el-form :model="historyQuery" size="small" :inline="true" class="history-filter">
                  <el-form-item label="日期">
                    <el-date-picker
                      v-model="historyQuery.dateRange"
                      type="daterange"
                      value-format="yyyy-MM-dd"
                      range-separator="-"
                      start-placeholder="开始日期"
                      end-placeholder="结束日期"
                      style="width: 260px"
                    />
                  </el-form-item>
                  <el-form-item label="状态">
                    <el-select v-model="historyQuery.status" clearable style="width: 140px">
                      <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
                    </el-select>
                  </el-form-item>
                  <el-form-item>
                    <el-button type="primary" icon="el-icon-search" @click="handleHistoryQuery">查询</el-button>
                    <el-button icon="el-icon-refresh" @click="resetHistoryQuery">重置</el-button>
                  </el-form-item>
                </el-form>

                <el-table v-loading="loadingRecords" :data="historyRecords" border>
                  <el-table-column label="状态" width="100" align="center">
                    <template slot-scope="scope">
                      <el-tag size="mini" :type="collectionStatusType(scope.row)">{{ collectionStatusLabel(scope.row) }}</el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="周期" width="180">
                    <template slot-scope="scope">{{ periodText(scope.row) }}</template>
                  </el-table-column>
                  <el-table-column label="活动数据" min-width="140" align="right">
                    <template slot-scope="scope">{{ formatNumber(scope.row.activityValue) }} {{ scope.row.activityUnit }}</template>
                  </el-table-column>
                  <el-table-column label="因子" prop="emissionFactor" width="110" align="right">
                    <template slot-scope="scope">{{ formatNumber(scope.row.emissionFactor) }}</template>
                  </el-table-column>
                  <el-table-column label="碳排放量" prop="carbonEmission" width="130" align="right">
                    <template slot-scope="scope">{{ formatNumber(scope.row.carbonEmission) }}</template>
                  </el-table-column>
                  <el-table-column label="凭证" min-width="150" show-overflow-tooltip>
                    <template slot-scope="scope">{{ scope.row.sourceNo || scope.row.evidenceUrl || '-' }}</template>
                  </el-table-column>
                  <el-table-column label="备注" prop="remark" min-width="160" show-overflow-tooltip />
                  <el-table-column label="操作" width="260" align="center" fixed="right">
                    <template slot-scope="scope">
                      <el-button v-if="canEditData && canEdit(scope.row)" type="text" icon="el-icon-edit" @click="editRecord(scope.row)">编辑</el-button>
                      <el-button v-if="canLockData && scope.row.status === 'APPROVED'" type="text" icon="el-icon-lock" @click="lockRecord(scope.row)">锁定</el-button>
                      <el-button type="text" icon="el-icon-document" @click="viewAudits(scope.row)">流水</el-button>
                      <el-button v-if="canLockData && canVoid(scope.row)" type="text" icon="el-icon-delete" @click="voidRecord(scope.row)">作废</el-button>
                    </template>
                  </el-table-column>
                </el-table>

                <el-pagination
                  class="table-pagination"
                  background
                  layout="total, sizes, prev, pager, next, jumper"
                  :total="historyTotal"
                  :page-size.sync="historyQuery.size"
                  :current-page.sync="historyQuery.page"
                  :page-sizes="[10, 20, 50, 100]"
                  @size-change="loadHistory"
                  @current-change="loadHistory"
                />
              </section>
            </el-tab-pane>
          </el-tabs>
        </template>
      </main>
    </div>

    <el-dialog title="驳回原因" :visible.sync="rejectVisible" width="460px" append-to-body>
      <el-input v-model="rejectComment" type="textarea" :rows="4" placeholder="请输入驳回原因" />
      <div slot="footer" class="dialog-footer">
        <el-button @click="rejectVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="rejectRecord">确定驳回</el-button>
      </div>
    </el-dialog>

    <el-dialog title="操作流水" :visible.sync="auditVisible" width="720px" append-to-body>
      <el-timeline v-if="auditLogs.length">
        <el-timeline-item
          v-for="item in auditLogs"
          :key="item.id"
          :timestamp="item.operatedAt"
          placement="top"
        >
          <div class="audit-item">
            <strong>{{ auditActionLabel(item.action) }}</strong>
            <span>{{ auditStatusLabel(item.fromStatus) }} -> {{ auditStatusLabel(item.toStatus) }}</span>
            <p v-if="item.comment">{{ item.comment }}</p>
          </div>
        </el-timeline-item>
      </el-timeline>
      <el-empty v-else description="暂无操作流水" />
    </el-dialog>
  </div>
</template>

<script>
import { collectionApi, emissionApi, flattenCarbonTree } from '@/api/carbon'
import { hasAnyPermission, hasAnyRole } from '@/utils/permissionMatch'

function today() {
  const date = new Date()
  return formatDate(date)
}

function formatDate(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

function parseDate(value) {
  if (!value) return null
  const parts = String(value).split('-').map(Number)
  return new Date(parts[0], (parts[1] || 1) - 1, parts[2] || 1)
}

export default {
  name: 'CarbonDataEntry',
  data() {
    return {
      loadingTree: false,
      loadingRecords: false,
      saving: false,
      importing: false,
      serviceError: '',
      templates: [],
      rawTree: null,
      expandedKeys: [],
      treeKeyword: '',
      manualOnly: false,
      selectedNode: null,
      activeTab: 'single',
      treeProps: {
        children: 'children',
        label: 'name'
      },
      query: {
        templateId: null
      },
      form: this.emptyForm(),
      rules: {
        periodType: [{ required: true, message: '请选择统计周期', trigger: 'change' }],
        periodStart: [{ required: true, message: '请选择开始日期', trigger: 'change' }],
        periodEnd: [{ required: true, message: '请选择结束日期', trigger: 'change' }],
        activityValue: [{ required: true, message: '请输入活动数据', trigger: 'blur' }],
        activityUnit: [{ required: true, message: '请选择计量单位', trigger: 'change' }],
        unitConvertRate: [{ required: true, message: '请输入换算系数', trigger: 'blur' }],
        emissionFactor: [{ required: true, message: '请输入排放因子', trigger: 'blur' }]
      },
      periodOptions: [
        { label: '日', value: 'DAY' },
        { label: '月', value: 'MONTH' },
        { label: '季', value: 'QUARTER' },
        { label: '年', value: 'YEAR' },
        { label: '自定义', value: 'CUSTOM' }
      ],
      statusOptions: [
        { label: '草稿', value: 'DRAFT', type: 'info' },
        { label: '待审核', value: 'SUBMITTED', type: 'warning' },
        { label: '已通过', value: 'APPROVED', type: 'success' },
        { label: '已驳回', value: 'REJECTED', type: 'danger' },
        { label: '已锁定', value: 'LOCKED', type: '' },
        { label: '已作废', value: 'VOIDED', type: 'info' }
      ],
      historyQuery: {
        status: '',
        dateRange: [],
        page: 1,
        size: 10
      },
      historyRecords: [],
      pendingRecords: [],
      historyTotal: 0,
      importRows: [],
      importErrors: [],
      rejectVisible: false,
      rejectComment: '',
      rejectTarget: null,
      auditVisible: false,
      auditLogs: []
    }
  },
  computed: {
    isAdmin() {
      return hasAnyRole(this.$store.getters.roles, ['admin'])
    },
    canEditData() {
      return this.isAdmin || hasAnyPermission(this.$store.getters.permissions, ['carbon:data:edit'])
    },
    canSubmitData() {
      return this.isAdmin || hasAnyPermission(this.$store.getters.permissions, ['carbon:data:submit'])
    },
    canReviewData() {
      return this.isAdmin || hasAnyPermission(this.$store.getters.permissions, ['carbon:data:review'])
    },
    canLockData() {
      return this.isAdmin || hasAnyPermission(this.$store.getters.permissions, ['carbon:data:lock'])
    },
    canEnterSelected() {
      return !!this.selectedNode && this.isEntryNode(this.selectedNode)
        && this.isManualNode(this.selectedNode)
    },
    selectedConfig() {
      return this.selectedNode || {}
    },
    filteredTree() {
      if (!this.rawTree) return []
      const node = this.filterManualTree(this.rawTree)
      return node ? [node] : []
    },
    allEntryNodes() {
      if (!this.rawTree) return []
      return flattenCarbonTree(this.rawTree).filter(item => this.isEntryNode(item))
    },
    entryNodeCount() {
      return this.allEntryNodes.length
    },
    unitOptions() {
      const units = new Set()
      if (this.selectedConfig.measurementUnit) units.add(this.selectedConfig.measurementUnit)
      ;(this.categoryUnits(this.selectedConfig.emissionCategory) || []).forEach(unit => units.add(unit))
      return Array.from(units)
    },
    estimatedEmission() {
      const value = Number(this.form.activityValue || 0)
      const rate = Number(this.form.unitConvertRate || 0)
      const factor = Number(this.form.emissionFactor || 0)
      const ratio = Number(this.form.allocationRatio || 0) / 100
      return value * rate * factor * ratio
    },
    validImportRows() {
      return this.importRows.filter(item => !item._error)
    }
  },
  watch: {
    treeKeyword(value) {
      if (this.$refs.nodeTree) {
        this.$refs.nodeTree.filter(value)
      }
    }
  },
  created() {
    this.loadTree()
  },
  methods: {
    operatorId() {
      return this.$store.getters.id || 1
    },
    emptyForm() {
      return {
        id: null,
        nodeId: null,
        periodType: 'MONTH',
        periodStart: today().slice(0, 8) + '01',
        periodEnd: today(),
        activityValue: null,
        activityUnit: '',
        unitConvertRate: 1,
        emissionFactor: null,
        factorUnit: '',
        allocationRatio: 100,
        evidenceUrl: '',
        sourceNo: '',
        remark: '',
        status: 'DRAFT'
      }
    },
    async handleTemplateChange() {
      this.selectedNode = null
      await this.loadTree()
    },
    async loadTree() {
      this.loadingTree = true
      this.serviceError = ''
      try {
        const trees = await collectionApi.trees({ silent: true })
        this.rawTree = { id: 'collection-root', name: '能耗数据采集点', nodeType: 'root', children: trees }
        this.expandedKeys = [this.rawTree.id].concat(trees.map(tree => tree.id))
        this.selectFirstNode()
      } catch (error) {
        this.rawTree = null
        this.selectedNode = null
        this.serviceError = this.resolveServiceError(error)
      } finally {
        this.loadingTree = false
      }
    },
    selectFirstNode() {
      this.$nextTick(() => {
        const candidates = flattenCarbonTree(this.filteredTree[0] || {}).filter(item => this.isEntryNode(item))
        const first = candidates[0]
        if (first) {
          this.selectNode(first)
        }
      })
    },
    handleNodeClick(data) {
      if (!this.isEntryNode(data)) return
      this.selectNode(data)
    },
    selectNode(node) {
      this.selectedNode = node
      this.resetEntryForm()
      this.$nextTick(() => {
        if (this.$refs.nodeTree) {
          this.$refs.nodeTree.setCurrentKey(node.id)
        }
      })
      this.loadHistory()
      this.loadPending()
    },
    resetEntryForm() {
      const form = this.emptyForm()
      form.nodeId = this.selectedNode ? this.selectedNode.id : null
      form.activityUnit = this.selectedConfig.measurementUnit || ''
      form.emissionFactor = this.selectedConfig.carbonEmissionFactor || 0
      form.factorUnit = this.selectedConfig.carbonEmissionFactorDescription || 'tCO2e/unit'
      form.allocationRatio = this.selectedConfig.allocationRatio || 100
      form.periodEnd = this.periodEndByType(form.periodType, form.periodStart)
      this.form = form
      this.$nextTick(() => this.$refs.entryForm && this.$refs.entryForm.clearValidate())
    },
    syncPeriodEnd() {
      if (this.form.periodType !== 'CUSTOM') {
        this.form.periodEnd = this.periodEndByType(this.form.periodType, this.form.periodStart)
      }
    },
    periodEndByType(type, startText) {
      const start = parseDate(startText)
      if (!start) return ''
      const end = new Date(start.getTime())
      if (type === 'MONTH') {
        end.setMonth(start.getMonth() + 1, 0)
      } else if (type === 'QUARTER') {
        const quarterStart = Math.floor(start.getMonth() / 3) * 3
        end.setMonth(quarterStart + 3, 0)
      } else if (type === 'YEAR') {
        end.setMonth(11, 31)
      }
      return formatDate(end)
    },
    buildPayload(status) {
      return Object.assign({}, this.form, {
        nodeId: this.selectedNode.id,
        dataDate: this.form.periodStart,
        actualValue: Number(this.form.activityValue),
        carbonEmission: Number(this.estimatedEmission.toFixed(6)),
        calculatedValue: Number(this.estimatedEmission.toFixed(6)),
        dataSource: 'MANUAL',
        qualityScore: status === 'DRAFT' ? 0.8 : 1,
        status,
        createdBy: this.operatorId(),
        updatedBy: this.operatorId()
      })
    },
    saveEntry(status) {
      if (!this.canEnterSelected) {
        this.$message.warning('当前采集点不允许人工录入')
        return
      }
      this.$refs.entryForm.validate(async valid => {
        if (!valid) return
        this.saving = true
        try {
          const result = await collectionApi.manual({
            collectionPointType: this.selectedNode.collectionPointType,
            collectionPointId: this.selectedNode.collectionPointId,
            readingValue: this.form.activityValue,
            collectionTime: `${this.form.periodStart}T00:00:00`
          })
          this.$message.success(result && result.message ? result.message : '人工采集数据已提交，等待审核')
          this.resetEntryForm()
          this.loadHistory()
          this.loadPending()
        } finally {
          this.saving = false
        }
      })
    },
    async loadHistory() {
      if (!this.selectedNode) return
      this.loadingRecords = true
      try {
        const rows = await collectionApi.latest(this.selectedNode.collectionPointType, this.selectedNode.collectionPointId)
        this.historyRecords = (rows || []).map(row => {
          const collectionStatus = Number(row.collectionStatus !== undefined ? row.collectionStatus : row.collection_status)
          const readingValue = row.readingValue !== undefined ? row.readingValue : row.reading_value
          const collectionTime = row.collectionTime || row.collection_time
          const meterReadingMethod = Number(row.meterReadingMethod !== undefined ? row.meterReadingMethod : row.meter_reading_method)
          return Object.assign({}, row, {
            collectionStatus,
            meterReadingMethod,
            workflowStatus: row.workflowStatus || 'APPROVED',
            status: row.workflowStatus || (collectionStatus === 1 ? 'APPROVED' : 'REJECTED'),
            activityValue: readingValue,
            activityUnit: row.measurementUnit || row.measurement_unit || this.selectedConfig.measurementUnit,
            periodStart: collectionTime,
            periodEnd: collectionTime,
            periodType: Number(row.isCumulative !== undefined ? row.isCumulative : this.selectedNode.isCumulative) === 1 ? 'DAY' : 'CUSTOM'
          })
        })
        this.historyTotal = this.historyRecords.length
      } catch (error) {
        this.historyRecords = []
        this.historyTotal = 0
        this.serviceError = this.resolveServiceError(error)
      } finally {
        this.loadingRecords = false
      }
    },
    async loadPending() {
      if (!this.selectedNode || !this.canReviewData) {
        this.pendingRecords = []
        return
      }
      try {
        const rows = await collectionApi.pending(this.selectedNode.collectionPointType, this.selectedNode.collectionPointId, { silent: true })
        this.pendingRecords = (rows || []).map(row => Object.assign({}, row, {
          activityValue: row.readingValue,
          activityUnit: row.measurementUnit,
          periodStart: row.collectionTime,
          periodEnd: row.collectionTime,
          periodType: Number(row.isCumulative) === 1 ? 'DAY' : 'CUSTOM',
          status: row.workflowStatus || 'SUBMITTED'
        }))
      } catch (error) {
        this.pendingRecords = []
      }
    },
    handleHistoryQuery() {
      this.historyQuery.page = 1
      this.loadHistory()
    },
    resetHistoryQuery() {
      this.historyQuery.status = ''
      this.historyQuery.dateRange = []
      this.historyQuery.page = 1
      this.loadHistory()
    },
    handleTabClick(tab) {
      if (tab.name === 'review') this.loadPending()
      if (tab.name === 'history') this.loadHistory()
    },
    editRecord(row) {
      this.activeTab = 'single'
      this.form = Object.assign(this.emptyForm(), row, {
        activityValue: row.activityValue || row.actualValue,
        remark: row.remark || row.remarks || '',
        periodStart: row.periodStart || row.dataDate,
        periodEnd: row.periodEnd || row.dataDate
      })
      this.$nextTick(() => this.$refs.entryForm && this.$refs.entryForm.clearValidate())
    },
    async submitRecord(row) {
      await this.$confirm('确认提交该记录进入审核？', '系统提示', { type: 'warning' })
      await collectionApi.manual({
        collectionPointType: row.collectionPointType,
        collectionPointId: row.collectionPointId,
        readingValue: row.activityValue || row.readingValue,
        collectionTime: row.collectionTime
      })
      this.$message.success('已提交审核')
      this.loadHistory()
      this.loadPending()
    },
    async approveRecord(row) {
      await this.$confirm('确认审核通过该记录？', '系统提示', { type: 'warning' })
      await collectionApi.approve(row.id, { comment: '审核通过' })
      this.$message.success('审核已通过')
      this.loadHistory()
      this.loadPending()
    },
    openReject(row) {
      this.rejectTarget = row
      this.rejectComment = ''
      this.rejectVisible = true
    },
    async rejectRecord() {
      if (!this.rejectComment) {
        this.$message.warning('请输入驳回原因')
        return
      }
      this.saving = true
      try {
        await collectionApi.reject(this.rejectTarget.id, { comment: this.rejectComment })
        this.$message.success('已驳回')
        this.rejectVisible = false
        this.loadHistory()
        this.loadPending()
      } finally {
        this.saving = false
      }
    },
    async lockRecord(row) {
      await this.$confirm('锁定后该记录不可继续编辑，是否继续？', '系统提示', { type: 'warning' })
      await emissionApi.lock(row.id, { operatorId: this.operatorId(), comment: '锁定归档' })
      this.$message.success('记录已锁定')
      this.loadHistory()
    },
    async voidRecord(row) {
      await this.$confirm('确认作废该记录？作废后不再参与统计。', '系统提示', { type: 'warning' })
      await emissionApi.voidEntry(row.id, { operatorId: this.operatorId(), comment: '人工作废' })
      this.$message.success('记录已作废')
      this.loadHistory()
      this.loadPending()
    },
    async viewAudits(row) {
      this.auditLogs = await collectionApi.audits(row.id)
      this.auditVisible = true
    },
    downloadImportTemplate() {
      const header = ['节点编码/采集点编码', '统计周期类型', '开始日期', '结束日期', '活动数据', '计量单位', '排放因子', '凭证编号/附件名', '备注']
      const sampleCode = this.selectedConfig.equipmentCode || (this.selectedNode && this.selectedNode.id) || ''
      const sample = [sampleCode, 'MONTH', today().slice(0, 8) + '01', today(), '100', this.selectedConfig.measurementUnit || 'kWh', this.selectedConfig.carbonEmissionFactor || '', '台账-001', '']
      this.downloadText([header, sample].map(row => row.join(',')).join('\n'), '人工数据录入导入模板.csv', 'text/csv;charset=utf-8')
    },
    handleImportFile(event) {
      const file = event.target.files[0]
      if (!file) return
      const reader = new FileReader()
      reader.onload = e => {
        this.parseImportText(e.target.result)
        event.target.value = ''
      }
      reader.readAsText(file, 'utf-8')
    },
    parseImportText(text) {
      this.importRows = []
      this.importErrors = []
      const lines = String(text || '').replace(/^\uFEFF/, '').split(/\r?\n/).filter(line => line.trim())
      if (lines.length < 2) {
        this.importErrors = ['导入文件没有数据行']
        return
      }
      const headers = this.parseCsvLine(lines[0])
      this.importRows = lines.slice(1).map((line, index) => {
        const values = this.parseCsvLine(line)
        const row = {}
        headers.forEach((header, i) => {
          row[header] = values[i]
        })
        return this.mapImportRow(row, index + 2)
      })
      this.importErrors = this.importRows.filter(row => row._error).map(row => `第${row._row}行：${row._error}`)
    },
    parseCsvLine(line) {
      const values = []
      let current = ''
      let quoted = false
      for (let i = 0; i < line.length; i++) {
        const char = line[i]
        if (char === '"' && line[i + 1] === '"') {
          current += '"'
          i++
        } else if (char === '"') {
          quoted = !quoted
        } else if (char === ',' && !quoted) {
          values.push(current.trim())
          current = ''
        } else {
          current += char
        }
      }
      values.push(current.trim())
      return values
    },
    mapImportRow(row, rowNumber) {
      const node = this.resolveImportNode(row['节点编码/采集点编码'])
      const periodType = (row['统计周期类型'] || 'MONTH').toUpperCase()
      const activityValue = Number(row['活动数据'])
      const mapped = {
        _row: rowNumber,
        nodeId: node && node.id,
        nodeName: node && node.name,
        periodType,
        periodStart: row['开始日期'],
        periodEnd: row['结束日期'] || this.periodEndByType(periodType, row['开始日期']),
        activityValue,
        activityUnit: row['计量单位'] || (node && node.config && node.config.measurementUnit),
        unitConvertRate: 1,
        emissionFactor: row['排放因子'] ? Number(row['排放因子']) : (node && node.config && node.config.carbonEmissionFactor),
        factorUnit: node && node.config && node.config.carbonEmissionFactorDescription,
        allocationRatio: (node && node.config && node.config.allocationRatio) || 100,
        sourceNo: row['凭证编号/附件名'],
        remark: row['备注'],
        dataSource: 'MANUAL',
        status: 'DRAFT',
        createdBy: this.operatorId(),
        updatedBy: this.operatorId()
      }
      mapped.carbonEmission = Number(((mapped.activityValue || 0) * (mapped.emissionFactor || 0) * ((mapped.allocationRatio || 100) / 100)).toFixed(6))
      mapped.calculatedValue = mapped.carbonEmission
      mapped.actualValue = mapped.activityValue
      mapped.dataDate = mapped.periodStart
      mapped._error = this.importRowError(mapped)
      return mapped
    },
    resolveImportNode(code) {
      if (!code && this.selectedNode) return this.selectedNode
      return this.allEntryNodes.find(node => {
        const config = node.config || {}
        const info = node.nodeInfo || {}
        return String(node.id) === String(code) || config.equipmentCode === code || info.nodeCode === code
      })
    },
    importRowError(row) {
      if (!row.nodeId) return '未匹配到节点'
      if (!row.periodStart || !row.periodEnd) return '统计周期不完整'
      if (Number.isNaN(row.activityValue) || row.activityValue < 0) return '活动数据不合法'
      if (!row.activityUnit) return '计量单位不能为空'
      if (row.emissionFactor === undefined || row.emissionFactor === null || Number.isNaN(Number(row.emissionFactor))) return '排放因子不合法'
      return ''
    },
    async importBatch() {
      this.importing = true
      try {
        const result = await emissionApi.batchCreate(this.validImportRows)
        this.$message.success(`导入完成：成功 ${result.success || 0} 条，失败 ${result.failed || 0} 条`)
        this.importErrors = result.errors || []
        this.importRows = []
        this.loadHistory()
      } finally {
        this.importing = false
      }
    },
    filterManualTree(node) {
      if (!node) return null
      const children = (node.children || []).map(child => this.filterManualTree(child)).filter(Boolean)
      const entry = this.isEntryNode(node)
      if (entry && this.manualOnly && !this.isManualNode(node)) {
        return null
      }
      if (!entry && this.manualOnly && !children.length) {
        return null
      }
      return Object.assign({}, node, { children })
    },
    filterNode(value, data) {
      if (!value) return true
      return String(data.name || '').indexOf(value) !== -1
    },
    isEntryNode(node) {
      return node && node.nodeType === 'meter'
    },
    setTreeExpansion(expanded) {
      const keys = expanded
        ? flattenCarbonTree(this.rawTree || {}).filter(node => node.children && node.children.length).map(node => node.id)
        : []
      this.expandedKeys = keys
      this.$nextTick(() => {
        const store = this.$refs.nodeTree && this.$refs.nodeTree.store
        if (!store || !store.nodesMap) return
        Object.keys(store.nodesMap).forEach(key => {
          store.nodesMap[key].expanded = expanded
        })
      })
    },
    isManualNode(node) {
      return node && Number(node.meterReadingMethod) === 0
    },
    nodeIcon(node) {
      if (!this.isEntryNode(node)) return 'el-icon-folder'
      return this.isManualNode(node) ? 'el-icon-edit-outline' : 'el-icon-connection'
    },
    categoryUnits(category) {
      const map = {
        '购入的电力': ['kWh', 'MWh', 'GWh'],
        '购入的热力': ['GJ', 'MJ', '吨'],
        '化石燃料': ['t', 'kg', 'L', 'Nm3', '104 Nm3'],
        '废弃物处理': ['t', 'm3']
      }
      return map[category] || ['kWh', 'MWh', 'GJ', 't', 'kg', 'm3']
    },
    canEdit(row) {
      return row.status === 'DRAFT' || row.status === 'REJECTED'
    },
    canSubmit(row) {
      return row.status === 'DRAFT' || row.status === 'REJECTED'
    },
    canVoid(row) {
      return row.status !== 'VOIDED' && row.status !== 'LOCKED'
    },
    statusLabel(value) {
      if (!value) return '-'
      const item = this.statusOptions.find(option => option.value === value)
      return item ? item.label : value
    },
    statusType(value) {
      const item = this.statusOptions.find(option => option.value === value)
      return item ? item.type : 'info'
    },
    collectionStatusLabel(row) {
      if (row.workflowStatus === 'SUBMITTED') return '待审核'
      if (row.workflowStatus === 'REJECTED') return '已驳回'
      const status = Number(row.collectionStatus)
      if (status === 1) return Number(row.meterReadingMethod) === 0 ? '人工录入成功' : '自动采集成功'
      if (status === 2) return '自动采集失败'
      if (status === 3) return '已取消采集'
      return '待采集'
    },
    collectionStatusType(row) {
      const status = Number(row.collectionStatus)
      if (status === 1) return 'success'
      if (status === 2) return 'danger'
      if (status === 3) return 'info'
      return 'warning'
    },
    periodLabel(value) {
      const item = this.periodOptions.find(option => option.value === value)
      return item ? item.label : value
    },
    periodText(row) {
      return `${this.periodLabel(row.periodType)} ${row.periodStart || row.dataDate || '-'} 至 ${row.periodEnd || row.dataDate || '-'}`
    },
    auditActionLabel(action) {
      const map = {
        CREATE: '创建',
        UPDATE: '修改',
        SUBMIT: '提交',
        APPROVE: '审核通过',
        REJECT: '驳回',
        LOCK: '锁定',
        VOID: '作废',
        MANUAL_ENTRY: '人工录入',
        AUTO_COLLECTION: '自动采集'
      }
      return map[action] || action
    },
    auditStatusLabel(value) {
      const map = {
        NOT_COLLECTED: '未采集',
        PENDING: '待采集',
        COLLECTED: '采集成功',
        FAILED: '采集失败',
        CANCELLED: '已取消'
      }
      return map[value] || this.statusLabel(value)
    },
    formatNumber(value) {
      if (value === undefined || value === null || value === '') return '-'
      return Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 6 })
    },
    formatRatio(value) {
      if (value === undefined || value === null || value === '') return '-'
      return `${Number(value).toFixed(2)}%`
    },
    downloadText(content, filename, type) {
      const blob = new Blob(['\uFEFF' + content], { type })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      link.click()
      URL.revokeObjectURL(url)
    },
    resolveServiceError(error) {
      const response = error && error.response
      const data = response && response.data
      if (typeof data === 'string' && data.indexOf('Proxy error') !== -1) {
        return '碳排放服务未启动或代理配置异常，请确认后端服务已启动后再刷新页面。'
      }
      return (data && (data.message || data.error)) || '碳排放数据暂时无法加载，请稍后重试。'
    }
  }
}
</script>

<style scoped lang="scss">
.carbon-data-entry {
  height: calc(100vh - 84px);
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-sizing: border-box;
  background: #f6f8fb;
}

.carbon-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  margin-bottom: 16px;

  h2 {
    margin: 0 0 6px;
    color: #1f2d3d;
    font-size: 22px;
  }

  span {
    color: #7a8797;
  }
}

.toolbar-actions {
  display: flex;
  gap: 8px;

  .el-button {
    min-height: 36px;
    padding: 0 16px;
    white-space: nowrap;
  }
}

.service-alert {
  margin-bottom: 16px;
}

.entry-workbench {
  flex: 1 1 auto;
  height: 0;
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 16px;
  align-items: stretch;
  min-height: 0;
}

.node-panel,
.entry-main,
.caliber-card,
.entry-section {
  border: 1px solid #e5eaf1;
  border-radius: 6px;
  background: #fff;
}

.node-panel {
  min-height: 0;
  height: 100%;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  padding: 16px;
  overflow: hidden;
}

.panel-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  color: #1f2d3d;
  font-weight: 700;

  small {
    color: #8b97a8;
    font-weight: 400;
  }
}

.template-select,
.tree-search,
.manual-filter {
  width: 100%;
  margin-bottom: 12px;
}

.tree-source-tip {
  margin-bottom: 8px;
  color: #7a8797;
  font-size: 12px;
}

.tree-actions {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;

  .el-button {
    flex: 1;
    margin-left: 0;
    min-height: 34px;
    padding: 0 10px;
    white-space: nowrap;
  }
}

.entry-disabled-alert {
  margin-bottom: 14px;
}

.entry-form-fieldset {
  min-width: 0;
  margin: 0;
  padding: 0;
  border: 0;
}

.readonly-control {
  ::v-deep .el-input__inner,
  ::v-deep textarea {
    color: #1f2d3d;
    background: #fff;
    cursor: default;
  }

  ::v-deep .el-textarea__inner {
    color: #1f2d3d;
    background: #fff;
    cursor: default;
  }
}

.node-tree {
  flex: 1;
  min-height: 0;
  margin-top: 6px;
  overflow-y: auto;
  overflow-x: hidden;

  ::v-deep .el-tree-node__content {
    height: 36px;
    border-radius: 5px;
  }
}

.tree-node {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  width: 100%;

  i {
    flex: 0 0 auto;
    color: #2265b4;
  }

  span {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.entry-main {
  min-width: 0;
  min-height: 0;
  height: 100%;
  overflow-y: auto;
  padding: 16px;
}

.caliber-card {
  margin-bottom: 16px;
  padding: 18px;
}

.caliber-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;

  h3 {
    margin: 5px 0 0;
    color: #1f2d3d;
    font-size: 20px;
  }
}

.eyebrow {
  color: #6b7788;
  font-size: 12px;
  font-weight: 700;
}

.caliber-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;

  > div {
    min-width: 0;
    padding: 12px;
    border-radius: 6px;
    background: #f8fafc;
  }

  span {
    display: block;
    margin-bottom: 6px;
    color: #7a8797;
    font-size: 12px;
  }

  strong {
    display: block;
    color: #1f2d3d;
    overflow-wrap: anywhere;
  }
}

.entry-tabs {
  ::v-deep .el-tabs__header {
    margin-bottom: 12px;
  }
}

.entry-section {
  padding: 16px;
}

.form-actions,
.batch-toolbar {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 8px;
  flex-wrap: nowrap;

  .el-button {
    min-height: 36px;
    padding: 0 16px;
    white-space: nowrap;
  }
}

.batch-toolbar {
  justify-content: flex-start;
  margin-bottom: 12px;

  span {
    color: #7a8797;
  }
}

.file-input {
  display: none;
}

.import-alert {
  margin-bottom: 12px;
}

.history-filter {
  margin-bottom: 8px;
}

.table-pagination {
  margin-top: 16px;
  text-align: right;
}

.audit-item {
  strong,
  span {
    display: block;
  }

  span {
    margin-top: 4px;
    color: #6b7788;
  }

  p {
    margin: 8px 0 0;
    color: #1f2d3d;
    line-height: 1.6;
  }
}

@media (max-width: 1100px) {
  .entry-workbench {
    grid-template-columns: 280px minmax(0, 1fr);
  }

  .caliber-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .carbon-toolbar,
  .caliber-head,
  .toolbar-actions,
  .form-actions,
  .batch-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .entry-workbench,
  .caliber-grid {
    grid-template-columns: 1fr;
  }
}
</style>
