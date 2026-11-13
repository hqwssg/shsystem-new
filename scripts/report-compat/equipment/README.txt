报告设备默认清单初始化 2026-10-22

按用户要求，从此前三家公司的原始报告中提取第一章“企业主要设备及参数汇总表”。
肃宁：2024年度报告9行，原平：2024年度报告4行，机辆：2025年度报告57行，共70行。
截图中的机辆15行只是第一页，完整续表也已提取。未导入第七章监测表或能源活动量。
来源文件名、SHA256、原始行及归一结果见equipment-defaults.json。
机辆原序号33重复出现，两条设备都保留；同名同型号的不同原文行也保留，不合并。

数量与适用范围
历史设备数量作为可编辑的参考默认，并非本报告期已核实的设备数量。
每行备注保留原备注并注明参考年度，页面提示按本期核对。
原文7行未给出数量（肃宁1行、机辆6行），保存为空，不补0、不猜测数量。
名称、能源、型号及已有数量保留原文；原文没有数量单位和设备类别的，不擅自补写。
历史序号及详细来源留在溯源文件，成品表序号按显示顺序重新编号。

整合顺序
1. 先合并包内equipment-only.patch，检查后构建部署Java、前端及Python renderer。
   该代码兼容设备数量为空，设备表使用单倍行距，跨页重复表头、整行分页；正文样式保持。
   生产代码仅涉及models.py、publisher.py、ReportSnapshotAssembler.java、ReportTaskServiceImpl.java和AssetsStep.vue。
   补丁还含设备初始化材料、提取/打包工具及相关测试。不包含工作量选填等上一轮修改。
   在项目根目录执行：
     git apply --ignore-space-change --check /上传目录/equipment-only.patch
     git apply --ignore-space-change /上传目录/equipment-only.patch
   若检查冲突，让整合同事按差异合并，保留已上线的其他修改，不要整目录覆盖。
2. 将init_report_equipment.sh上传到服务器，例如：
     /opt/carbon-report-init/init_report_equipment.sh
3. 确认数据库容器名称：
     docker ps --format '{{.Names}} {{.Image}}'
4. 执行（把ruoyi-db换成实际数据库容器名）：
     bash /opt/carbon-report-init/init_report_equipment.sh --container ruoyi-db --database carbon_emissions --user root
   按提示输入数据库密码，输入不回显。脚本不需要Python，设备数据已嵌入这个.sh文件。
   已部署相应空数量兼容代码后，数据执行只需这个.sh文件，无须上传原始Word。
5. 出现REPORT_EQUIPMENT_INIT_OK及Completed后，检查返回各公司的条数及action。
   INITIALIZED：空设备清单已补入；EXISTING_EQUIPMENT_KEPT：保留原有非空人工清单。
6. 新建报告或刷新无手工设备的草稿，在“设备→用能设备”核对并保存。已手工保存设备的报告优先保留原内容。

写入边界
仅更新三家已登记公司的report_dept_profile.default_equipment_json、版本和审计时间。
按公司全名及登记关系解析实际dept_id，本地301/302/303与线上3010/3020/3030均支持。
已有非空清单不覆盖、不自动追加；公司没有档案时停止，先完成原档案初始化。
不修改公司编码（SH占位编码也不会被本脚本迁移）、文字、图片、人员、工作量、账号、权限、报告填报及核算结果。
重复执行不重复写入、不增加版本；异常时回滚整个设备更新事务。不要使用mysql --force忽略错误。
适用MySQL8.x，需读取/更新档案、临时表及创建/执行/删除辅助存储过程权限，目标档案表须为InnoDB。
本包的.sql与.sh内嵌SQL相同，仅供熟悉MySQL的同事在自行备份后使用；通常执行.sh即可。

备份与回退
.sh执行前自动备份企业档案，并显示服务器上的备份和日志目录。不要将含业务档案的备份发回交付包。
备份SQL不含DROP TABLE，但不是一键覆盖回滚脚本。回退应依据备份，仅还原目标公司的设备默认JSON及相应版本。
若执行后已有人工修改，不应直接回退覆盖；先核对当前内容、版本和执行日志。
代码回退点：pre-sync-30-report-equipment-defaults-20261022。已生成文件保持原样，不执行删除。

开发复现
原始Word留在用户本地，不放入本包。
  python scripts/report-compat/equipment/extract_equipment.py --source-root /原始报告父目录
  python scripts/report-compat/equipment/build_initializer.py --output /设备初始化输出目录
提取器核验原报告SHA256，拒绝静默改用其他版本；初始化包可由标准库直接构建。
