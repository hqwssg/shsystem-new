# 服务器更新步骤（2026-11-13）

本包只替换应用程序文件并重启 `ruoyi-web` 内已有应用启动器，不重建容器、不重启数据库、不执行数据库迁移、不备份服务器文件，也不自动导入演示数据。执行前必须确认算法队列为空；脚本发现 `pending`、`validating`、`running` 或 `queued` 任务会直接退出。可选演示数据入口只新增隔离的演示记录，不创建服务器备份；应用更新与演示数据初始化是两个独立步骤。

## 1. 上传与校验

将 `server-update-20261113-four-updates-r2.tar.gz` 和同名 `.sha256` 上传到 `/opt`，在服务器执行：

```sh
cd /opt
sha256sum -c server-update-20261113-four-updates-r2.tar.gz.sha256
tar -xzf server-update-20261113-four-updates-r2.tar.gz
cd /opt/server-update-20261113-four-updates-r2
: "${MYSQL_ROOT_PASSWORD:?请先使用随包交付指令设置数据库密码环境变量}"
sh deploy-integration-20261113.sh --check
```

`--check` 只校验包、容器、Python 环境、数据库连通性、算法队列、静态文件/JAR 和 Python 语法，不改已安装文件。

## 2. 应用更新

确认检查输出 `CHECK_OK` 后执行：

```sh
set -o pipefail
sh deploy-integration-20261113.sh 2>&1 | tee /opt/server-update-20261113-four-updates-r2.log
```

成功标志是输出 `PASS: web HTTP status ...`，这里只证明首页与应用端口可用，不代表业务全流程已验收。脚本使用服务器现有 `/usr/local/bin/start-ruoyi-web.sh`，保留既有私有环境和密钥；失败时不要重复覆盖，先查看 `/home/ruoyi/logs/*.log` 与容器日志。发布期间停止提交新任务并保持算法队列为空；应用会短暂重启，数据库、GoView 和 HTTPS 入口配置不变。应用程序包只包含本次涉及的两个完整前端、碳核算 JAR 和清单中的 Python 文件，不是整机环境或数据库备份。

## 3. 可选演示数据初始化

应用更新成功并完成页面验收后，才按需要执行。该步骤会写入隔离的演示项目/版本，不会自动运行任务：

```sh
cd /opt/server-update-20261113-four-updates-r2
: "${MYSQL_ROOT_PASSWORD:?请先使用随包交付指令设置数据库密码环境变量}"
sh initialize-algorithm-demo-no-backup-20261113.sh
```

脚本默认将演示数据绑定给现有网站账号 `admin`；如目标账号不同，可在执行前设置 `DEMO_ACCOUNT=实际账号`。脚本检查部门绑定、权限、重复数据及人工修改冲突，并在事务中写入隔离的演示数据，不执行备份、不创建任务或结果。看到 `ALGORITHM_DEMO_INIT_OK` 和 `Completed` 才算完成。若不需要演示数据，跳过本节。初始化失败或出现 `EXISTING_DATA_DIFFERS`、`BINDING_DISABLED` 时停止，不使用 `mysql --force`。

## 4. 回退与验证

本部署脚本不保存旧应用副本；如需回退，使用此前已持有的发布包或旧提交重新构建，恢复两个完整静态目录、旧 JAR 及配套算法源码。确保 `index.html` 与资源来自同一版本。不要只替换 `index.html`，不要在 Vue 3 的 `node_modules` 上构建旧 Vue CLI。完成后验证登录/菜单、人工录入、碳核算统计、报告生成下载、模型页面及算法表单；演示数据任务必须实际执行后再判断结果。

本次 SSH 检查发现 22 端口连接失败、2213 端口认证未通过；未在服务器执行更新。以上为交付指令，不代表线上已经更新。密码不提交至 Git，使用交付回复中的现有服务器凭据设置命令即可，无需交互输入。
