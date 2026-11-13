# 服务器部署与更新说明

本文专门说明 Linux 服务器上的首次部署和已有环境升级。内容覆盖 Docker 三容器部署、Xftp/Xshell 离线更新、验收和故障处理。本地源码初始化、构建和开发机启动请阅读 deployment-guide.md。

> 当前文档最后更新：2026-11-08。密码、审计密钥和公网地址只在服务器终端临时设置，不写入仓库或部署包。

2026-11-08 报告 AI 配置更新使用已有 `sys_config`，无需 SQL 迁移。已有服务器可使用专项无备份更新包，详见 [报告 AI 专项更新说明](report-ai-update-20261108.md)。生产必须持久保存 `CARBON_REPORT_LLM_CONFIG_ENCRYPTION_KEY`；本地 `.runtime` 密钥不能上传。专项安装器生成并复用受保护的服务器运行密钥，后续全量更新保留 AI 环境设置。

碳排放趋势预测模块随本版本完整接入，浏览器只访问 `/prediction/` 和 `/prediction-api/platform/*`；容器内部由 Java 平台 `8086` 调用 Python 算法服务 `8090`，Python 端口不对外开放。更新脚本会安装离线算法依赖、导入 22 张 `prediction_*` 表及权限；只有 `prediction_activity_monthly` 为空时才导入随包提供的 2019-2025 基线数据，已有预测业务数据保持不变。

趋势预测页面采用读写分离：所有已登录用户都可以打开菜单并读取组织、历史活动、模型、任务、预测结果和看板数据；训练、重新预测、异常复核、活动数据录入、因子和规则维护等写操作仍由 `prediction_analyst`、`carbon_accountant`、管理员等角色权限控制。平台管理员按角色键 `admin`、`company_admin`、`system_admin`、`platform_admin` 或 `super_admin`（以及迁移库中的无下划线历史别名）识别；角色名称为 `系统管理员`、`超级管理员`、`平台管理员`、`公司级系统管理员` 或 `公司管理员` 且处于启用状态时同样识别为平台管理员；规范登录名 `admin` 也视为最高管理员，不依赖固定角色 ID。昵称本身不会授予权限。本版新增 `82_prediction_admin_grants.sql`，会幂等补齐这些管理员的五项预测权限。若页面显示“无权限”且表格为空，应先检查预测平台 JAR 是否为本包版本，再检查浏览器是否携带有效登录令牌；不能用取消鉴权的方式绕过写操作保护。

2026-11-03 月度发布更新新增核算节点月度汇总表、统计基准模板的分公司月度汇总表，以及趋势预测自动消费参数 `carbon.trend-prediction.auto-ingest-company-monthly-data`（默认关闭）。迁移不回填旧核算任务，也不会覆盖管理员已设置的参数值；自动投递、重试和 `ingest_status` 更新由后续补齐与入库更新提供，见 5.12 节。

2026-10-28 月度采集点核算数据更新包含模板内物理采集点唯一引用校验、按自然月发布最新成功数据和幂等迁移 `70_collection_point_monthly_data.sql`。全量更新脚本直接执行该迁移，不创建服务器端备份；首次上线不回填历史月度数据。

不确定性分析模块随本版本加入 `uncertainty-app.jar`（容器内端口 8085），由主 Nginx 提供 `/uncertainty/` 页面和 `/api/uncertainty/*` 代理。页面不再手填核算任务 ID，而是通过登录令牌查询当前账号可访问的成功核算任务，按模板名称筛选后选择；模块菜单权限为 `carbon:uncertainty:view`。`71_uncertainty_menus.sql` 仅幂等新增菜单和角色关联，`66/67/68` 三份不确定性表迁移已存在时不会重建或覆盖业务数据。

如果旧包在 `55_data_linkage.sql` 报 `Duplicate entry ... for key uk_template_cycle_revision`，不要删除重复历史任务，也不要初始化数据库；使用包含本修复的新包重新执行即可。新版本不再创建该已废弃的全局唯一索引，`65_calculation_void.sql` 会继续幂等清理残留索引。

本次月度能耗统计分析接入不新增数据库迁移：模型后端接口为 `/api/monthly-analysis/*`，主前端通过 `/carbon-api/monthly-analysis/*` 代理访问。接口使用 `carbon:analysis:view`，不要求模板编辑权限；读取范围由公司、模板、节点、物理采集点权限交集决定。部署时必须保证 `emission_collection_node_data_month` 已存在，缺表会明确返回 503。服务器更新包不执行演示数据初始化，也不重导历史核算任务；正式环境直接查询真实月度结果。演示脚本 `scripts/energy-analysis/monthly_demo.py` 只允许 localhost/127.0.0.1/::1，禁止在生产容器或远程数据库执行。

本地观测示例 `41_local_observation_fixtures.sql` 只放在 `mysql/optional/`，不会由生产更新脚本执行；它依赖本地示例模板，禁止在生产库运行。

## 一、部署架构和默认端口

| 容器 | 内容 | 容器内部端口 | 默认宿主机端口 |
| --- | --- | ---: | ---: |
| ruoyi-db | MySQL 5.7 和 carbon_emissions 数据库 | 3306 | 3306 |
| ruoyi-web | RuoYi 主后端、碳排放模型、不确定性分析、趋势预测 Java/Python、Redis、Nginx 和业务前端 | 80、8081、8082、8085、8086、8090（仅内部） | 80 |
| ruoyi-screen | GoView 后端和前端、Nginx | 80、8083 | 3000 |

更新脚本默认使用以下名称和端口。服务器实际值不同，必须在执行脚本前覆盖环境变量：

~~~text
DB_CONTAINER=ruoyi-db
WEB_CONTAINER=ruoyi-web
SCREEN_CONTAINER=ruoyi-screen
INTERNAL_NETWORK=ruoyi-internal
WEB_HOST_PORT=53221
SCREEN_HOST_PORT=53231
~~~

