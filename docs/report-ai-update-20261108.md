# 报告 AI 配置专项更新（2026-11-08）

本次整合了交付目录 `carbon-report-ai-config-patch-20261108` 的全部 4 个文件。三项文件校验值均匹配 `MANIFEST.sha256`。当前项目基线为 `9ee6a0eb`，交付声明的 `8d9609e9` 在当前仓库不存在；保留当前月度报告与核算来源校验逻辑后合并。额外补齐交付所依赖、当前基线缺少的 Python `test-llm` 命令。

报告校验页可填写 AI 地址、模型和明文 API Key；具有报告校验权限的用户可读取并使用默认配置，只有管理员可保存全局默认。默认 API Key 以 AES-GCM 加密存入已有 `sys_config`；本次填写的密钥只进入报告生成进程环境，不写入报告草稿、任务快照或命令行。启用 AI 时会实际测试 chat completion 接口，失败阻止本次校验通过；切换配置后需重新校验。AI 生成不复用旧文档缓存，非 AI 生成保留原有缓存行为。

## 更新范围

本次为已有环境的专项包，包含当前主系统 JAR、主前端、报告 Python 渲染模块和启动脚本。不执行 SQL 迁移、数据库初始化、权限重置、演示数据写入或任何服务器更新备份。保留其他 JAR、算法、数据库、GoView SQLite、上传文件和运行配置。更新时重启 `ruoyi-web` 中的应用服务；数据库与 GoView 容器保持运行。

服务器需已完成此前月度修复更新，具备 `/etc/carbon-integration.env`、`/usr/local/bin/start-ruoyi-web.sh` 和 `/opt/carbon-report-venv/bin/python`。`--check` 检查现有运行环境和包文件，不会替代登录后功能验收。

## 密钥持久化

生产加密密钥由服务器首次运行更新脚本时生成，或复用现有 `CARBON_REPORT_LLM_CONFIG_ENCRYPTION_KEY`。实际运行配置分别保存于宿主机 `/opt/ruoyi-runtime/report-ai/llm-encryption.key` 和 Web 容器 `/etc/carbon-report/llm-encryption.key`，权限分别为目录 700、文件 600。这些是受保护的运行配置，不是项目更新备份；不能删除、重新生成或提交 Git。容器重建后，重新执行本专项更新可从宿主机恢复同一把密钥。若数据库已保存加密 API Key 但找不到原密钥，更新会停止，需恢复原加密配置；不会静默替换。

`CARBON_REPORT_LLM_BASE_URL`、`CARBON_REPORT_LLM_MODEL`、`CARBON_REPORT_LLM_API_KEY` 可以继续提供服务端回退值；已有 `/etc/carbon-integration.env` 保留不变，后续全量部署器也保留这些配置。禁止上传本机 `.runtime` 密钥。

## 执行

将包和校验文件上传服务器 `/opt`，按最终交付的实际包名校验、解压并进入包目录。设置 `MYSQL_ROOT_PASSWORD`、容器名称、Web 端口后：

```bash
bash deploy-report-ai.sh --check
set -o pipefail
bash deploy-report-ai.sh 2>&1 | tee /opt/report-ai-update-20261108.log
```

脚本的数据库操作仅查询 `sys_config` 加密项是否存在，实际保存 AI 配置由管理员在界面操作。日志不输出加密密钥或 API Key。

## 验收

重新登录，进入报告校验页，打开 AI 开关，确认可以读取地址、模型、密钥。管理员保存全局默认后刷新并重启主服务，配置应仍可解密。普通用户可读取及使用配置，但不能保存默认值。先用错误密钥确认校验失败，再用有效凭据测试连通性并生成 Word/PDF；关闭 AI 后原报告生成应正常。真实模型调用需服务器有可达模型地址和有效凭据，本地离线测试无法代替。
