# 当前版本服务器增量更新（Xftp/Xshell）

本文件对应 `tools/server-update/build-update.ps1` 生成的增量包。它适用于已有三容器环境的升级，不是空服务器首次安装包。服务器不需要重新下载源码、JAR、前端依赖或 SQL；所有内容在本地构建后通过 Xftp 上传。

## 1. 本地生成更新包

在 Windows PowerShell 的仓库根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File tools/server-update/build-update.ps1
```

如果已经完成本地构建、只需要重新打包：

```powershell
powershell -ExecutionPolicy Bypass -File tools/server-update/build-update.ps1 -SkipBuild
```

生成结果位于 `deploy-package/`：

```text
server-update-TIMESTAMP.tar.gz
server-update-TIMESTAMP.tar.gz.sha256
server-update-TIMESTAMP/
build-logs-TIMESTAMP/
```

上传 `.tar.gz` 和同名 `.sha256` 即可。不要上传本地 `goview.db`、`logs` 或全量数据库初始化脚本。

## 2. 用 Xftp 上传

1. 使用 Xftp 连接服务器的宿主机 SSH 端口。
2. 将更新包和校验文件上传到服务器 `/opt/`。
3. 使用 Xshell 登录同一台宿主机，继续执行下面的命令。

Xftp 只负责传输文件，不要把文件上传到 `ruoyi-web` 容器内部；更新脚本需要在 Docker 宿主机执行并通过 `docker cp` 更新业务容器。

## 3. 服务器预检查

在 Xshell 中执行：

```bash
cd /opt
sha256sum -c server-update-TIMESTAMP.tar.gz.sha256
tar -xzf server-update-TIMESTAMP.tar.gz
cd /opt/server-update-TIMESTAMP
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
export DB_CONTAINER=ruoyi-db
export WEB_CONTAINER=ruoyi-web
export SCREEN_CONTAINER=ruoyi-screen
export WEB_HOST_PORT=53221
export SCREEN_HOST_PORT=53231
export WEB_PUBLIC_URL=http://服务器公网地址:53221
export SCREEN_PUBLIC_URL=http://服务器公网地址:53231
read -rsp 'MariaDB/MySQL root密码: ' MYSQL_ROOT_PASSWORD; echo
export MYSQL_ROOT_PASSWORD
bash deploy-update.sh --check
```

容器名称和端口必须以 `docker ps` 的实际结果为准。`--check` 只检查，不会修改程序或数据库。

## 4. 执行更新

默认不重排角色、不删除旧示例数据，适合普通版本更新：

```bash
set -o pipefail
APPLY_PERMISSION_RESET=false bash deploy-update.sh 2>&1 | tee /opt/server-update-execution.log
```

只有明确需要同步历史权限测试账号和角色编号时，才使用：

```bash
APPLY_PERMISSION_RESET=true bash deploy-update.sh 2>&1 | tee /opt/server-update-permission-reset.log
```

执行脚本会自动完成包校验、数据库和程序备份、增量 SQL、JAR/WAR 和前端替换、服务重启以及 HTTP/Nginx 检查。

备份默认位于：

```text
/opt/ruoyi-backups/时间戳/
```

## 5. 避免服务器联网下载

更新包已经携带后端程序、前端静态资源、SQL、报表 Python 源码和 GoView 资源。首次部署时应在服务器镜像中预装 Java、Python、LibreOffice、中文字体和报表 Python 依赖；更新时不要重新构建镜像。

执行更新前确认 Web 容器已有：

```bash
docker exec ruoyi-web /opt/carbon-report-venv/bin/python -c 'import pydantic,docx,PIL,matplotlib,jinja2,httpx'
docker exec ruoyi-web command -v libreoffice
docker exec ruoyi-web java -version
```

如果这些依赖已存在，更新只通过 Xftp 上传包，不需要服务器下载源码或 Node/Maven 依赖。若更新脚本发现 Python venv 缺少依赖，会尝试执行 pip 安装；完全离线环境应先把同版本 Python venv 或依赖 wheelhouse 做进服务器镜像。

## 6. 验收

```bash
docker exec ruoyi-web pgrep -x java
docker exec ruoyi-screen pgrep -x java
docker exec ruoyi-web nginx -t
docker exec ruoyi-screen nginx -t
docker exec -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" ruoyi-db mysql --protocol=TCP -h127.0.0.1 -P3306 -uroot carbon_emissions -e "SELECT COUNT(*) FROM sys_oper_log; SHOW TABLES LIKE 'energy_run';"
```

浏览器执行 Ctrl+F5，退出后重新登录，检查主系统、采集点、人工录入/审核、报表、能量页面和 GoView。受保护的 `/carbon/energy/runs` 未登录返回 401 属于正常鉴权结果，不应返回 `No static resource carbon/energy/runs`。

## 7. 故障处理

失败时保留日志和 `/opt/ruoyi-backups/时间戳/`，不要重复初始化数据库。恢复前停止 Web/Screen 中的 Java 进程，再按备份恢复 `database.sql`、`web.tgz`、`screen.tgz` 和 `goview-sqllite`（包括 WAL 文件）。不要只回滚 JAR 而忽略已执行的数据库迁移。