首次 Docker 编排使用 docker/docker-compose.yml 中的映射（管理系统 80、大屏 3000）；已有服务器增量更新使用更新脚本检测到的宿主机端口，不能混用两套地址。

## 二、服务器前置条件

### 2.1 软件和资源

服务器需要：

- Linux、可使用 sudo 的部署账号。
- Docker Engine 和 Docker Compose V2（可执行 docker compose）。
- 至少 4 个 CPU、8 GB 内存和 20 GB 可用磁盘；报表和大屏数据较多时预留更多空间。
- 防火墙放行实际对外端口，SSH 端口只对管理网开放。
- 首次部署时可拉取 mysql:5.7 基础镜像，或提前离线导入镜像。
- 已准备 Java、Python、LibreOffice/soffice、curl、pgrep、nginx 和报表依赖的运行镜像或应用容器。更新阶段不在服务器下载 Maven、Node、源码依赖或系统软件；中文字体也应提前放入镜像，否则中文 PDF 可能缺字。

检查命令：

~~~bash
docker --version
docker compose version
docker info
df -h
ss -lntp
~~~

### 2.2 首次部署的联网和离线方式

服务器可联网时，首次启动会从镜像仓库获取 mysql:5.7、eclipse-temurin、nginx 和 redis 基础镜像，并在服务器构建 web-main、web-screen 和 MySQL 镜像。服务器不需要连接 GitHub、Maven、npm 或 PyPI。

完全离线时，必须在可联网的构建机完成镜像构建，而不是只准备 MySQL 镜像。构建机上执行：

~~~powershell
cd docker
docker compose build
docker compose config --images
~~~

记录上一条命令列出的全部镜像名称并导出（示例）：

~~~powershell
docker save mysql:5.7 eclipse-temurin:17-jre eclipse-temurin:8-jre nginx redis -o ruoyi-base-images.tar
~~~

如果 compose build 生成了带项目名前缀的 web-main、web-screen 镜像，也一并加入 docker save。用 Xftp 上传 ruoyi-base-images.tar 和 docker 目录，在服务器导入：

~~~bash
docker load -i ruoyi-base-images.tar
~~~

确认所有镜像已导入后，在服务器执行 docker compose up -d（不要加 --build）。若只想离线准备数据库基础镜像，也可以单独导出 mysql:5.7，但 web-main 和 web-screen 的基础镜像及 apt/Python 依赖仍必须提前构建或放入服务器镜像仓库。

## 三、首次 Docker 部署

以下命令在仓库根目录和服务器分别执行。首次部署前确认没有需要保留的同名数据目录；已有环境请跳到第五章，不要用首次初始化流程覆盖生产数据。

### 3.1 本地构建部署材料

在 Windows PowerShell 的仓库根目录完成构建，具体构建命令见 deployment-guide.md，然后执行：

~~~powershell
cd docker
sh copy.sh
~~~

copy.sh 会准备：

~~~text
docker/mysql/db/                         初始化 SQL
docker/web-main/jar/                     主系统和模型 JAR
docker/web-main/html/                    主系统和模型前端 dist
docker/web-main/renderer/                报表渲染模块
docker/web-main/energy-engine/           重空协同真实 Python 求解引擎
docker/web-main/single-train-engine/    单列车能量回收 Python 适配器
docker/web-main/single-train-algorithm/ 单列车能量回收算法与默认参数
docker/web-main/python/                  能耗脚本
docker/web-screen/jar/                   GoView WAR
docker/web-screen/html/                  GoView 前端 dist
docker/web-screen/sqllite/goview.db     GoView SQLite 初始库
docker/web-screen/upload/                GoView 上传文件
~~~

执行前确认 target 和三个 dist 都是本次构建结果。不要把生产服务器上的 goview.db、upload 或 MySQL data 用本地空数据覆盖。

### 3.2 上传目录

首次部署至少上传整个 docker 目录和 docker-compose.yml 所引用的构建上下文。可以先在本地打包：

~~~powershell
cd ..
tar -czf ruoyi-docker-first-deploy.tar.gz docker
~~~

用 Xftp 上传到服务器，例如 /opt/，然后解压并进入目录：

~~~bash
cd /opt
tar -xzf ruoyi-docker-first-deploy.tar.gz
cd /opt/docker
~~~

如果服务器不能运行 tar，应使用 Xftp 直接上传目录，保持 docker/mysql、docker/web-main 和 docker/web-screen 的层级不变。

### 3.3 修改生产配置

编辑 docker/docker-compose.yml：

1. 将 ruoyi-db 的 MYSQL_ROOT_PASSWORD 改成随机强密码。
2. 将 ruoyi-web 的 SPRING_DATASOURCE_DYNAMIC_DATASOURCE_MASTER_PASSWORD 改成同一个数据库密码。
3. 不要把密码、外部地址或审计密钥提交回 Git。
4. 为主系统、模型和 GoView 设置同一个 GOVIEW_AUDIT_SECRET。

推荐在 Xshell 中临时设置审计密钥：

~~~bash
export GOVIEW_AUDIT_SECRET="$(openssl rand -hex 32)"
~~~

首次 compose 文件默认外部端口是 80 和 3000；如果服务器端口被占用，应同时修改 ports、FILE_DOMAIN、SCREEN_PUBLIC_URL 和防火墙规则。

### 3.4 启动数据库并等待初始化

~~~bash
docker compose up -d ruoyi-db
docker compose ps
docker compose logs -f ruoyi-db
~~~

看到 MySQL ready for connections 后按 Ctrl+C 退出日志。确认数据库可用：

~~~bash
docker exec ruoyi-db mysql -uroot -p -e "SHOW DATABASES;"
docker exec ruoyi-db mysql -uroot -p carbon_emissions -e "SHOW TABLES;"
~~~

