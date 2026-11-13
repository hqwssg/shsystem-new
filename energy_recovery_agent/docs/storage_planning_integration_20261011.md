# 第六类任务：储能选址与定容规划

本地版本：`2026.10.10.1-mysql-six-tasks`。算法来源为 `new_function/algorithm_release_20261010_v1` 的规划合同与离散规划模块，增量接入 `shuohuang-main`、外部 `energy_recovery_agent` 和 MySQL。未接入独立单列车算法。此前五类升级说明、备份和发布记录保留。

本次完成代码接入和隔离验证，未连接或修改现有业务数据库，尚未进行正式业务部署和工程验收。历史 `RELEASE_MANIFEST`、`interface_contract_freeze` 等仍描述原交付状态；当前增量合同见 `database/storage_planning_platform_contract.json`。

## 数据维护

数据维护新增“储能规划”分类，中文模板位于 `data_templates/user_excel/储能规划.xlsx`，包含填写说明及六张业务表。可上传 Excel 叠加发布，也可在浏览器逐表编辑并保存版本。

| 中文工作表 | 算法输入文件 |
| --- | --- |
| 候选站点 | storage_candidate_sites.csv |
| 储能技术 | storage_technologies.csv |
| 站点技术配置 | storage_site_technology_options.csv |
| 场景集、规划场景 | storage_planning_scenarios.json |
| 规划策略 | storage_planning_policy.json |

版本保存时沿用中文文件名映射和原有版本快照。用户填写中文字段和单位栏，场景内的车流、发车间隔、相位与倍率参数均展开为业务字段，无需编写 JSON。技术或故障站点编码列表可用中文逗号分隔。

首版需要填写全部六张表，每个版本仅支持一份策略、一个场景集。Excel 空白表沿用底稿，浏览器未提交的表保留底稿；在线明确清空必需表会被拒绝。规划数据部分缺失、编号重复、站点或技术引用错误、容量功率非法、供电臂不存在、场景权重不合法、运行图路径不存在均阻止发布、保存或规划任务提交。

运行图填写版本内文件路径，支持中文路径，转换后核对实际文件。规划固定输入运行图；“运行图协同规划”须填“否”。不新增连续定容或运行图协同规划算法。

规划任务使用候选站点和候选技术参数。已提供完整规划输入的版本允许在役储能设备文件为空数组；不把推荐设备写回在役设备表。旧版本没有规划数据时，原五类任务仍可执行。

`data_templates/storage_planning_example` 为单独保存的合成样例，不自动发布到任何业务版本；技术用空白合同模板另存于 `data_templates/storage_planning_template`。样例不代表现场站址或价格。

## 创建和执行任务

任务创建页选择“储能选址与定容规划”，选择版本后从该版本读取策略和场景集选项。不可手工提交版本中不存在的编码。预设接口增量返回 `planningReady`、`planningIssues`、`planningPolicyOptions` 和 `scenarioSetOptions`，原任务参数恢复和版本选择流程继续使用。

| 参数 | 默认值及约束 |
| --- | --- |
| planning_policy_code | 必填，从版本策略选择 |
| scenario_set_code | 必填，从版本场景集选择 |
| search_mode | coarse；另支持 coarse_to_fine、exhaustive |
| max_levels_per_dimension | 2，整数且至少 2 |
| settlement_step_s | 300 秒，正整数 |
| refinement_shortlist_size | 3，正整数，仅粗搜后细化时显示 |

策略、场景集编码在入队和工作进程执行时分别核对版本数据。复用指定任务执行、冻结快照、心跳、取消、租约恢复和删除机制。资源档位 quick/standard/fine 对应 180/600/1200 秒进程预算，内部计算保留退出和产物写入时间，实际搜索上限还受策略最大计算秒数限制；不会自动切换搜索方式。

算法提前结束保留搜索完整性标记，结果仅针对已评价候选。进程超时记录任务失败，不会伪装为无可行方案。取消会终止运行进程，过期执行租约不能覆盖任务结果。

## 结果接口与页面

新增 `GET /carbon/energy/runs/{runId}/storage-planning`，查询参数为 `pageNum`（默认 1）、`pageSize`（默认 20，最大 100）和可选 `planId`。沿用 `carbon:energy:query` 权限、部门归属与成功状态检查；方案必须属于当前任务。

返回 Java 驼峰字段：`decision`、`plans`、`selectedPlan`、`devices`、`scenarioResults`、`baselineScenarioResults`、`referenceOnly`、`total`、`pageNum`、`pageSize`。结构化 JSON 内部键也转为驼峰。候选按排名分页，选择候选后读取其完整设备和逐场景结果。

| 决策值 | 页面结论 |
| --- | --- |
| recommend_build | 建议建设 |
| keep_no_build | 建议不建设 |
| no_feasible_plan | 无可行方案；基线仅作参考 |

