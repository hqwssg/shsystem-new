两个算法模块：已有数据库表注释补充包（2026-11-11）

用途
在已有 MySQL 表上补充表 COMMENT 和字段 COMMENT。适用于重空协同 energy_*、
单列车 single_* 两个模块。本包不含业务数据初始化、不修改算法、页面或任务数据。
范围严格限定在 comments.json 列出的 53 张表、667 个字段。
源文件是用户提供的《数据库设计-罗鑫补充字段说明.sql》，并结合当前算法存取代码
补充字段含义、单位、状态、关联关系及 JSON 用途。原文件含 DROP/建库语句，不可执行！

主要文件
  manage_comments.py       读取目标库实时结构，生成、执行和回退注释增量
  comments.json            53 张表的目标中文注释；不包含字段类型或业务数据
  字段说明.txt             同一份注释的可读清单
  check_comments.sql       只读查看注释的 SQL
  test_manage_comments.py  9 项本地单元测试
  验证记录.txt             本地验证结果及范围

执行方式（Python 3.10+、MySQL 8.0，依赖 PyMySQL）
优先使用服务器已有算法 Python 环境。不需要重建 Docker 镜像或重启应用。
以下命令在解压后的目录执行；把数据库地址、用户名、库名替换成实际配置。
密码会提示输入，不写进命令、脚本或交付包。账号需要 SELECT、ALTER 和读取结构权限。
只有对目标业务库有相应授权的整合同事执行。

1. 上传并解压到服务器固定目录，例如 /opt/algorithm-db-comments-20261111。
   确认目标数据库并先进行数据库备份，备份须包含这两个模块表的结构和业务数据。
   暂停提交算法任务，等待运行中任务结束；执行期间不进行其他建表、改字段或写入操作。
   如果 Python 环境缺少 PyMySQL，才执行：
     python -m pip install -r requirements.txt

2. 只生成计划，此时不修改数据库：
     python manage_comments.py plan --host 127.0.0.1 --port 3306 --user root --database carbon_emissions --output ./online-plan --check-data
   online-plan 必须是新目录。生成内容：
     plan.json          目标服务器/库身份、原注释、目标注释、结构及数据校验值
     before-schema.sql  执行前原始表结构，仅供审阅，禁止直接执行作为回退！
     apply.sql          根据目标真实字段定义生成的注释修改 SQL，供审阅
     rollback.sql       该目标库对应的原注释回退 SQL，供审阅
   核对 plan.json 的库名及表清单。missing_tables 表示目标库没有该表，本包跳过且不建表。
   missing_columns 表示缺少的字段，同样只报告、不补建。
   unknown_columns_kept 表示目标库新增且本包不认识的字段，其结构与注释原样保留。
   将整个 online-plan 目录复制保存到容器之外，再继续执行。

3. 确认计划后执行（由工具重读结构并校验，推荐此方式，不直接 source SQL）：
     python manage_comments.py apply --host 127.0.0.1 --port 3306 --user root --database carbon_emissions --plan ./online-plan
   工具逐表使用目标现场 SHOW CREATE 中的字段完整定义，仅替换 COMMENT。
   字段类型、默认值、空值属性、字符集、索引、外键和 CHECK 不按本地定义覆盖。
   同一计划重复执行会跳过已完成部分，不重复插入数据。
   如果计划生成后有数据/结构/注释变化，会停止；先核对原因，再生成新计划。
   不要把本地生成的 plan.json 拿到线上复用，工具会核对服务器身份和库名。

4. 核对结果：
     python manage_comments.py verify --host 127.0.0.1 --port 3306 --user root --database carbon_emissions
   应为 success=true、mismatches=[]。同时查看 missing_*，确认是否符合部署范围。
   apply-result.json 保存执行表清单、数据核对表数、结构核对结果和成功状态。
   也可以在 MySQL 中执行 check_comments.sql，抽查表和字段中文说明。
   注释修改不改变应用查询字段，不需要重跑算法任务、重新导入数据或重启业务服务。

Docker 情况
如果宿主机没有 Python，而 ruoyi-web 内有可用 Python/PyMySQL 环境：
  docker cp ./algorithm-db-comments-20261111 ruoyi-web:/tmp/algorithm-db-comments-20261111
  docker exec -it ruoyi-web sh
  cd /tmp/algorithm-db-comments-20261111
  python3 -c "import pymysql; print('PyMySQL available')"
