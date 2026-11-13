# 报告 AI 配置合并验证记录

日期：2026-11-08（Asia/Shanghai）。合并前主分支：`9ee6a0eb2648a38c8677b0618e325316f0727246`。

## 原交付文件核验

已完整阅读交付目录全部文件：`README.md`、`VERIFICATION.txt`、`MANIFEST.sha256`、`patch.diff`。交付声称的基线 `8d9609e9e7ec2433c3eff7dd5426ddf6f36a69a7` 在当前仓库中不存在；原补丁不能完整直接应用。保留当前报告生成服务的月度活动序列、核算来源有效性验证及现有图片处理后完成适配。

| 文件 | 实际 SHA256（与清单一致） |
| --- | --- |
| patch.diff | `2ccf39abc0764c13f7cf5c9de41c4cae270d51e4167ebdf78c0472da4132319b` |
| README.md | `cbca5c5a1efe039d62b95c9e98de396cef1eb06e415481337232ff0f4161bfc2` |
| VERIFICATION.txt | `be8f8e1729cfeeadeb743e713b3c95a40462457d7b4ee0aadb56ef844364e3ab` |

原补丁的 12 个文件全部纳入本次更新。额外增加 Python `test-llm` 命令、服务器密钥持久配置安装器、专项无 SQL 更新脚本、构建及包验证脚本，并增加对应回归验证。

## 本轮已执行

- `mvnd -pl ruoyi-admin -am package`：22 个模块构建成功，未跳过测试；其中报告模块 189 项测试，188 项通过、1 项条件跳过（该 Java/Python 合同测试需显式设置 `report.contract.python`）。其他模块结果见本地构建日志。
- `npm run build:prod`：在本次主工作区构建成功；存在静态资源体积提示，无构建错误。
- `python -m unittest discover -s tests-report-ai -v`：9 项通过。覆盖模型接口的 URL/模型/密钥传递、HTTP 失败脱敏、缺密钥/无效响应、本地模拟 HTTP 服务下真实 CLI 调用、运行加密密钥生成与复用/恢复/冲突保护、Bash `--check` 不执行应用替换或数据库写入。
- Java 新增回归覆盖：默认密钥 AES-GCM 存储及服务重启后解密、空密钥保留、请求密钥不写入默认配置、错误加密密钥拒绝、普通用户不能保存全局默认、AI 连通性失败阻止校验、关闭 AI 不调用模型、AI 生成转交本次配置且不复用旧文档。
- Git Bash `bash -n`：本次专项部署脚本、全量部署脚本、启动脚本语法检查通过。
- `git diff --check`：通过。

## 包验证

使用 `python tools/server-update/verify-report-ai-package.py <解压目录>` 核对每个文件 SHA256、归档成员实际内容、归档 SHA256、JAR 内新增 AI 服务/配置类和 Mapper、前端 AI 接口及 Python `test-llm` 命令。验证还要求包内不存在 SQL、实际运行密钥、`.env` 或 Python 字节码。实际输出及归档校验文件与本次包一并交付。

# 2026-11-08 部署验收地址修正

旧专项包 `server-report-ai-update-20261108-133215` 的部署脚本误查 `/uncertainty/`。本地 MVC 已复现根地址 500、实际向导页面 200、未登录业务接口 401。仓库已改为检查主前端实际使用的 `/uncertainty/uncertainty-wizard.html`，并增加已安装应用逐文件 SHA256 校验；真实页面或服务失败仍会阻止验收。已执行旧包的服务器可使用单独验收包，见 `docs/report-ai-healthcheck-fix-20261108.md`。服务器运行结果及真实 AI 调用仍需在服务器验收。

## 未执行与限制

服务器 `202.115.17.253:22` 本轮连通性复查不可达，未连接服务器、未上传包、未实际更新生产环境。未使用真实模型凭据进行外部模型调用，未执行生产数据库变更。实际 AI 连通性与 Word/PDF 生成仍需部署后使用正式凭据登录验收。源交付未包含的“肃宁/朔宁”文本修复不在本次范围内。
