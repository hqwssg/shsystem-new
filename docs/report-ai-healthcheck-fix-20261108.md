# 报告 AI 更新后验收（2026-11-08）

旧专项部署脚本检查 `/uncertainty/`，Nginx 将其转发到不确定性 JAR 的 `/`。该应用没有根页面；通用异常处理将缺少静态资源的异常返回为 HTTP 500。主前端实际使用 `/uncertainty/uncertainty-wizard.html`，之前全量部署脚本也检查该地址。

本地 MVC 复现结果：根地址 500、实际向导页面 200、未携带登录令牌的业务 API 401。这说明原验收地址有误；不能仅据此推断服务器其余服务正常，或 AI 已完成真实调用。

## 已执行旧包后的处理

保留服务器 `/opt/server-report-ai-update-20261108-133215` 解压目录，将本验收包和同名 `.sha256` 上传 `/opt`，校验并解压，进入目录后执行：

```bash
export REPORT_AI_PACKAGE=/opt/server-report-ai-update-20261108-133215
export DB_CONTAINER=ruoyi-db
export WEB_CONTAINER=ruoyi-web
export SCREEN_CONTAINER=ruoyi-screen
export WEB_HOST_PORT=53221
export SCREEN_HOST_PORT=53231
set -o pipefail
bash verify-report-ai-runtime.sh 2>&1 | tee /opt/report-ai-runtime-verification-20261108.log
```

本脚本校验原包完整性，并逐项比对已安装主 JAR、主前端、报告 Python 源文件和启动脚本的 SHA256。随后检查主系统、核算模型、不确定性实际页面、预测平台、大屏、Python 预测健康接口、报告 CLI 和运行密钥权限。未登录的不确定性、预测组织接口必须返回 401/403；真实页面返回 500、服务未启动或文件未完整替换时仍会失败。

本验收包不覆盖应用、不重启服务、不执行 SQL、不读写业务数据、不创建服务器更新备份、不输出或替换任何密钥，也不需要数据库密码。此前启动脚本已尝试重启应用；此处只验收其运行结果。请勿运行旧的 `apply-uncertainty-hotfix.sh`，它包含本次不需要的迁移与备份。

若验收失败，请保留完整输出。如不确定性实际页面仍异常，在服务器查看：

```bash
docker exec ruoyi-web sh -c 'pgrep -af "[u]ncertainty-app.jar"; curl -i --max-time 10 http://127.0.0.1:8085/uncertainty-wizard.html'
docker exec ruoyi-web tail -n 160 /home/ruoyi/logs/uncertainty-app.log
```

全部自动检查通过后，仍需登录报告校验页，使用有效 AI 凭据测试连接并生成报告，确认配置持久化及实际生成结果。自动验收无法替代真实模型调用。

## 后续构建

仓库部署脚本与构建器已统一使用正确页面，并复用本次健康检查和逐文件校验。旧包保持原始校验值；验收包可用于已执行旧包的服务器，无需再次上传整个应用。