然后执行上述 plan/apply/verify 命令。若 Python 在虚拟环境里，用其完整可执行路径。
--host 要填写该容器能访问的实际 MySQL 服务名/IP，不要机械使用 127.0.0.1。
plan 目录要用 docker cp 复制回宿主机保存，避免容器重建丢失回退信息。

已存在计划的继续执行（2026-11-11 r5 修复）
如果旧版 apply 因 MySQL 在 ALTER 后把列继承的表默认字符集/排序规则显式展开而报
Schema drift detected，且原计划的 last-error.json 显示部分表已完成：
  1. 保留原 online-plan-20261111-r1 目录及其 plan.json，不执行旧工具的 apply/rollback。
  2. 将 r5 包中的 manage_comments.py、comments.json 复制到该计划旁的独立工作目录；
     comments.json 必须与生成计划时完全相同。不要改动 plan.json 或清除 last-error.json。
  3. 确认已完成表的当前注释为目标注释，且 last-error.json 的 completed_tables 与操作记录相符。
  4. 用 r5 工具对原计划执行 apply。工具会先校验计划内所有表的结构、注释和数据，
     已到目标注释的表会跳过，其余表继续执行。若出现任何其他结构漂移或数据变化，
     工具会在执行后续 DDL 前停止；不要重建计划或改用 rollback，先保存错误记录并排查。
  5. 成功后执行 verify，要求 success=true、mismatches=[]，并检查 missing_* 范围。
     将 apply-result.json、verify 输出和 last-error.json 一并留存。

兼容旧计划：r5 会比较原版哈希、当前规范化哈希和旧计划兼容哈希。兼容哈希仅移除与表默认
完全一致的显式列 CHARACTER SET，保留 COLLATE 参与比较，以匹配 r1 计划已保存哈希。
CHECK 中 MySQL 将 ASCII 常量 introducer 从 _gbk 重序列化为 _utf8mb4 也按原有规则兼容。
只有任一哈希与计划值完全匹配才允许继续，执行后的结构核验同样如此。此机制不改写计划，
不忽略列类型、非默认字符集/排序规则、默认值、索引、外键或 CHECK 差异。若均不匹配，
工具仍会在任何后续 DDL 前停止。

回退及失败处理
  python manage_comments.py rollback --host 127.0.0.1 --port 3306 --user root --database carbon_emissions --plan ./online-plan
此命令仅恢复该计划保存的原注释，不回滚任务和业务数据。保留相同 comments.json。
回退结果写入 rollback-result.json，逐表核对原结构和原注释，且核对执行前后数据一致。
verify 命令是“与本包新注释比较”，回退后它显示不匹配属于正常；以回退结果为准。
MySQL ALTER 是隐式提交，不支持用一次 ROLLBACK 撤销整包。
若中途失败，last-error.json 记录已完成表；可在排除原因后用同一计划继续执行或回退。
不要在部分执行后直接丢弃原计划，否则将丢失部分表的原注释。

维护窗口说明
优先尝试 ALGORITHM=INPLACE、LOCK=NONE。部分 MySQL CHECK 组合即使只改注释也要求
MySQL 内部 COPY 算法：仅在计划启用 --check-data 时才允许此回退，并使用 LOCK=SHARED。
它可能暂时阻塞写入、占用额外磁盘；不是执行 DROP/CREATE 业务表，但需要维护时段。
复制阶段发生约束或数据异常会报错，不会删除约束、关闭外键、清空或补写业务数据。
执行结果 mysql_internal_copy_tables 会列出这些表。本地此次为 4 张。
--check-data 读取完整数据计算校验值，不导出数据内容，数据量大时需要更多时间。
原始备份、计划及执行记录请留在服务器受控目录，不放到前端可下载位置。

注意 MySQL 会将部分旧 CHECK 中 ASCII 字符串的 _gbk 标记重记为 _utf8mb4。
工具仅对这种 ASCII 常量标记作等价处理；非 ASCII、显式 COLLATE、二进制及其他结构仍严格比较。

边界
只验证了本地 MySQL 8.0.30；线上实际 MySQL 版本、权限、表大小和磁盘需由整合同事复验。
未自动连接或修改线上库。本包不包含私有配置、密钥、数据库备份或原始全库建表文件。