不要执行 docker compose down -v；该命令会删除数据库卷对应的数据目录。

### 3.5 启动业务容器

服务器可联网、允许 Docker 构建镜像时，执行：

~~~bash
docker compose up -d --build ruoyi-web ruoyi-screen
docker compose ps
docker compose logs --tail=100 ruoyi-web ruoyi-screen
~~~

完全离线且已按 2.2 导入镜像时，使用下面命令，避免 Docker 尝试重新构建或拉取基础镜像：

~~~bash
docker compose up -d ruoyi-web ruoyi-screen
docker compose ps
~~~

确认三个容器状态为 running，再进行第七章验收。

## 四、服务器持久化目录（更新脚本不备份）

以下目录包含业务数据。更新脚本不会覆盖或删除这些目录，也不会在服务器端创建备份；如需长期灾备，请使用独立的主机运维流程：

~~~text
docker/mysql/data/                  MySQL 数据
docker/web-main/uploadPath/         主系统上传文件和报表产物
docker/web-main/redis-data/         Redis 持久化数据
docker/web-screen/sqllite/          GoView goview.db 及 WAL/SHM
docker/web-screen/upload/           GoView 上传文件
~~~

goview.db 保存大屏项目、用户和资源；覆盖或删除它会造成大屏数据丢失。备份时必须同时保留 goview.db、goview.db-wal 和 goview.db-shm（存在时）。

## 五、已有 Docker 服务器的离线增量更新

更新包在本地生成，服务器只接收压缩包，不需要联网下载源码、Maven、Node、Python 或数据库依赖。

### 5.1 本地生成更新包

在仓库根目录执行完整构建和打包：

~~~powershell
powershell -ExecutionPolicy Bypass -File tools/server-update/build-update.ps1
~~~

如果本地构建已经完成，只重新打包：

~~~powershell
powershell -ExecutionPolicy Bypass -File tools/server-update/build-update.ps1 -SkipBuild
~~~

本次只更新主后台、主前端、重空算法、单列车算法、报告渲染器和本轮数据库迁移时，可生成更小的离线包（服务器必须已经部署过完整运行环境和 Python/LibreOffice 依赖）：

~~~powershell
powershell -ExecutionPolicy Bypass -File tools/server-update/build-lightweight-update.ps1 -SkipBuild
~~~

该轻量包不会替换模型后端、GoView、Redis 或生产上传目录；它只用于已有运行环境的定向资源更新。当前全量服务器更新必须使用包根目录的 `deploy-update.sh`，该主流程不执行 `mysqldump`、不创建 `/opt/ruoyi-backups`，也不保留 `.before-*` 应用副本。若服务器没有 `/usr/local/bin/start-ruoyi-web.sh`，请使用完整更新包。历史轻量脚本仅为旧版本遗留工具，不属于本次更新入口。

输出位于 deploy-package/：

~~~text
server-update-TIMESTAMP.tar.gz
server-update-TIMESTAMP.tar.gz.sha256
~~~

压缩包同时包含当前 JAR/WAR、三套前端、报告渲染器、重空协同 Python 求解引擎、单列车能量回收适配器与算法、Linux x86_64 Python 3.10/3.11/3.12 离线依赖、全部增量迁移 SQL、统计查询/能耗分析示例、完整朔黄重空数据，以及 `initial-data/goview/` 下的首次部署 GoView 初始库和上传示例。本版还包含工作量选填、报告科学符号与原生公式、能耗统计树状导航，以及三家公司 70 行设备和 9 张默认图片的安全补齐脚本。更新脚本不会覆盖生产 `goview.db`，也不会自动写入三家公司默认材料。

### 5.2 用 Xftp 上传

1. 使用 Xftp 连接服务器 SSH 主机和端口。
2. 将压缩包及同名 sha256 文件上传到 /opt/。
3. 用 Xshell 登录同一台服务器。
4. 不要把文件直接复制到容器内部，更新脚本会使用 docker cp 处理。

### 5.3 校验并预检查

将时间戳替换为实际文件名：

~~~bash
cd /opt
sha256sum -c server-update-TIMESTAMP.tar.gz.sha256
tar -xzf server-update-TIMESTAMP.tar.gz
cd /opt/server-update-TIMESTAMP
~~~

如果 `sha256sum` 把文件名显示为带有 `\r` 的路径，说明校验文件被 Windows 换行符污染，先执行：

~~~bash
sed -i 's/\r$//' server-update-TIMESTAMP.tar.gz.sha256
sha256sum -c server-update-TIMESTAMP.tar.gz.sha256
~~~

部分旧服务器只有 Docker Compose V1，此时使用 `docker-compose`，或直接使用本文中的 `docker ps`、`docker restart`、`docker logs` 命令；不要把 `docker compose` 当作可用命令。

~~~bash
export DB_CONTAINER=ruoyi-db
export WEB_CONTAINER=ruoyi-web
export SCREEN_CONTAINER=ruoyi-screen
export INTERNAL_NETWORK=ruoyi-internal
export WEB_HOST_PORT=53221
export SCREEN_HOST_PORT=53231
export WEB_PUBLIC_URL=http://服务器地址:53221
export SCREEN_PUBLIC_URL=http://服务器地址:53231

read -rsp 'MySQL root 密码: ' MYSQL_ROOT_PASSWORD
echo
export MYSQL_ROOT_PASSWORD

bash deploy-update.sh --check
~~~

预检查会验证包内文件哈希、三个容器、数据库连接、运行时依赖和 GoView 数据库存在性，不会修改数据库或应用文件。它是基础环境检查，不会执行增量 SQL、完整数据校验或模拟服务重启，不能替代正式更新后的验收。上一版出现的 `sys_menu` 2090 主键冲突已通过权限键幂等迁移修复；能源、报告和 GoView 菜单均不再使用固定主键，重复更新不会重复插入。

