<template>
  <div class="template-list-container">
    <div v-if="!embedded" class="header">
      <div class="header-left">
        <el-button @click="$emit('back')" :icon="ArrowLeft" circle />
        <h1>碳排放核算模版管理</h1>
      </div>
      <div class="user-info">
        <span>当前用户: {{ currentUser?.nickName || currentUser?.userName || currentUser?.name }}</span>
        <el-button @click="handleLogout" link>退出登录</el-button>
      </div>
    </div>

    <el-alert
      v-if="!canEdit"
      title="当前账号只有查看权限，模板的新建、编辑和删除操作不可用"
      type="warning"
      show-icon
      :closable="false"
      class="permission-alert"
    />

    <div class="toolbar">
      <el-button @click="handleNewTemplate(2)" type="primary" :disabled="!canEdit" title="需要碳排放模型编辑权限">新建核算模版</el-button>
      <el-button @click="handleNewTemplate(1)" type="primary" :disabled="!canEdit" title="需要碳排放模型编辑权限">新建节点模版</el-button>
      <el-button @click="handleOpenTemplate" :disabled="!selectedTemplate">打开模版</el-button>
      <el-button @click="openCompanyOwnership" :disabled="!canEdit || !selectedTemplate">设置归属公司</el-button>
      <el-button
        type="primary"
        @click="setStatisticsBaseline"
        :loading="baselineSaving"
        :disabled="!canEdit || !isCalcSelected || !selectedTemplate?.companyDeptId || isBaselineSelected"
        title="设置为该分公司统计查询和预测模型的默认核算模版"
      >{{ isBaselineSelected ? '已是统计基准模版' : '设置为统计基准模版' }}</el-button>
      <el-button @click="handleSaveAs" :disabled="!canEdit || !selectedTemplate" title="需要碳排放模型编辑权限">另存为</el-button>
      <el-button @click="handleDeleteTemplate" :disabled="!canEdit || !selectedTemplate" type="danger" title="需要碳排放模型编辑权限">删除当前模版</el-button>
      <el-button
        @click="handleValidateTemplate"
        :disabled="!canValidate || !isCalcSelected"
        :loading="validating"
        type="warning"
        title="仅核算模版支持校验"
      >校验模版</el-button>
      <el-button
        @click="handleViewValidationResult"
        :disabled="!isCalcSelected"
        type="info"
        title="查看选中核算模版最近一次校验结果"
      >校验结果查看</el-button>
      <el-button
        @click="openManualCalculation"
        :disabled="!canEdit || !isCalcSelected"
        type="success"
        title="按指定月份执行一次手动核算"
      >手动核算</el-button>
    </div>

    <div class="template-list">
      <table>
        <thead>
          <tr>
            <th>选择</th>
            <th>模版名称</th>
            <th>归属公司</th>
            <th>模版类型</th>
            <th>最后修改人</th>
            <th>最后修改时间</th>
            <th>版本</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="template in templates"
            :key="template.id"
            :class="{ selected: selectedTemplate?.id === template.id }"
            @click="selectTemplate(template)"
            @dblclick="handleDoubleClick(template)"
          >
            <td><el-radio :value="template.id" v-model="selectedId" >{{ template.id }}</el-radio></td>
            <td>{{ template.name }}</td>
            <td>{{ template.companyName || '待指定公司' }}</td>
            <td>
              <el-tag :type="getTemplateType(template.templateType).tagType">
                {{ getTemplateType(template.templateType).label }}
              </el-tag>
            </td>
            <td>{{ template.updatedByName }}</td>
            <td>{{ formatDate(template.updatedAt) }}</td>
            <td>{{ template.version }}</td>
            <td>
              <el-tag :type="template.enabled ? 'success' : 'danger'">
                {{ template.enabled ? '启用' : '停用' }}
              </el-tag>
            </td>
            <td>
              <el-button
                @click.stop="handleEditTemplate(template)"
                link
                size="small"
                :disabled="!canEdit"
                title="需要碳排放模型编辑权限"
              >编辑</el-button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-if="templates.length === 0" class="empty-tip">
        <el-empty description="暂无模版" />
      </div>
    </div>

    <el-dialog v-model="showNewModal" :title="newTemplateForm.templateType === 2 ? '新建核算模版' : '新建节点模版'" width="400px">
      <el-form :model="newTemplateForm">
        <el-form-item label="归属公司">
          <el-select v-model="newTemplateForm.companyDeptId" :loading="companiesLoading" :disabled="!companiesReady" placeholder="请选择归属公司" clearable>
            <el-option v-for="company in companies" :key="company.deptId" :label="company.deptName" :value="company.deptId" />
          </el-select>
          <span v-if="companiesError" class="text-muted">{{ companiesError }}</span>
        </el-form-item>

        <el-form-item label="模版名称">
          <el-input v-model="newTemplateForm.name" placeholder="请输入模版名称" />
        </el-form-item>
        <el-form-item label="模版类型">
          <el-select v-model="newTemplateForm.templateType" disabled placeholder="请选择模版类型">
            <el-option label="节点模版" :value="1" />
            <el-option label="核算模版" :value="2" />
          </el-select>
          <span class="text-muted">
            {{ newTemplateForm.templateType === 2 ? '（实现碳排放自动化核算功能，支持树形节点管理、属性配置及计划任务调度）' : '（仅用于构建层级关系，作为结构被引用，不参与碳排放自动化核算）' }}
          </span>
        </el-form-item>
        <el-form-item label="描述信息">
          <el-input v-model="newTemplateForm.description" type="textarea" placeholder="请输入描述信息" :rows="3" />
        </el-form-item>
      </el-form>
      <div slot="footer" class="dialog-footer">
        <el-button @click="showNewModal = false">取消</el-button>
        <el-button type="primary" :loading="newSubmitting" :disabled="newSubmitting || !companiesReady" @click="confirmNewTemplate">确定</el-button>
      </div>
    </el-dialog>

    <el-dialog v-model="showSaveAsModal" title="另存为" width="400px">
      <el-form :model="saveAsForm">
        <el-form-item label="归属公司">
          <el-select v-model="saveAsForm.companyDeptId" :loading="companiesLoading" :disabled="!companiesReady" placeholder="请选择归属公司" clearable>
            <el-option v-for="company in companies" :key="company.deptId" :label="company.deptName" :value="company.deptId" />
          </el-select>
          <span v-if="companiesError" class="text-muted">{{ companiesError }}</span>
        </el-form-item>

        <el-form-item label="新模版名称">
          <el-input v-model="saveAsForm.name" placeholder="请输入新模版名称" />
        </el-form-item>
      </el-form>
      <div slot="footer" class="dialog-footer">
        <el-button @click="showSaveAsModal = false">取消</el-button>
        <el-button type="primary" :loading="copySubmitting" :disabled="copySubmitting || !companiesReady" @click="confirmSaveAs">确定</el-button>
      </div>
    </el-dialog>

    <el-dialog v-model="companyVisible" title="设置模板归属公司" width="540px" :close-on-click-modal="false" :before-close="closeCompanyOwnership">
      <p>模板：{{ ownershipForm.name }}。公司归属参与现有数据权限。已有公司快照的任务不会被重新归类。</p>
      <el-form :disabled="ownershipSaving">
        <el-form-item label="归属公司">
          <el-select v-model="ownershipForm.companyDeptId" :loading="companiesLoading" :disabled="!companiesReady" placeholder="请选择归属公司" clearable>
            <el-option v-for="company in companies" :key="company.deptId" :label="company.deptName" :value="company.deptId" />
          </el-select>
          <span v-if="companiesError" class="text-muted">{{ companiesError }}</span>
        </el-form-item>
        <el-checkbox v-model="ownershipForm.confirmLegacyTasks">我已核对，该模板尚未确认公司归属的历史任务也属于此公司</el-checkbox>
        <p class="text-muted">不勾选时只设置模板及后续新任务。旧报告的数据来源和已保存结果保持原样。</p>
      </el-form>
      <template #footer>
        <el-button :disabled="ownershipSaving" @click="companyVisible = false">取消</el-button>
        <el-button type="primary" :loading="ownershipSaving" :disabled="!companiesReady || !ownershipForm.companyDeptId" @click="saveCompanyOwnership">保存归属</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showDeleteConfirm" title="确认删除">
      <p>确定要删除该模版吗？此操作不可恢复。</p>
      <div slot="footer" class="dialog-footer">
        <el-button @click="showDeleteConfirm = false">取消</el-button>
        <el-button type="danger" @click="confirmDelete">确定删除</el-button>
      </div>
    </el-dialog>

    <el-dialog v-model="showEditModal" :title="'编辑模版属性（' + (editForm.templateType === 2 ? '核算模版' : '节点模版') + '）'" width="45%">
      <el-form :model="editForm" label-width="120px">
        <el-form-item label="模版名称">
          <el-input v-model="editForm.name" disabled />
        </el-form-item>

        <el-form-item label="描述信息">
          <el-input v-model="editForm.description" type="textarea" placeholder="请输入描述信息" :rows="2" />
        </el-form-item>

        <el-form-item label="是否启用">
          <el-radio-group v-model="editForm.enabled">
            <el-radio :value="true">启用</el-radio>
            <el-radio :value="false">停用</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item v-if="editForm.templateType === 2" label="碳排放因子模版">
          <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
            <el-tag v-if="editForm.factorTemplateId" type="success" size="small">
              {{ factorTemplateName(editForm.factorTemplateId) || ('ID: ' + editForm.factorTemplateId) }}
            </el-tag>
            <span v-else class="text-muted">未选择</span>
            <el-button type="primary" size="small" @click="openFactorTemplateSelect">选择碳排放因子模版</el-button>
            <el-button v-if="editForm.factorTemplateId" size="small" @click="editForm.factorTemplateId = null">清除</el-button>
          </div>
        </el-form-item>

        <el-form-item v-if="editForm.templateType === 2" label="自动核算">
          <el-checkbox v-model="editForm.taskConfig.autoCalculationEnabled">
            启用自动核算
          </el-checkbox>
          <span class="text-muted">未勾选时仅允许手动核算，不会因数据变化或到达计划时间自动执行</span>
        </el-form-item>

        <el-form-item v-if="editForm.templateType === 2" label="统计基准模版">
          <el-button
            type="primary"
            size="small"
            :loading="baselineSaving"
            :disabled="!canEdit || !editForm.companyDeptId || isBaselineSelected"
            @click="setStatisticsBaseline"
          >{{ isBaselineSelected ? '已是统计基准模版' : '设置为统计基准模版' }}</el-button>
          <span v-if="!editForm.companyDeptId" class="text-muted">请先设置归属公司</span>
          <span v-else class="text-muted">仅写入系统参数，不修改碳排放核算因子库</span>
        </el-form-item>

        <el-collapse
          v-if="editForm.templateType === 2 && editForm.taskConfig.autoCalculationEnabled"
          v-model="taskCollapse"
        >
            <el-collapse-item title="计划任务配置" name="1">
              <el-form :model="editForm.taskConfig" label-width="100px">
                <el-row :gutter="20">
                  <el-col :span="12">
                    <el-form-item label="起始日期">
                      <el-date-picker
                        v-model="editForm.taskConfig.startDate"
                        type="datetime"
                        placeholder="选择起始日期"
                        format="YYYY-MM-DD HH:mm"
                        value-format="YYYY-MM-DDTHH:mm"
                        style="width: 100%"
                      />
                      <span v-if="!editForm.taskConfig.startDate" class="text-muted">为空表示立即生效</span>
                    </el-form-item>
                  </el-col>
                  <el-col :span="12">
                    <el-form-item label="截止日期">
                      <el-date-picker
                        v-model="editForm.taskConfig.endDate"
                        type="datetime"
                        placeholder="选择截止日期（可选）"
                        format="YYYY-MM-DD HH:mm"
                        value-format="YYYY-MM-DDTHH:mm"
                        style="width: 100%"
                      />
                      <span v-if="!editForm.taskConfig.endDate" class="text-muted">无限制</span>
                    </el-form-item>
                  </el-col>
                </el-row>

                <el-form-item label="执行周期">
                  <el-select v-model="editForm.taskConfig.cycleType" @change="handleCycleChange">
                    <el-option label="按日" value="DAILY" />
                    <el-option label="按周" value="WEEKLY" />
                    <el-option label="按月" value="MONTHLY" />
                    <el-option label="按季" value="QUARTERLY" />
                    <el-option label="按年" value="YEARLY" />
                  </el-select>
                  <!-- 执行日期已固定为对应计量周期的第一天，由程序自动填写，暂不提供人工选择 -->
                  <span class="text-muted">{{ fixedExecutionDateHint }}</span>
                </el-form-item>

                <!-- 执行日期选择已隐藏（固定为计量周期第一天，自动填写）；如需恢复人工选择，将 v-if="false" 移除即可 -->
                <el-form-item v-if="false && editForm.taskConfig.cycleType === 'WEEKLY'" label="周执行日期">
                  <el-checkbox-group v-model="editForm.taskConfig.weekdays">
                    <el-checkbox label="周一" value="1" />
                    <el-checkbox label="周二" value="2" />
                    <el-checkbox label="周三" value="3" />
                    <el-checkbox label="周四" value="4" />
                    <el-checkbox label="周五" value="5" />
                    <el-checkbox label="周六" value="6" />
                    <el-checkbox label="周日" value="0" />
                  </el-checkbox-group>
                </el-form-item>

                <el-form-item v-if="false && (editForm.taskConfig.cycleType === 'MONTHLY' || editForm.taskConfig.cycleType === 'QUARTERLY')" label="月执行日期">
                  <el-input v-model="editForm.taskConfig.monthDays" placeholder="如：1,5,15" />
                  <span class="text-muted">多个日期用逗号分隔</span>
                </el-form-item>

                <el-form-item v-if="false && editForm.taskConfig.cycleType === 'YEARLY'" label="年执行日期">
                  <el-input v-model="editForm.taskConfig.yearMonths" placeholder="如：1-15,6-15" />
                  <span class="text-muted">格式：月份-日期，多个用逗号分隔</span>
                </el-form-item>

                <el-row :gutter="20">
                  <el-col :span="8">
                    <el-form-item label="执行时间">
                      <el-time-picker
                        v-model="editForm.taskConfig.executionTime"
                        format="HH:mm"
                        value-format="HH:mm"
                        :editable="true"
                        style="width: 100%"
                      />
                    </el-form-item>
                  </el-col>
                  <el-col :span="8">
                    <el-form-item v-if="editForm.taskConfig.cycleType === 'WEEKLY'" label="重复间隔">
                      <el-input v-model="editForm.taskConfig.interval" type="number" placeholder="每N周执行一次" style="width: 100%" />
                    </el-form-item>
                    <el-form-item v-if="editForm.taskConfig.cycleType === 'MONTHLY'" label="重复间隔">
                      <el-input v-model="editForm.taskConfig.interval" type="number" placeholder="每N个月执行一次" style="width: 100%" />
                    </el-form-item>
                  </el-col>
                  <el-col :span="8">
                    <el-form-item label="延迟核算日期">
                      <el-input
                        v-model="editForm.taskConfig.delayDays"
                        type="number"
                        :min="0"
                        placeholder="宽限期天数"
                      >
                        <template #append>天</template>
                      </el-input>
                      <span class="text-muted">统计周期结束后宽限期，默认3天</span>
                    </el-form-item>
                  </el-col>
                </el-row>
              </el-form>
            </el-collapse-item>
          </el-collapse>
      </el-form>
      <div slot="footer" class="dialog-footer">
        <el-button @click="showEditModal = false">取消</el-button>
        <el-button type="primary" :loading="editSubmitting" :disabled="editSubmitting" @click="confirmEdit">确定</el-button>
      </div>
    </el-dialog>

    <!-- 碳排放因子模版选择弹窗 -->
    <el-dialog v-model="factorTemplateSelectVisible" title="碳排放因子模版选择" width="880px" append-to-body>
      <div style="margin-bottom: 12px;">
        <el-button type="success" size="small" @click="openNewFactorTemplate">新建模版</el-button>
        <el-button type="success" size="small" :disabled="!selectedFactorTemplate" @click="handleEditFactorBtn">编辑因子</el-button>
        <el-button type="warning" size="small" :disabled="!selectedFactorTemplate" @click="handleEditInfoBtn">编辑信息</el-button>
        <el-button type="info" size="small" :disabled="!selectedFactorTemplate" @click="handleCopyBtn">拷贝模版</el-button>
        <span class="text-muted" style="margin-left: 12px;">列表显示所有共享模版和自己创建的模版；先选中一行再操作。被其他用户核算模版引用的自有模版不可编辑。</span>
      </div>
      <el-table
        :data="factorTemplateList"
        v-loading="factorTemplateLoading"
        border
        stripe
        size="small"
        :max-height="420"
        @row-click="handleFactorTemplateRowClick"
      >
        <el-table-column width="55" align="center">
          <template #header>选择</template>
          <template #default="{ row }">
            <el-radio :value="row.id" v-model="selectedFactorTemplateId" @click.stop>
              <span></span>
            </el-radio>
          </template>
        </el-table-column>
        <el-table-column type="index" label="序号" width="55" align="center" />
        <el-table-column prop="templateName" label="模版名称" min-width="150" show-overflow-tooltip />
        <el-table-column prop="templateDescription" label="模版说明" min-width="160" show-overflow-tooltip />
        <el-table-column label="共享" width="70" align="center">
          <template #default="{ row }">
            <el-tag :type="row.isShared === 1 ? 'success' : 'info'" size="small">{{ row.isShared === 1 ? '共享' : '私有' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="归属" width="70" align="center">
          <template #default="{ row }">
            <el-tag :type="isOwnFactorTemplate(row) ? 'primary' : 'warning'" size="small">{{ isOwnFactorTemplate(row) ? '自己' : '他人' }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="lockedFactorTemplateIds.length > 0" class="text-muted" style="margin-top: 8px; color: #e6a23c;">
        提示：部分自有模版正在被其他用户创建的核算模版使用，其“编辑因子/编辑信息”已锁定。
      </div>
      <template #footer>
        <el-button @click="factorTemplateSelectVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!selectedFactorTemplate" @click="confirmSelectFactorTemplate">选择</el-button>
      </template>
    </el-dialog>

    <!-- 新建/编辑 因子模版信息弹窗 -->
    <el-dialog
      v-model="factorTemplateFormVisible"
      :title="factorTemplateForm.id ? '编辑因子模版信息' : '新建因子模版'"
      width="480px"
      append-to-body
    >
      <el-form :model="factorTemplateForm" label-width="90px">
        <el-form-item label="模版名称" required>
          <el-input v-model="factorTemplateForm.templateName" placeholder="请输入模版名称" maxlength="200" show-word-limit />
        </el-form-item>
        <el-form-item label="模版说明">
          <el-input v-model="factorTemplateForm.templateDescription" type="textarea" :rows="3" placeholder="模版用途说明（可选）" maxlength="1000" show-word-limit />
        </el-form-item>
        <el-form-item label="是否共享">
          <el-switch v-model="factorTemplateForm.isShared" :active-value="1" :inactive-value="0" active-text="共享" inactive-text="私有" />
        </el-form-item>
      </el-form>
      <div slot="footer" class="dialog-footer">
        <el-button @click="factorTemplateFormVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmFactorTemplateForm">保存</el-button>
      </div>
    </el-dialog>

    <!-- 拷贝因子模版弹窗 -->
    <el-dialog v-model="copyFactorTemplateVisible" title="拷贝因子模版" width="480px" append-to-body>
      <el-form :model="copyFactorTemplateForm" label-width="100px">
        <el-form-item label="源模版">
          <el-input :model-value="copyFactorTemplateForm.sourceName" disabled />
        </el-form-item>
        <el-form-item label="新模版名称" required>
          <el-input v-model="copyFactorTemplateForm.newName" placeholder="请输入新模版名称" maxlength="200" show-word-limit />
        </el-form-item>
      </el-form>
      <div slot="footer" class="dialog-footer">
        <el-button @click="copyFactorTemplateVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmCopyFactorTemplate">拷贝</el-button>
      </div>
    </el-dialog>

    <!-- 模版校验结果弹窗 -->
    <el-dialog v-model="validationResultVisible" :title="validationResultTitle" width="680px" append-to-body>
      <div v-if="validationResult && validationResult.checkResult > 0" class="validation-result-body">
        <div class="validation-summary">
          <el-tag :type="checkResultMeta.tagType" size="large">{{ checkResultMeta.label }}</el-tag>
          <span class="validation-time">校验时间：{{ formatDateTime(validationResult.checkTime) }}</span>
        </div>
        <!-- 富文本校验详情：错误-红、告警-橙、提示-蓝、通过-绿（颜色由后端HTML内联样式控制） -->
        <div class="validation-message" v-html="validationResult.checkMessage"></div>
      </div>
      <el-empty v-else description="该模版尚未执行校验，请先点击「校验模版」" />
      <template #footer>
        <el-button @click="validationResultVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="manualCalculationVisible" title="手动核算" width="460px" append-to-body>
      <el-form :model="manualCalculationForm" label-width="90px">
        <el-form-item label="核算模版">
          <el-input :model-value="selectedTemplate?.name || ''" disabled />
        </el-form-item>
        <el-form-item label="起始月份" required>
          <el-date-picker
            v-model="manualCalculationForm.startMonth"
            type="month"
            value-format="YYYY-MM"
            format="YYYY年MM月"
            placeholder="选择起始月份"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="截止月份" required>
          <el-date-picker
            v-model="manualCalculationForm.endMonth"
            type="month"
            value-format="YYYY-MM"
            format="YYYY年MM月"
            placeholder="选择截止月份"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="月度记录">
          <el-checkbox v-model="manualCalculationForm.generateMonthlyRecords">
            生成月度统计记录
          </el-checkbox>
        </el-form-item>
        <div class="manual-calculation-hint">系统将自动按起始月份1日、截止月份最后一日执行一次核算。</div>
      </el-form>
      <template #footer>
        <el-button @click="manualCalculationVisible = false" :disabled="manualCalculating">取消</el-button>
        <el-button type="primary" @click="confirmManualCalculation" :loading="manualCalculating">确认核算</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue';
import { ArrowLeft } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus';
import { templateApi, factorTemplateApi } from '../api/auth';
import { hasPermission } from '../utils/permissions';

const props = defineProps({
  currentUser: {
    type: Object,
    default: null
  },
  embedded: {
    type: Boolean,
    default: false
  }
});

const emit = defineEmits(['open-template', 'logout', 'back', 'edit-factor-template']);
const canEdit = computed(() => hasPermission(props.currentUser, 'carbon:model:edit'));
const canValidate = computed(() => canEdit.value || hasPermission(props.currentUser, 'carbon:model:validate'));

const companies = ref([]), companiesLoading = ref(false), companiesReady = ref(false), companiesError = ref('');
const companyVisible = ref(false), ownershipSaving = ref(false), newSubmitting = ref(false), copySubmitting = ref(false);
const ownershipForm = ref({ id: null, name: '', companyDeptId: null, confirmLegacyTasks: false });
let companiesRequestId = 0;
onBeforeUnmount(() => { companiesRequestId++; });
const loadCompanies = async () => {
  const requestId = ++companiesRequestId;
  companiesLoading.value = true; companiesReady.value = false; companiesError.value = '';
  try { const res = await templateApi.getCompanies(); if (requestId !== companiesRequestId) return false; companies.value = Array.isArray(res.data) ? res.data : []; companiesReady.value = true; return true; }
  catch { if (requestId === companiesRequestId) { companies.value = []; companiesError.value = '公司列表加载失败，请重新打开后重试'; } return false; }
  finally { if (requestId === companiesRequestId) companiesLoading.value = false; }
};
const defaultCompany = id => companies.value.some(c => c.deptId === id) ? id : companies.value.length === 1 ? companies.value[0].deptId : null;
const openCompanyOwnership = async () => {
  if (!canEdit.value || !selectedTemplate.value) return;
  const selected = selectedTemplate.value;
  ownershipForm.value = { id: selected.id, name: selected.name, companyDeptId: null, confirmLegacyTasks: false };
  companyVisible.value = true;
  const loaded = await loadCompanies();
  if (loaded && companyVisible.value && ownershipForm.value.id === selected.id) ownershipForm.value.companyDeptId = defaultCompany(selected.companyDeptId);
};
const closeCompanyOwnership = done => { if (!ownershipSaving.value) done(); };
const saveCompanyOwnership = async () => {
  if (ownershipSaving.value || !companiesReady.value || !ownershipForm.value.companyDeptId) return;
  ownershipSaving.value = true;
  try {
    await templateApi.assignCompany(ownershipForm.value.id, ownershipForm.value.companyDeptId, ownershipForm.value.confirmLegacyTasks);
    companyVisible.value = false; selectedTemplate.value = null; selectedId.value = null;
    await loadTemplates(); ElMessage.success('公司归属已保存，已有报告保持原数据来源');
  } catch (error) { ElMessage.error(error?.response?.data?.message || '归属保存失败，请检查权限和任务状态'); }
  finally { ownershipSaving.value = false; }
};
const templates = ref([]);
const selectedTemplate = ref(null);
const selectedId = ref(null);

const showNewModal = ref(false);
const showSaveAsModal = ref(false);
const showDeleteConfirm = ref(false);
const showEditModal = ref(false);
const editSubmitting = ref(false);
const taskCollapse = ref(['1']);

const newTemplateForm = ref({
  name: '',
  description: '',
  templateType: 1
});

const saveAsForm = ref({
  name: ''
});

const editForm = ref({
  id: null,
  name: '',
  description: '',
  enabled: true,
  templateType: 1,
  taskConfig: {
    autoCalculationEnabled: false,
    startDate: null,
    endDate: null,
    cycleType: 'DAILY',
    weekdays: [],
    monthDays: [],
    quarterDays: [],
    yearMonths: [],
    yearDays: [],
    executionTime: '02:00',
    interval: 1,
    delayDays: 3
  }
});

// 执行日期固定提示：执行日期选择框已隐藏，日期由程序自动设置为对应计量周期的第一天
const fixedExecutionDateHint = computed(() => {
  switch (editForm.value.taskConfig.cycleType) {
    case 'WEEKLY': return '执行日期固定为：每周周一';
    case 'MONTHLY': return '执行日期固定为：每月1号';
    case 'QUARTERLY': return '执行日期固定为：每季度第1天（1/4/7/10月1日）';
    case 'YEARLY': return '执行日期固定为：每年1月1日';
    default: return '每日执行，无需选择日期';
  }
});

// 按执行周期类型自动填写执行日期（固定为对应计量周期的第一天），字段格式与后端
// EmissionScheduler.checkCycle 的解析期望一致（均为JSON数组）：
// WEEKLY→weekdays[周一=1]；MONTHLY→monthDays[1]；QUARTERLY→quarterDays[1]（1/4/7/10月1日）；
// YEARLY→yearMonths[1]+yearDays[1]（1月1日）。当前固定该策略，后续如需放开人工设置，
// 恢复隐藏的日期选择输入框（移除 v-if="false"）并调整本方法即可。
const applyFixedExecutionDates = (taskConfig) => {
  taskConfig.weekdays = [];
  taskConfig.monthDays = [];
  taskConfig.quarterDays = [];
  taskConfig.yearMonths = [];
  taskConfig.yearDays = [];
  switch (taskConfig.cycleType) {
    case 'WEEKLY':
      taskConfig.weekdays = [1];       // 每周周一
      break;
    case 'MONTHLY':
      taskConfig.monthDays = [1];      // 每月1号
      break;
    case 'QUARTERLY':
      taskConfig.quarterDays = [1];    // 每季度第1天（1/4/7/10月1日）
      break;
    case 'YEARLY':
      taskConfig.yearMonths = [1];     // 每年1月1日
      taskConfig.yearDays = [1];
      break;
    case 'DAILY':
    default:
      break;
  }
  return taskConfig;
};

const loadTemplates = async () => {
  // The template list is the primary model-management view. A read-only or
  // older backend may not expose baseline metadata yet; that must not hide
  // every template in the UI.
  try {
    const templateResponse = await templateApi.getAllTemplates();
    templates.value = Array.isArray(templateResponse.data) ? templateResponse.data : [];
  } catch {
    templates.value = [];
    statisticsBaselines.value = [];
    ElMessage.error('模板列表加载失败，请重试');
    return;
  }
  try {
    const baselineResponse = await templateApi.getStatisticsBaselines();
    statisticsBaselines.value = Array.isArray(baselineResponse.data) ? baselineResponse.data : [];
  } catch {
    // Keep the templates usable when baseline support is unavailable.
    statisticsBaselines.value = [];
  }
};

const setStatisticsBaseline = async () => {
  if (!selectedTemplate.value || baselineSaving.value || isBaselineSelected.value) return;
  if (!selectedTemplate.value.companyDeptId) {
    ElMessage.warning('请先设置模板归属公司');
    return;
  }
  baselineSaving.value = true;
  try {
    const selectedId = selectedTemplate.value.id;
    const response = await templateApi.setStatisticsBaseline(selectedId);
    await loadTemplates();
    const refreshed = templates.value.find(item => String(item.id) === String(selectedId));
    if (refreshed) selectedTemplate.value = refreshed;
    const data = response.data || {};
    ElMessage.success(`已将“${data.templateName || selectedTemplate.value?.name || ''}”设为${data.companyName || '当前公司'}统计基准模版`);
  } catch (error) {
    ElMessage.error(error?.response?.data?.message || error?.response?.data?.error || '设置统计基准模版失败');
  } finally {
    baselineSaving.value = false;
  }
};

onMounted(() => {
  loadTemplates();
});

const selectTemplate = (template) => {
  selectedTemplate.value = template;
  selectedId.value = template.id;
};

const handleDoubleClick = (template) => {
  emit('open-template', template);
};

const handleNewTemplate = async (type = 1) => {
  newTemplateForm.value = {
    name: '',
    description: '',
    templateType: type, companyDeptId: null
  };
  showNewModal.value = true;
  const loaded = await loadCompanies();
  if (loaded && showNewModal.value) newTemplateForm.value.companyDeptId = defaultCompany(null);
};

const confirmNewTemplate = async () => {
  if (newSubmitting.value || !companiesReady.value) return;
  if (!newTemplateForm.value.name.trim()) { ElMessage.warning('请输入模版名称'); return; }
  if (newTemplateForm.value.templateType === 2 && !newTemplateForm.value.companyDeptId) { ElMessage.warning('请选择归属公司'); return; }
  newSubmitting.value = true;
  try {
    await templateApi.createTemplate(newTemplateForm.value.name, props.currentUser?.userId, newTemplateForm.value.description, newTemplateForm.value.templateType, newTemplateForm.value.companyDeptId);
    showNewModal.value = false; await loadTemplates(); ElMessage.success('新建成功');
  } catch (error) { ElMessage.error(error?.response?.data?.message || '新建失败'); }
  finally { newSubmitting.value = false; }
};

const handleOpenTemplate = () => {
  if (selectedTemplate.value) {
    emit('open-template', selectedTemplate.value);
  }
};

const handleSaveAs = async () => {
  if (selectedTemplate.value) {
    saveAsForm.value = {
      name: selectedTemplate.value.name + '_副本', companyDeptId: null
    };
    showSaveAsModal.value = true;
    const loaded = await loadCompanies();
    if (loaded && showSaveAsModal.value) saveAsForm.value.companyDeptId = defaultCompany(selectedTemplate.value?.companyDeptId);
  }
};

const confirmSaveAs = async () => {
  if (copySubmitting.value || !companiesReady.value || !selectedTemplate.value) return;
  if (!saveAsForm.value.name.trim()) { ElMessage.warning('请输入新模版名称'); return; }
  if (selectedTemplate.value.templateType === 2 && !saveAsForm.value.companyDeptId) { ElMessage.warning('请选择归属公司'); return; }
  copySubmitting.value = true;
  try {
    await templateApi.copyTemplate(selectedTemplate.value.id, saveAsForm.value.name, props.currentUser?.userId, saveAsForm.value.companyDeptId);
    showSaveAsModal.value = false; await loadTemplates(); ElMessage.success('另存为成功，请核对采集点是否属于所选公司');
  } catch (error) { ElMessage.error(error?.response?.data?.message || '另存为失败'); }
  finally { copySubmitting.value = false; }
};

const handleDeleteTemplate = () => {
  if (selectedTemplate.value) {
    showDeleteConfirm.value = true;
  }
};

const confirmDelete = () => {
  templateApi.deleteTemplate(selectedTemplate.value.id).then(() => {
    showDeleteConfirm.value = false;
    loadTemplates();
    selectedTemplate.value = null;
    selectedId.value = null;
    alert('删除成功');
  });
};

const handleLogout = () => {
  localStorage.removeItem('user');
  emit('logout');
};

const formatDate = (dateStr) => {
  if (!dateStr) return '';
  const date = new Date(dateStr);
  return date.toLocaleString('zh-CN');
};

// ============ 模版校验（仅核算模版） ============

const validating = ref(false);
const validationResultVisible = ref(false);
const validationResult = ref(null);
const manualCalculationVisible = ref(false);
const manualCalculating = ref(false);
const manualCalculationForm = ref({ startMonth: '', endMonth: '', generateMonthlyRecords: true });

/** 选中的是否为核算模版（校验功能仅对核算模版有效） */
const isCalcSelected = computed(() => selectedTemplate.value?.templateType === 2);
const statisticsBaselines = ref([]);
const baselineSaving = ref(false);
const isBaselineSelected = computed(() =>
  statisticsBaselines.value.some(item =>
    item.templateId != null
      && String(item.templateId) === String(selectedTemplate.value?.id)
      && item.companyDeptId != null
      && String(item.companyDeptId) === String(selectedTemplate.value?.companyDeptId)
  )
);

const validationResultTitle = computed(() =>
  '模版校验结果' + (selectedTemplate.value ? ' - ' + selectedTemplate.value.name : '')
);

/**
 * 校验结果代码 → 展示信息
 * 0-未检查、1-完全正确、2-正确（存在提示信息）、3-存在告警、4-存在错误
 */
const checkResultMeta = computed(() => {
  const map = {
    1: { label: '完全正确', tagType: 'success' },
    2: { label: '正确（存在提示信息）', tagType: 'primary' },
    3: { label: '存在告警', tagType: 'warning' },
    4: { label: '存在错误', tagType: 'danger' }
  };
  return map[validationResult.value?.checkResult] || { label: '未检查', tagType: 'info' };
});

const formatDateTime = formatDate;

const currentMonth = () => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
};

const openManualCalculation = () => {
  if (!selectedTemplate.value || !isCalcSelected.value) return;
  const month = currentMonth();
  manualCalculationForm.value = { startMonth: month, endMonth: month, generateMonthlyRecords: true };
  manualCalculationVisible.value = true;
};

const confirmManualCalculation = async () => {
  const { startMonth, endMonth, generateMonthlyRecords } = manualCalculationForm.value;
  if (!startMonth || !endMonth) {
    ElMessage.warning('请选择核算起止月份');
    return;
  }
  if (startMonth > endMonth) {
    ElMessage.warning('起始月份不能晚于截止月份');
    return;
  }
  manualCalculating.value = true;
  try {
    const res = await templateApi.manualCalculate(
      selectedTemplate.value.id,
      startMonth,
      endMonth,
      generateMonthlyRecords !== false
    );
    manualCalculationVisible.value = false;
    const data = res.data || {};
    const status = Number(data.status);
    if (status === 2) {
      ElMessage.success(data.message || '手动核算完成');
    } else if (status === 1 || status === 0) {
      ElMessage.info(data.message || '该周期核算正在执行');
    } else if (status === 3) {
      ElMessage.error(data.message || '手动核算失败');
    } else {
      ElMessage.warning(data.message || '核算任务已提交');
    }
  } catch (err) {
    console.error('手动核算失败', err);
    ElMessage.error('手动核算失败：' + (err.response?.data?.message || err.message));
  } finally {
    manualCalculating.value = false;
  }
};

/**
 * 执行校验：调用后端校验接口，弹窗展示富文本结果并刷新列表
 * （模版修改后校验结果会被后端自动重置为未检查）
 */
const handleValidateTemplate = async () => {
  if (!selectedTemplate.value) return;
  if (selectedTemplate.value.templateType !== 2) {
    ElMessage.warning('仅核算模版支持校验');
    return;
  }
  validating.value = true;
  try {
    const res = await templateApi.validateTemplate(selectedTemplate.value.id);
    validationResult.value = res.data;
    validationResultVisible.value = true;
    // 刷新列表以同步最新校验状态，并保持选中行不变
    await loadTemplates();
    const refreshed = templates.value.find(t => t.id === selectedTemplate.value.id);
    if (refreshed) {
      selectedTemplate.value = refreshed;
    }
  } catch (err) {
    console.error('模版校验失败', err);
    ElMessage.error('校验失败：' + (err.response?.data?.message || err.message));
  } finally {
    validating.value = false;
  }
};

/**
 * 查看选中核算模版最近一次保存的校验结果（不重新校验）
 */
const handleViewValidationResult = async () => {
  if (!selectedTemplate.value) return;
  if (selectedTemplate.value.templateType !== 2) {
    ElMessage.warning('仅核算模版支持校验结果查看');
    return;
  }
  try {
    const res = await templateApi.getValidationResult(selectedTemplate.value.id);
    validationResult.value = res.data;
    validationResultVisible.value = true;
  } catch (err) {
    console.error('获取校验结果失败', err);
    ElMessage.error('获取校验结果失败：' + (err.response?.data?.message || err.message));
  }
};

/**
 * 根据模版类型值返回展示信息
 * 1-节点模版；2-核算模版；未识别时按节点模版处理
 * @param {number} templateType 模版类型
 * @returns {{label: string, tagType: string}} 展示标签与 el-tag 类型
 */
const getTemplateType = (templateType) => {
  if (templateType === 2) {
    return { label: '核算模版', tagType: 'primary' };
  }
  return { label: '节点模版', tagType: 'info' };
};

const initEditForm = () => {
  editForm.value = {
    id: null,
    name: '',
    companyDeptId: null,
    companyName: '',
    description: '',
    enabled: true,
    templateType: 1,
    factorTemplateId: null,
    taskConfig: {
      autoCalculationEnabled: false,
      startDate: null,
      endDate: null,
      cycleType: 'DAILY',
      weekdays: [],
      monthDays: [],
      quarterDays: [],
      yearMonths: [],
      yearDays: [],
      executionTime: '02:00',
      interval: 1,
      delayDays: 3
    }
  };
};

const handleEditTemplate = (template) => {
  selectedTemplate.value = template;
  selectedId.value = template.id;
  initEditForm();

  editForm.value.id = template.id;
  editForm.value.companyDeptId = template.companyDeptId || null;
  editForm.value.companyName = template.companyName || '';
  editForm.value.name = template.name;
  editForm.value.description = template.description || '';
  editForm.value.enabled = template.enabled !== undefined ? template.enabled : true;
  // 模版类型：后端默认1（节点模版），未返回时回退为1
  editForm.value.templateType = template.templateType !== undefined && template.templateType !== null
    ? template.templateType
    : 1;
  editForm.value.factorTemplateId = template.factorTemplateId !== undefined && template.factorTemplateId !== null
    ? template.factorTemplateId
    : null;

  if (template.taskConfig && template.taskConfig.trim()) {
    try {
      const taskConfig = JSON.parse(template.taskConfig);
      editForm.value.taskConfig = {
        autoCalculationEnabled: taskConfig.autoCalculationEnabled === true,
        startDate: taskConfig.startDate || null,
        endDate: taskConfig.endDate || null,
        cycleType: taskConfig.cycleType || 'DAILY',
        weekdays: taskConfig.weekdays || taskConfig.weekDays || [],
        monthDays: taskConfig.monthDays || [],
        quarterDays: taskConfig.quarterDays || [],
        yearMonths: taskConfig.yearMonths || [],
        yearDays: taskConfig.yearDays || [],
        executionTime: taskConfig.executionTime || '02:00',
        interval: taskConfig.interval || 1,
        // 延迟核算日期（天）：缺省3天
        delayDays: taskConfig.delayDays !== undefined ? taskConfig.delayDays : 3
      };
      // 执行日期选择已固定：按周期类型自动覆盖为对应计量周期的第一天
      //（同时把历史遗留的字符串格式日期统一修正为数组格式，与后端解析期望一致）
      applyFixedExecutionDates(editForm.value.taskConfig);
    } catch (e) {
      console.error('Failed to parse taskConfig:', e);
    }
  }

  showEditModal.value = true;

  // 核算模版：预加载碳排放因子模版列表（用于显示当前已关联的因子模版名称）
  if (editForm.value.templateType === 2) {
    preloadFactorTemplateList();
  }
};

/**
 * 预加载因子模版列表（静默，不弹窗、不加 loading）
 */
const preloadFactorTemplateList = async () => {
  try {
    const res = await factorTemplateApi.listAll();
    factorTemplateList.value = res.data || [];
  } catch (err) {
    console.error('预加载因子模版列表失败', err);
  }
};

const handleCycleChange = () => {
  // 切换执行周期时，自动将执行日期重置为对应计量周期的第一天
  applyFixedExecutionDates(editForm.value.taskConfig);
};

const confirmEdit = async () => {
  if (editSubmitting.value) return;
  const currentUser = JSON.parse(localStorage.getItem('user') || '{}');
  editSubmitting.value = true;
  try {
    await templateApi.updateTemplateProperties(
      editForm.value.id,
      editForm.value.description,
      editForm.value.enabled,
      editForm.value.templateType,
      JSON.stringify(editForm.value.taskConfig),
      editForm.value.factorTemplateId,
      currentUser.userId
    );
    showEditModal.value = false;
    await loadTemplates();
    ElMessage.success('编辑成功');
  } catch (err) {
    console.error('编辑模版属性失败', err);
    const message = err.response?.data?.message || err.response?.data?.error || err.message || '保存失败';
    ElMessage.error('保存失败：' + message);
  } finally {
    editSubmitting.value = false;
  }
};

// ============ 碳排放因子模版选择 ============

const factorTemplateSelectVisible = ref(false);
const factorTemplateList = ref([]);
const factorTemplateLoading = ref(false);
const lockedFactorTemplateIds = ref([]);
// 弹窗中当前选中（单选）的因子模版ID
const selectedFactorTemplateId = ref(null);
// 当前选中的因子模版行对象（未选中为 null）
const selectedFactorTemplate = computed(() =>
  factorTemplateList.value.find(t => t.id === selectedFactorTemplateId.value) || null
);

const factorTemplateFormVisible = ref(false);
const factorTemplateForm = ref({ id: null, templateName: '', templateDescription: '', isShared: 1 });

const copyFactorTemplateVisible = ref(false);
const copyFactorTemplateForm = ref({ sourceId: null, sourceName: '', newName: '' });

/**
 * 判断因子模版是否属于当前用户
 */
const isOwnFactorTemplate = (row) => {
  return row.createdBy != null && row.createdBy === props.currentUser?.userId;
};

/**
 * 根据ID查询因子模版名称（用于编辑弹窗中展示当前选择）
 */
const factorTemplateName = (id) => {
  const t = factorTemplateList.value.find(item => item.id === id);
  return t ? t.templateName : '';
};

/**
 * 打开碳排放因子模版选择弹窗
 * @param {number|null} preselectId 打开后需要默认选中的因子模版ID（如新建/拷贝后的新模版）
 */
const openFactorTemplateSelect = async (preselectId = null) => {
  factorTemplateSelectVisible.value = true;
  factorTemplateLoading.value = true;
  lockedFactorTemplateIds.value = [];
  // 默认选中指定模版；未指定时选中当前核算模版已关联的因子模版
  selectedFactorTemplateId.value = preselectId || editForm.value.factorTemplateId || null;
  try {
    const res = await factorTemplateApi.listAll();
    factorTemplateList.value = res.data || [];
    // 对自有模版并行查询"他人核算模版引用计数"，>0 则锁定
    const ownList = factorTemplateList.value.filter(t => isOwnFactorTemplate(t));
    const checks = await Promise.all(
      ownList.map(t =>
        factorTemplateApi.getReferenceCount(t.id, props.currentUser?.userId)
          .then(r => ({ id: t.id, count: r.data?.count || 0 }))
      )
    );
    lockedFactorTemplateIds.value = checks.filter(c => c.count > 0).map(c => c.id);
  } catch (err) {
    console.error('加载因子模版列表失败', err);
    ElMessage.error('加载因子模版列表失败：' + (err.response?.data?.message || err.message));
  } finally {
    factorTemplateLoading.value = false;
  }
};

/**
 * 点击表格行：选中该行
 */
const handleFactorTemplateRowClick = (row) => {
  selectedFactorTemplateId.value = row.id;
};

/**
 * 底部"选择"按钮：将选中的因子模版设为当前核算模版的因子模版（保存编辑时写入）
 */
const confirmSelectFactorTemplate = () => {
  const row = selectedFactorTemplate.value;
  if (!row) {
    ElMessage.warning('请先选择一条因子模版');
    return;
  }
  editForm.value.factorTemplateId = row.id;
  factorTemplateSelectVisible.value = false;
  ElMessage.success(`已选择因子模版"${row.templateName}"，点击"确定"保存生效`);
};

/**
 * 顶部"编辑因子"按钮：校验选中行后跳转到因子编辑界面
 */
const handleEditFactorBtn = () => {
  const row = selectedFactorTemplate.value;
  if (!row) {
    ElMessage.warning('请先选择一条因子模版');
    return;
  }
  if (!isOwnFactorTemplate(row)) {
    ElMessage.warning('只能编辑自己创建的因子模版');
    return;
  }
  if (lockedFactorTemplateIds.value.includes(row.id)) {
    ElMessage.warning('该因子模版正在被其他用户的核算模版使用，不可编辑');
    return;
  }
  factorTemplateSelectVisible.value = false;
  showEditModal.value = false;
  emit('edit-factor-template', row.id);
};

/**
 * 顶部"编辑信息"按钮：校验选中行后打开信息编辑弹窗
 */
const handleEditInfoBtn = () => {
  const row = selectedFactorTemplate.value;
  if (!row) {
    ElMessage.warning('请先选择一条因子模版');
    return;
  }
  if (!isOwnFactorTemplate(row)) {
    ElMessage.warning('只能编辑自己创建的因子模版');
    return;
  }
  if (lockedFactorTemplateIds.value.includes(row.id)) {
    ElMessage.warning('该因子模版正在被其他用户的核算模版使用，不可编辑');
    return;
  }
  openEditFactorTemplateInfo(row);
};

/**
 * 顶部"拷贝模版"按钮：校验选中行后打开拷贝弹窗
 */
const handleCopyBtn = () => {
  const row = selectedFactorTemplate.value;
  if (!row) {
    ElMessage.warning('请先选择一条因子模版');
    return;
  }
  openCopyFactorTemplate(row);
};

/**
 * 打开新建因子模版信息弹窗
 */
const openNewFactorTemplate = () => {
  factorTemplateForm.value = { id: null, templateName: '', templateDescription: '', isShared: 1 };
  factorTemplateFormVisible.value = true;
};

/**
 * 打开编辑因子模版信息弹窗
 */
const openEditFactorTemplateInfo = (row) => {
  factorTemplateForm.value = {
    id: row.id,
    templateName: row.templateName,
    templateDescription: row.templateDescription || '',
    isShared: row.isShared != null ? row.isShared : 1
  };
  factorTemplateFormVisible.value = true;
};

/**
 * 保存新建/编辑 因子模版信息
 */
const confirmFactorTemplateForm = async () => {
  if (!factorTemplateForm.value.templateName?.trim()) {
    ElMessage.warning('请输入模版名称');
    return;
  }
  const userId = props.currentUser?.userId;
  try {
    const form = factorTemplateForm.value;
    let newId = null;
    if (form.id) {
      // 编辑
      const target = factorTemplateList.value.find(t => t.id === form.id) || {};
      await factorTemplateApi.update(form.id, {
        templateName: form.templateName.trim(),
        templateDescription: form.templateDescription,
        isShared: form.isShared,
        status: target.status != null ? target.status : 1,
        updatedBy: userId
      });
      ElMessage.success('因子模版已更新');
      newId = form.id;
    } else {
      // 新建
      const createRes = await factorTemplateApi.create({
        templateName: form.templateName.trim(),
        templateDescription: form.templateDescription,
        isShared: form.isShared,
        createdBy: userId
      });
      if (createRes.data?.success === false) {
        ElMessage.error(createRes.data.message || '创建失败');
        return;
      }
      ElMessage.success('因子模版已创建');
      newId = createRes.data?.data?.id || null;
    }
    factorTemplateFormVisible.value = false;
    await openFactorTemplateSelect(newId);
  } catch (err) {
    console.error('保存因子模版失败', err);
    ElMessage.error('保存失败：' + (err.response?.data?.message || err.message));
  }
};

/**
 * 打开拷贝因子模版弹窗
 */
const openCopyFactorTemplate = (row) => {
  copyFactorTemplateForm.value = {
    sourceId: row.id,
    sourceName: row.templateName,
    newName: row.templateName + '_副本'
  };
  copyFactorTemplateVisible.value = true;
};

/**
 * 确认拷贝因子模版
 */
const confirmCopyFactorTemplate = async () => {
  if (!copyFactorTemplateForm.value.newName?.trim()) {
    ElMessage.warning('请输入新模版名称');
    return;
  }
  try {
    const res = await factorTemplateApi.copyTemplate(
      copyFactorTemplateForm.value.sourceId,
      copyFactorTemplateForm.value.newName.trim(),
      props.currentUser?.userId
    );
    if (res.data?.success === false) {
      ElMessage.error(res.data.message || '拷贝失败');
      return;
    }
    ElMessage.success('因子模版已拷贝');
    copyFactorTemplateVisible.value = false;
    await openFactorTemplateSelect(res.data?.data?.id || null);
  } catch (err) {
    console.error('拷贝因子模版失败', err);
    ElMessage.error('拷贝失败：' + (err.response?.data?.message || err.message));
  }
};
</script>

<style scoped>
.template-list-container {
  padding: 20px;
  min-height: 100vh;
  background-color: #f5f7fa;
}

.permission-alert {
  margin: 12px 0;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 15px;
}

.header h1 {
  font-size: 24px;
  color: #1f2329;
  margin: 0;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 16px;
  font-size: 14px;
}

.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 20px;
}

.manual-calculation-hint {
  color: #909399;
  font-size: 13px;
  line-height: 1.6;
  margin: -4px 0 4px 90px;
}

/* 模版校验结果弹窗 */
.validation-result-body {
  max-height: 55vh;
  overflow-y: auto;
}

.validation-summary {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-bottom: 10px;
  margin-bottom: 10px;
  border-bottom: 1px solid #ebeef5;
}

.validation-time {
  color: #909399;
  font-size: 13px;
}

.validation-message {
  font-size: 13px;
  line-height: 1.8;
  word-break: break-all;
}

/* v-html 注入的后端富文本节点无 scoped 属性，需用 :deep 穿透 */
.validation-message :deep(div) {
  margin-bottom: 4px;
}

.template-list {
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  padding: 20px;
}

.template-list table {
  width: 100%;
  border-collapse: collapse;
}

.template-list th,
.template-list td {
  padding: 12px;
  text-align: left;
  border-bottom: 1px solid #e8eaec;
}

.template-list th {
  background-color: #f5f7fa;
  font-weight: 600;
  color: #595959;
}

.template-list tbody tr:hover {
  background-color: #f5f7fa;
}

.template-list tbody tr.selected {
  background-color: #e6f7ff;
}

.empty-tip {
  padding: 40px;
  text-align: center;
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.text-muted {
  color: #8c8c8c;
  font-size: 12px;
  margin-left: 8px;
}
</style>