页面显示投资、年成本、年收益、容量功率、候选淘汰原因、逐站配置和与基线的场景对比，同时展示结论等级、数据状态和搜索完整性。占位输入提示“规划敏感性结论，不能作为正式工程结论”，合成数据明确标为样例。工程候选仍需工程复核，不代表正式工程验收。无可行方案的参考基线不显示为推荐建设方案。

已注册中文名称、预览和完整文件下载的产物：

- storage_planning_report.md、storage_planning_summary.json
- no_build_baseline.csv、energy_hotspots.csv
- storage_plan_candidates.csv、storage_plan_devices.csv、storage_plan_scenario_results.csv
- storage_plan_rejections.csv、storage_plan_lifecycle.csv
- storage_economic_sensitivity.csv、storage_device_scenario_results.csv

下载返回完整文件，独立于页面候选分页。数据库金额等 DECIMAL 字段有固定精度；原始 CSV/JSON 产物完整保存，JSON 数值比较允许 MySQL 的浮点表示差异。

## 数据库与部署顺序

迁移文件：`shuohuang-main/sql/carbon-energy/V3__storage_planning.sql`，最低 MySQL 8.0.16。增加五张规划输入表、四张结果表，并扩展 `energy_run` 类型约束。采用现有 `energy_` 前缀、char(36) UUID、JSON 和外键约定。算法侧 `sql/V3__storage_planning.sql` 为同内容副本，支持外部算法目录独立交付。

正式部署顺序：

1. 停止接收新任务并等待运行任务结束，备份业务数据库及平台、算法代码。
2. 在已安装 V1 的业务库执行 V3 迁移；新环境按 V1、V2 菜单、V3 顺序安装。
3. 更新外部算法目录，再更新 Java 平台和前端构建产物，核对 Python 路径和外部算法根目录配置。
4. 启动后先核对原五类任务，再发布正式规划数据并运行规划任务。

MySQL DDL 隐式提交，迁移不承诺整体事务回滚。输入发布、在线替换、结果写入、结果清理和任务删除使用事务；已验证注入失败后的业务事务回滚。不要用 PostgreSQL 交付脚本覆盖 MySQL 适配。

## 验证记录

记录根目录：`output/energy_storage_planning_20261011`，验证在 2026-10-11 至 2026-10-12 完成。

- Python：73 项通过；主动排除一项默认会使用业务数据库配置的旧测试。
- Java：21 项通过，包含权限、状态、分页、方案归属、驼峰 JSON 和实际 MyBatis 查询；实际 SQL 只连接自行启动的隔离 MySQL。
- 隔离 MySQL：16 项通过，覆盖旧五类约束迁移、重复迁移、中文发布、在线替换、空在役设备、四类规划结果、真实工作进程、取消、恢复、删除、产物一致性和事务回滚。
- 浏览器：5 组通过，加载实际 Vue 与 Element 组件，覆盖参数恢复、条件输入、缺失数据阻止提交、六张表编辑、方案分页及四类结果提示；接口数据使用隔离夹具，Java/MySQL 另外实测。未进行生产身份认证下的整站 HTTP 联调。
- 原五类任务：5 类实际小规模计算全部通过，原 16 项算法烟测全部通过。
- 新规划合同与 MVP 两项烟测通过，中文 Excel/浏览器/五个输入文件完整往返通过，包含多技术、展开场景参数、错误数据和中文运行图引用。
- 前端生产构建通过，保留原有两项资源体积警告。

总记录见 `verification_summary.json` 和 `验证记录.md`。`mysql_failure.log` 为修复过程中的历史诊断，最终结果以 `mysql_validation.json` 为准。隔离数据和结果保留用于审阅，验证结束后关闭自行启动的 MySQL；没有读取现有业务数据库配置进行连接。

可在工作区根目录复核：

```powershell
python -m pytest energy_recovery_agent/tests -q -k 'not delete_missing_run_reports_error'
python scripts/isolated_energy_mysql.py --restart
python scripts/verify_storage_planning_mysql.py
# 需要实际 MyBatis 联测时，按验证记录中的 Maven 命令运行
python scripts/isolated_energy_mysql.py --stop
```

首次没有隔离实例记录时，启动命令不加 `--restart`。隔离脚本只接受其专属数据目录，拒绝 3306 端口，不读取业务连接配置，不删除隔离数据目录。

## 备份和回退

`output/energy_storage_planning_20261011/backup` 保存本次修改前原文件；`original_files.json`、`change_manifest.json` 和 `changes.diff` 记录 SHA-256 与增量。五类历史升级记录仍保留在 `output/energy_upgrade_20261010`。

代码回退先停止任务及服务，再运行 `python scripts/rollback_storage_planning.py` 查看操作；明确执行时加 `--apply`。脚本先验证所有当前文件和备份哈希，拒绝覆盖交付后又修改的文件；只恢复此次代码，不连接数据库。本次未实际执行回退。

平台代码回退后保留 V3 新表和任务数据，避免丢失历史结果。有第六类任务记录时，不能直接恢复只允许五类的约束。数据库回退应根据部署前数据库备份单独处理，代码回退脚本不会自动删表或删业务数据。