--check 只校验 SHA256、容器、数据库、运行时和依赖，不修改数据库或应用文件。容器名称和宿主机端口应以 docker ps 的实际结果为准。

### 5.4 执行正式更新

本次 DQI/全景一致性全量包会自动执行 `69_node_factor_provenance.sql`。更新脚本在停写后直接执行幂等迁移并校验 10 个来源/快照字段全部存在，不创建服务器端备份。迁移不会猜测或改写历史节点覆盖；缺少正式因子来源或 ID 的历史记录需要用户在模型设置中重新选择正式因子。全景旧画布修复工具位于 `dashboard/repair-panorama.mjs`，默认只读，只有明确使用 `--apply` 才会写入指定项目，并回读校验。

普通版本更新使用默认的权限数据保护模式：

~~~bash
set -o pipefail
APPLY_PERMISSION_RESET=false bash deploy-update.sh 2>&1 | tee /opt/server-update-execution.log
~~~

只有明确需要同步固定编号测试角色、测试账号和旧示例数据时才使用：

~~~bash
APPLY_PERMISSION_RESET=true bash deploy-update.sh 2>&1 | tee /opt/server-update-permission-reset.log
~~~

APPLY_PERMISSION_RESET=true 可能覆盖固定编号的角色、账号和部门，真实环境默认禁止使用。更新脚本会创建并复用 `ruoyi-internal` 用户网络，使三个容器通过稳定容器名通信；数据库容器保持运行，不再因更新而重启。随后脚本执行校验、运行时准备、停写、增量 SQL、JAR/WAR/静态资源替换、服务重启以及 HTTP/Nginx 检查。正式更新中途发生错误时，脚本只保留终端日志和容器内临时日志，并尝试重新启动此前停止的 Web/GoView 服务；不会创建数据库、应用文件或 GoView 备份。

如果脚本中途失败，不要重新执行全量初始化 SQL；先保存终端日志、容器日志和迁移结果。

若因某条迁移失败后需要从该迁移继续，先确认失败前最后一条成功迁移，再用包内明确的下一条迁移文件名恢复。例如 `41_local_observation_fixtures.sql` 失败后，修复包应使用 `bash deploy-update.sh --resume-from 42_report_subject_alignment.sql`，避免重放已完成迁移。不要运行本地示例 SQL，也不要初始化数据库。

### 5.5 Python 和报表依赖

更新脚本会从更新包内的 `web-main/wheels/` 离线安装报表和重空求解依赖，不访问 PyPI。Web 容器需要可用的 Python 3.10、3.11 或 3.12；其他 Python 版本应先重建运行镜像。更新前可检查：

~~~bash
docker exec ruoyi-web /opt/carbon-report-venv/bin/python -c 'import pydantic,docx,PIL,matplotlib,jinja2,httpx'
docker exec ruoyi-web /opt/carbon-report-venv/bin/python -c 'import pymysql,numpy,scipy,openpyxl,psutil'
docker exec ruoyi-web test -f /home/ruoyi/energy-engine/database/cli.py
docker exec ruoyi-web sh -c 'command -v libreoffice || command -v soffice'
docker exec ruoyi-web java -version
~~~

LibreOffice/soffice、curl 和中文字体仍属于系统软件，应在基础镜像中准备好；更新脚本会检查 `soffice.bin`、`oosplash` 等实际程序的动态库，并实际执行 `--headless --version`。命令存在但缺少 `libXinerama.so.1` 等动态库时，预检会直接停止，不会等到生成 PDF 时才报错，也不会自行联网安装软件。

openEuler 24.03 容器缺少 `libXinerama.so.1`、`libnss3.so`、`libnspr4.so` 等库时，在正式更新前执行：

~~~bash
docker exec -u 0 ruoyi-web sh -lc 'dnf install -y nss nspr libXinerama'
docker exec -i ruoyi-web sh -s < scripts/verify-libreoffice.sh
~~~

如果 LibreOffice 安装在 `/opt/libreoffice版本/program/`，其中的 `libssl3.so`、`libnss3.so` 等属于发行包自带私有库。预检会在该私有目录加入 `LD_LIBRARY_PATH` 后再执行 `ldd`，不应把这些文件误判为系统依赖；只有加入私有目录后仍显示 `not found` 的库才需要安装系统软件包。

Debian/Ubuntu 镜像对应的软件包为 `libnss3 libnspr4 libxinerama1`。仓库的 Web Dockerfile 已显式安装 `libxinerama1`；Python 包仍从更新包内的 wheelhouse 离线安装，不访问 PyPI。

如果容器没有可用的 dnf 仓库，在宿主机或同版本 openEuler 24.03 x86_64 机器下载 `nss`、`nspr`、`libXinerama` 及其依赖，再用 Xftp 上传并导入容器：

~~~bash
mkdir -p /opt/libreoffice-rpms
dnf install --downloadonly --downloaddir=/opt/libreoffice-rpms nss nspr libXinerama
docker exec -u 0 ruoyi-web mkdir -p /tmp/libreoffice-rpms
docker cp /opt/libreoffice-rpms/. ruoyi-web:/tmp/libreoffice-rpms/
docker exec -u 0 ruoyi-web sh -lc 'rpm -Uvh --replacepkgs /tmp/libreoffice-rpms/*.rpm && ldconfig'
~~~

若宿主机没有 `dnf download`/`--downloadonly` 插件，先安装 `dnf-plugins-core`；RPM 必须与服务器架构和 openEuler 版本匹配。

Windows 安装了 Docker Desktop 时，也可以直接使用官方 openEuler 镜像下载 x86_64 RPM（PowerShell 执行）：

~~~powershell
$RpmDir = Join-Path (Get-Location) 'libreoffice-rpms'
New-Item -ItemType Directory -Force $RpmDir | Out-Null
docker run --rm --platform linux/amd64 `
  -v "${RpmDir}:/out" `
  openeuler/openeuler:24.03-lts-sp4 sh -lc `
  'dnf install -y dnf-plugins-core && dnf download --resolve --alldeps --destdir=/out nss nspr libXinerama'
tar -czf libreoffice-rpms.tar.gz -C $RpmDir .
~~~

将生成的 `libreoffice-rpms.tar.gz` 通过 Xftp 上传到服务器 `/opt/`，再按上面的 `tar`、`docker cp` 和 `rpm -Uvh` 命令导入。官方镜像标签见 `https://hub.docker.com/r/openeuler/openeuler/tags`，仓库主页见 `https://repo.openeuler.org/`。

### 5.6 重空（朔黄）数据集

更新包会把 `zhongkong_data/` 的 28 个数据文件复制到 Web 容器：

~~~text
/home/ruoyi/energy-data/zhongkong_data/
~~~

该目录包含车站、区间、供电臂、储能、列车参数、运行图、扰动回放和电表标定样本。数据状态为规划占位或实验性校准，不能直接当作正式工程结论。

正式更新时，`47_energy_full_dataset.sql` 会自动把 28 个原始文件写入 `energy_dataset_file`，并投影为 33 个主线车站、1390 个线路区间、76 个供电臂、2 种列车参数、2 个储能设备、33 条车站能力记录及 2 列/22 站次运行图。`energy_recovery_agent` 和 PyMySQL、SciPy 等依赖均由更新包部署，不需要在服务器手工下载或导入。

迁移按项目 `shuohuang_demo / v1` 幂等执行，只允许升级旧的三站占位版本或重复同步相同数据摘要。若服务器已有同名但内容不同的版本，迁移会中止并保留更新前自动备份，避免覆盖正式数据。部署脚本会在服务重启前核对上述主要数量，任一数量不符都会停止更新。

### 5.7 三家公司报告默认设备和图片初始化

正式更新不会自动写入报告默认材料。代码更新成功后，按需执行更新包中的两份自包含脚本：

- `report-equipment/init_report_equipment.sh`：补齐肃宁 9 行、原平 4 行、机辆 57 行设备，共 70 行，其中 7 个未知数量保持为空；
- `report-images/init_report_images.sh`：补齐三家公司各 3 张默认图，共 9 张。

两份脚本按有效公司全名查找实际部门 ID，不写死编号。脚本执行前自动备份，使用数据库锁和单个事务，只补空设备清单或缺失图片；已有非空人工设备、有效图片、历史报告快照、核算数据、权限和用户均保持不变。重复执行不会重复导入。`report-defaults/` 是早期首次部署的文字材料工具，本次设备和图片补齐不要再重复执行其中的 SQL。

在解压后的更新包目录确认数据库容器名称：

~~~bash
docker ps --format '{{.Names}} {{.Image}}'
~~~

当前标准容器名为 `ruoyi-db`，执行：

~~~bash
mkdir -p /opt/carbon-report-init
cp report-equipment/init_report_equipment.sh /opt/carbon-report-init/
cp report-images/init_report_images.sh /opt/carbon-report-init/
bash /opt/carbon-report-init/init_report_equipment.sh \
  --container ruoyi-db \
  --database carbon_emissions \
  --user root \
  --backup-dir /opt/ruoyi-backups/report-equipment-$(date +%Y%m%d-%H%M%S)
bash /opt/carbon-report-init/init_report_images.sh \
  --container ruoyi-db \
  --database carbon_emissions \
  --user root \
  --backup-dir /opt/ruoyi-backups/report-images-$(date +%Y%m%d-%H%M%S)
~~~

每个脚本提示 `Database password:` 时输入数据库密码，输入不会回显。不要使用 `bash -x`，也不要把密码写在命令行。分别出现以下标记才表示初始化成功：

~~~text
REPORT_EQUIPMENT_INIT_OK
REPORT_IMAGES_INIT_OK
Completed. Private backup and log directory: ...
~~~

设备结果中的 `INITIALIZED` 表示本次补齐，`EXISTING_EQUIPMENT_KEPT` 表示保留原有非空清单。图片结果中的 `INITIALIZED` 表示本次补齐，`EXISTING_IMAGE_KEPT` 表示保留已有有效图片，`EXTERNAL_REFERENCE_KEPT` 表示保留外部存储引用，需要另行确认引用可读。

初始化后可执行只读检查，并在系统中新建报告核对设备及三张默认图。旧报告已经保存的设备和图片快照不会自动回填。不要执行同目录 `.sql` 版本，因为它与 `.sh` 内嵌内容相同。若公司缺失、重名、未登记、档案编码冲突或结构不完整，脚本会在提交前停止或回滚，并保留备份及日志供排查。

~~~bash
docker cp report-equipment/check_equipment.sql ruoyi-db:/tmp/check_equipment.sql
docker cp report-images/check_images.sql ruoyi-db:/tmp/check_images.sql
docker exec -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" ruoyi-db \
  mysql --default-character-set=utf8mb4 -uroot carbon_emissions \
  -e 'SOURCE /tmp/check_equipment.sql; SOURCE /tmp/check_images.sql;'
~~~

非 Docker MySQL 且服务器已经安装 `mysql`、`mysqldump` 客户端时，改用：

~~~bash
bash /opt/carbon-report-init/init_report_equipment.sh \
  --local --host 127.0.0.1 --port 3306 \
  --database carbon_emissions --user root
bash /opt/carbon-report-init/init_report_images.sh \
  --local --host 127.0.0.1 --port 3306 \
  --database carbon_emissions --user root
~~~

### 5.8 能碳可视化大屏更新与模板导入

本次大屏更新包含两个可选模板：

- `dashboard/templates/shuohuang-management-dashboard.json`：朔黄铁路能碳数据可视化大屏，四项指标和六张图，支持演示/正式数据、年份、公司、能源和单位筛选；
- `dashboard/templates/shuohuang-carbon-dashboard.json`：原朔黄铁路碳排放全景大屏的兼容更新版。

部署脚本会更新主系统 JAR、GoView 前端 `dist` 和 GoView WAR，但不会覆盖生产 `goview.db`、上传目录或现有大屏项目。新模板必须在目标环境创建为新草稿，不能把开发机项目 ID 写入生产环境。

原全景项目无需覆盖 `goview.db`：新版 GoView 前端会兼容既有固定组件 ID，并通过带统一登录令牌的 `/carbon-screen/` 代理读取主系统聚合接口。该修复同时涉及 GoView 静态文件、GoView Nginx 配置和主系统 JAR，因此只执行 `docker restart ruoyi-web` 不足以完成更新，必须运行完整更新脚本；脚本会更新并重启 `ruoyi-web`、`ruoyi-screen`。

GoView 预览页右上角提供可收起的“大屏展示”切换器。切换器默认只占用一个紧凑按钮，展开后列出当前账号数据范围内可访问的已发布项目，也可输入项目 ID；切换过程中保持在预览界面，不改变或挤压原画布布局。项目列表和画布读取沿用 `carbon:screen:view` 权限及现有数据范围，不扩大项目访问范围。

更新完成后，在服务器更新包目录执行：

~~~bash
node dashboard/import-dashboard.mjs --help
export GOVIEW_API_BASE='http://127.0.0.1:53231/api/goview'
export GOVIEW_AUTHORIZATION='Bearer <当前登录用户的完整令牌>'
node dashboard/import-dashboard.mjs dashboard/templates/shuohuang-management-dashboard.json
~~~

导入工具只调用目标环境现有登录接口，创建新草稿并保存画布，不调用 `/sys/login`、不发布、不覆盖旧项目。令牌只在当前终端临时设置，不写入文件、Git 或日志。输出项目 ID 后，在 GoView 项目列表打开编辑器，先预览再由有权限的用户发布。

如需导入原全景模板，替换最后一个文件名：

~~~bash
node dashboard/import-dashboard.mjs dashboard/templates/shuohuang-carbon-dashboard.json
~~~

正式模式的真实数据来自既有合格核算任务；没有合格数据时页面显示“暂无数据”，不会把演示值或零值写入业务表。若接口返回 401/403，按当前统一登录和 `carbon:screen:edit` 权限排查；不要关闭统一鉴权。若 `view=management` 返回旧的 `overall/stations` 结构，说明主系统 JAR 未更新成功。

登录主系统后验收原全景版时，在浏览器开发者工具的 Network 中检查：

~~~text
http://服务器地址:53231/carbon-screen/carbon/screen/dashboard
~~~

响应必须为 JSON 且 `code=200`，不能是 GoView 的 `index.html`。未登录直接使用 `curl` 得到 `code=401` 属于正常鉴权行为；若返回 HTML，说明 `ruoyi-screen` 仍在使用旧 Nginx 配置，应执行完整更新而不是只重启 `ruoyi-web`。

原全景页的实时指标、站点数和排行均由该接口提供。若接口返回 HTML、401、403 或连接失败，页面会明确显示数据接口错误，不能再把取数失败当作真实的零排放。只有已登录请求返回 `code=200` 且 `overall` 聚合本身为零时，才继续核对成功核算任务和统计口径。

### 5.9 在预览界面切换大屏项目

进入“碳排放大屏展示”后会直接显示原大屏，不再先进入单独的选择页面。预览页右上角的“切换大屏”按钮可展开项目选择框，选择当前账号数据范围内已发布的项目后在原预览界面直接切换；控件采用固定悬浮定位，不改变画布大小，也不修改业务数据库或 `goview.db`。

选择列表由 GoView 服务实时读取，不需要在 `.env.production` 中维护项目 ID。项目必须已发布且处于当前账号的数据范围内；如需排查具体项目，也可在展开面板中输入数字项目 ID。

### 5.10 2026-10-19 报告兼容修复验收

本次更新不新增业务表或结构迁移。必须同时更新主系统 JAR、模型 JAR、主前端和 `carbon_report_agent`，不能只替换其中一项。更新后重点检查：

- 机辆分公司 2025 年成功任务可按现有权限查询，已确认归属的任务应包含 4172、4178；
- 4178 的预览应保留五行来源，`wan_m3` 按 `10k_m3` 等值换算；未确认柴油归属和历史热力单位异常仍须提示；
- 部分带入必须明确确认，来源版本或摘要变化、空预填、来源失联时不得删除原填报；
- 已冻结的逐条因子和排放量用于报告生成，后续模板因子修改不得静默改变已冻结报告；
- 正式生成仍拦截历史异常，不允许通过放宽权限、猜归属、补零或重写旧核算结果绕过。

正式更新脚本最后会使用更新包内的合成输入自动生成 DOCX、调用 LibreOffice 转换 PDF，并校验 DOCX 的 `PK` 文件头、PDF 的 `%PDF` 文件头及文件非空。看到 `Report render smoke test passed` 才表示 Python 渲染器与 PDF 转换链路均通过；该测试不读取或修改业务表，也不能替代登录后对真实报告任务的验收。

### 5.11 统计基准、自动核算、DQI 和大屏数据验收

更新后在“碳排放模版管理”选择已设置归属公司的核算模版，点击“设置为统计基准模版”。系统只写入一项公司级参数，不修改因子库：

~~~bash
docker exec -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" "$DB_CONTAINER" \
  mysql --protocol=TCP -h127.0.0.1 -P3306 -uroot \
  --default-character-set=utf8mb4 carbon_emissions -e \
  "SELECT config_key,config_name,config_value FROM sys_config WHERE config_key LIKE 'carbon.statistics.baseline-template.%';"
~~~

进入“统计查询”时，可访问公司的有效基准模版应被默认选中。模版属性中的“自动核算”默认不勾选，未勾选时计划配置不显示，数据变化和计划时间均不会自动发起任务；只有明确勾选并保存后调度器才会执行。

分别编辑电表、化石燃料、外购热力采集点的 DQI A1/A2/A4，保存并关闭弹窗，再次打开确认选择和评分仍存在。若服务器是旧数据库，先确认更新日志中 `67_dqi_collection_points.sql` 已成功执行。

原碳排放大屏应读取成功核算任务的真实结果。当前版本会兼容旧任务缺失的节点分类快照，并在汇总记录全零但核算明细非零时回退到明细；仍为零时应检查成功任务本身是否存在非零核算数据，而不是录入前端演示值。

### 5.12 月度补齐与预测自动入库开关

**两项功能交付默认均为 `false`。** 月度补齐使用碳后端的 `CARBON_MONTHLY_REPAIR_ENABLED`，启用后默认每天上海时间 02:00 扫描上一个自然月。预测自动发送使用系统参数 `carbon.trend-prediction.auto-ingest-company-monthly-data`，存量迁移保留管理员已设置的值。更新前检查两项开关的实际值，部署验收期间保持关闭。补齐会主动发起核算并写入月度表，统计基准模板重算后的发送可能覆盖预测端同月记录。默认关闭留出首次自动写入前的验收窗口。

**开启前检查**

1. 备份月度汇总、预测月度数据、发送队列、预测来源快照和回执相关表及运行配置。存量库先执行 `railway_carbon_prediction/sql/006_monthly_source_snapshot.sql` 和 `tpfhs-9/backend/src/main/resources/schema-update-20261106-monthly-prediction-outbox.sql`，再更新预测引擎和碳后端。将两份迁移纳入实际更新流程，部署前确认目标库和执行结果。
2. 确认每家启用公司的统计基准模板、采集点归属和 `prediction_org.platform_dept_id` 映射，核对能源字典、单位、因子和上月数据范围。机辆公司的总电、牵引电、辅助电分组需要现场核准并验证闭合。热力提交 `HEAT_REPORTED`，单位 GJ。面积热力需要在预测端确认换算依据及待复核行为。
3. 从碳后端所在环境确认预测接口可达，并使用受保护的凭据验证鉴权。调用 `GET /api/v1/prediction/ingest/monthly/capabilities`，确认响应中 `data.source_snapshot` 为 `1`。同容器部署可使用内部地址 `http://127.0.0.1:8090`。

**开启顺序**

1. 在「系统管理 → 系统配置 → 参数设置」查询 `carbon.trend-prediction.auto-ingest-company-monthly-data`，设置为 `true` 并通过正式参数查询确认生效。此参数同时控制凌晨补齐与统计基准模板正式重算触发的自动发送。
2. 向碳后端进程注入 `CARBON_MONTHLY_REPAIR_ENABLED=true`、`CARBON_MONTHLY_PREDICTION_URL` 和 `CARBON_MONTHLY_PREDICTION_API_KEY`，保留现有 Profile 并以 `job` Profile 重启。预测地址和密钥从接收方受保护的运行配置取得，密钥应匹配预测引擎的入库鉴权配置。进程管理器或容器环境必须实际把变量传给 Java；同容器部署使用 `/etc/carbon-integration.env` 时，确认启动脚本加载且变量已导出。现有全量更新会重写容器环境文件，每次更新后重新核对运行进程的实际配置。正常上线沿用默认 02:00，验收前确认没有临时短周期覆盖。

**验收和停用**

- 对账首家公司目标月份的核算任务、月度快照、发送记录与预测回执，逐项核对能源品种、单位、数量、批次及重复扫描结果。`COMPLETED` 表示接收完成，`PENDING_REVIEW` 表示接收待复核，待复核月份应排除出模型训练和预测取数。两种状态均可能对应本地 `ingest_status=1`，以发送状态和预测回执区分。
- 开关关闭期间登记为 `DISABLED` 的快照在启用后不会自动补发。上线记录应区分历史未发送快照与启用后产生的新快照。
- 停用时先把系统参数改回 `false`，再将 `CARBON_MONTHLY_REPAIR_ENABLED` 设为 `false` 并重启碳后端。保留月度快照、发送回执和审计记录，已接收的预测数据按预测端正式流程处理。

## 六、更新验收

### 6.1 容器和进程

~~~bash
docker compose ps
docker exec ruoyi-web pgrep -x java
docker exec ruoyi-screen pgrep -x java
docker exec ruoyi-web nginx -t
docker exec ruoyi-screen nginx -t
~~~

### 6.2 HTTP 和数据库

按实际宿主机端口检查：

~~~bash
curl -I http://127.0.0.1:53221/
curl -I http://127.0.0.1:53221/prod-api/code
curl -I http://127.0.0.1:53221/carbon-model/
curl -I http://127.0.0.1:53231/
docker exec -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" ruoyi-db \
  mysql --protocol=TCP -h127.0.0.1 -P3306 -uroot carbon_emissions \
  -e "SELECT COUNT(*) FROM sys_oper_log; SHOW TABLES LIKE 'energy_run';
      SELECT COUNT(*) AS attribution_stations FROM emission_energy_attribution_station;
      SHOW COLUMNS FROM emission_calculation_template LIKE 'company_dept_id';
      SELECT COUNT(*) AS files FROM energy_dataset_file f
      JOIN energy_project_version v ON v.version_id=f.version_id
      JOIN energy_project p ON p.project_id=v.project_id
      WHERE p.project_code='shuohuang_demo' AND v.version_code='v1';"
~~~

如果使用首次 compose 的 80/3000 端口，将上面 53221/53231 替换为 80/3000。

### 6.3 浏览器功能

强制刷新并重新登录，检查组织、人员、角色权限、采集点、人工录入和审核、能耗统计分析、报表导出、重空协同真实任务及 GoView。受保护接口未登录返回 401 属于正常鉴权结果；模型页面不应出现 No static resource carbon/energy/runs。

## 七、故障处理

### 7.1 更新期间的数据保护

本更新包不包含服务器端备份功能，不执行 `mysqldump`，也不创建 `/opt/ruoyi-backups`。更新脚本只在临时目录保留 SQL 执行日志；正式环境如需灾备，必须由独立的主机运维流程负责，不能依赖本更新包。

### 7.2 回滚原则

1. 先停止会写数据的 Web 和 Screen Java 进程，保留数据库容器运行。
2. 记录失败版本、终端日志、容器日志和已执行的迁移文件。
3. 不要重新初始化数据库；先修复错误后从中断阶段继续。
4. 启动容器并按第六章重新验收。
5. 如果确需恢复数据，只能使用服务器既有的独立灾备方案。

不要直接删除 docker/mysql/data，不要执行 docker compose down -v，不要用空的 goview.db 覆盖生产文件。无法确认数据一致性时，保留现场并从备份副本恢复到临时目录验证。

### 7.3 常见故障

- 容器反复重启：查看 docker compose logs --tail=200 ruoyi-web ruoyi-screen ruoyi-db，优先检查数据库密码、审计密钥和文件权限。
- 页面 404 或旧版本：确认本地重新执行 copy.sh，检查 web-main/html 和 web-screen/html，再执行 docker compose up -d --build。
- 模型页面登录失效：确认主系统 8081、模型 8082 和模型前端使用同一版本，GOVIEW_AUDIT_SECRET 一致，并清理浏览器缓存。
- 能量数据版本在线编辑提示“线路几何没有工作表 [????]”：这不是缺少 MySQL 表的典型错误，而是前后端版本不一致或中文 `sheet` 查询参数被错误解码。确认本次包中的 `ruoyi-admin.jar`、`web-main/energy-engine/` 和主前端同时替换；浏览器 Network 中 `/api/carbon/energy/version-tables` 的 `sheet` 应为 UTF-8 百分号编码（例如 `线路参数` 应显示为 `%E7%BA%BF%E8%B7%AF%E5%8F%82%E6%95%B0`），不要手工输入 `????`。本版本已在 Spring Boot 中固定 Tomcat URI 和 Servlet 编码为 UTF-8，更新后重启 `ruoyi-web` 并强制刷新浏览器。
- GoView 无法跳转：检查 3000/53231 端口、GoView SQLite 文件、RUOYI_AUDIT_URL 和审计密钥。
- 报表失败：检查容器内 Python、LibreOffice、报表目录写权限和磁盘空间。
- 端口冲突：用 ss -lntp 找出占用进程，同时修改 compose ports、更新脚本的 WEB_HOST_PORT/SCREEN_HOST_PORT 和防火墙规则。

### 7.4 更新失败后先恢复服务

如果更新脚本中途退出、管理页面无法打开，先不要重新初始化数据库，也不要执行 `docker compose down -v`。在服务器上按下面顺序恢复：

~~~bash
docker ps -a --filter name=ruoyi-web --filter name=ruoyi-screen --filter name=ruoyi-db
docker logs --tail=200 ruoyi-web
docker logs --tail=200 ruoyi-screen
docker logs --tail=200 ruoyi-db

# 容器已退出时先启动；容器仍运行时该命令返回非零但不会破坏数据
docker start ruoyi-db ruoyi-web ruoyi-screen 2>/dev/null || true
# 这些镜像的容器命令是 bash，重启容器不会自动启动 Java，必须显式执行启动脚本
docker exec ruoyi-web sh -c 'test -x /usr/local/bin/start-ruoyi-web.sh && sh /usr/local/bin/start-ruoyi-web.sh'
docker exec ruoyi-screen sh -c 'test -x /usr/local/bin/start-ruoyi-screen.sh && sh /usr/local/bin/start-ruoyi-screen.sh'
docker ps
~~~

若仍无法启动，先保留终端、容器和迁移日志，修复错误后重新执行对应更新步骤。更新脚本不会生成应用或数据库备份；需要回滚时只能使用服务器既有的独立灾备副本。新热修复包的 JAR 路径是：

~~~text
/opt/carbon-model-hotfix-20261009-2151/web-main/jar/carbon-emission-model.jar
~~~

可先只替换模型 JAR 并重启管理容器：

~~~bash
docker exec ruoyi-web sh -c 'cp /home/ruoyi/carbon-emission-model.jar /home/ruoyi/carbon-emission-model.jar.before-hotfix'
docker cp /opt/carbon-model-hotfix-20261009-2151/web-main/jar/carbon-emission-model.jar ruoyi-web:/home/ruoyi/carbon-emission-model.jar
docker restart ruoyi-web
docker logs --tail=120 ruoyi-web
~~~

如果新 JAR 启动失败，执行：

~~~bash
docker exec ruoyi-web sh -c 'cp /home/ruoyi/carbon-emission-model.jar.before-hotfix /home/ruoyi/carbon-emission-model.jar'
docker restart ruoyi-web
docker logs --tail=120 ruoyi-web
~~~

服务器只有 Compose V1 时，将文档中的 `docker compose ...` 改为 `docker-compose ...`；上述 `docker ps`、`docker exec`、`docker cp`、`docker restart` 命令不依赖 Compose。

## 八、安全要求

- 生产数据库使用独立强密码，禁止保留示例 password。
- GOVIEW_AUDIT_SECRET 至少 32 字节随机值，并在主系统、模型、GoView 中保持一致。
- 更新包和备份权限设为仅部署账号可读，数据库备份不得提交到 Git。
- 生产环境不要执行 docker compose down -v。
- 不要在真实数据上使用 APPLY_PERMISSION_RESET=true。
- 定期将 MySQL、GoView SQLite、上传文件和报表产物复制到独立备份介质，并验证可以恢复。
