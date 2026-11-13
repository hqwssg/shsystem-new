# shsystem 三类服务器拆分迁移记录

本文记录本次将上游 `hqwssg/shsystem` 最新代码整理为应用服务器、Python 算法服务器和数据库服务器的过程。以后重新拉取上游代码时，按本文复做并更新基线信息。

## 本次基线

- 上游仓库：`https://github.com/hqwssg/shsystem.git`
- 上游提交：`85378f896c25e0e86e01d4998f54f12faeaf2760`
- 目标仓库：`https://github.com/hqwssg/shsystem-new.git`
- 改造分支：`main`
- 目标旧提交：`a51f29c381205e3a7c3a62856ba1804704988166`

上游代码先作为完整基线导入，再叠加本记录中的拆分文件。不要把旧的 `target`、`dist`、日志、数据库数据或真实 `.env` 文件带入提交。

## 目标边界

```text
浏览器 -> sh-app:80
             RuoYi、GoView、预测平台 Java、碳排放模型、不确定性服务、Nginx、Redis
       -> sh-python:8090/8091
             预测 API 和报告、趋势、能源回收、单列车算法内部 API
       -> sh-db:3306
             MySQL 8.0（或经厂商确认的 TBase/CERDB）
```

三类服务器是职责边界，不强制等于三个容器。当前 MySQL 路线使用 `sh-app`、`sh-python`、`sh-db` 三个服务；应用容器内部仍包含多个 Java 服务和 Nginx，Python 容器集中运行算法进程。

## 已落地的文件

### 应用服务器

- `docker/three-container/app.Dockerfile`：构建 RuoYi、GoView、预测平台、碳排放模型和不确定性服务，并安装 Nginx、Redis、LibreOffice。
- `docker/three-container/app-start.sh`：启动各 Java 服务、Redis 和 Nginx。端口为 RuoYi `8081`、碳排放模型 `8082`、不确定性 `8085`、预测平台 `8086`、GoView `8087`。
- `docker/three-container/nginx.conf`：统一代理前端、RuoYi、GoView、预测平台和 Python 服务。
- `compose.app.yml`：单独构建/运行应用镜像的模板。

### Python 算法服务器

- `docker/three-container/python.Dockerfile`
- `docker/three-container/python-start.sh`
- `services/python_service/`：受令牌保护的内部任务 API，限制任务名和 `/srv/shared` 路径。
- `compose.python.yml`

Python 数据库配置支持 `DATABASE_DSN`、`DATABASE_DRIVER`、`DATABASE_HOST` 等通用变量，同时兼容原有 `CERDB_*` 和 `ENERGY_DATABASE_URL`。MySQL 路线使用 PyMySQL；TBase/CERDB 路线必须使用厂商确认的驱动和 DSN，不能只替换变量名。

### 数据库服务器

- `compose.mysql-three-container.yml`：MySQL 8.0、健康检查、持久化目录和只绑定本机的 `3306`。
- `docker/mysql/db/`：按文件名顺序执行的完整初始化脚本，覆盖 RuoYi、碳排放、能源、单列车、不确定性、预测、DQI 和趋势预测模块。
- `docker/copy.sh`：从源码目录重新生成并复制初始化 SQL，以及构建后的部署产物。只需要数据库脚本时，可按其中 SQL 复制段执行，避免把构建产物提交到 Git。

## 重新拉取最新版后的复做步骤

1. 记录当前远程、分支、提交号和数据库/共享目录备份；停止正在写入的旧服务。
2. 拉取上游最新提交，保留一份干净源码备份，然后把本仓库的拆分文件重新叠加到新基线。
3. 检查上游是否改变 Maven 模块、前端目录、Python 入口、端口或环境变量；同步更新两个 Dockerfile、启动脚本、Nginx 和 Compose。
4. 运行 `python tools/zhongkong/generate_dataset_sql.py`，再执行 `docker/copy.sh` 的 SQL 复制段，确认 `docker/mysql/db/` 中包含 `zz17` 至 `zz24` 及能源、单列车、不确定性脚本。
5. 复制 `.env.mysql.example` 为部署机上的 `.env`，填写镜像、共享目录、数据库账号和随机令牌。真实 `.env` 不提交。
6. 检查配置：

   ```powershell
   docker compose --env-file .env -f compose.mysql-three-container.yml config
   docker build -f docker/three-container/app.Dockerfile -t shsystem-app:<version> .
   docker build -f docker/three-container/python.Dockerfile -t shsystem-python:<version> .
   ```

7. 按“数据库 -> Python -> 应用”启动并验证健康检查、登录、报告、趋势预测、能源回收、单列车算法、文件上传和 GoView。
8. 记录新的上游提交、镜像版本、数据库路线、验证结果和未解决问题，再提交并推送 `main`。

## 配置要点

- 应用使用 `DATABASE_JDBC_URL`、`DATABASE_USER`、`DATABASE_PASSWORD`；Python 使用 `DATABASE_DSN` 或 `DATABASE_*`。
- `PYTHON_SERVICE_URL` 和 `PREDICTION_BASE_URL` 只指向内网 `sh-python`，Python 的 `8090/8091` 不直接映射公网。
- 应用和 Python 必须挂载同一个宿主机目录到 `/srv/shared`，用于上传文件、报告、算法输入输出和 GoView 数据。
- DSN 中的数据库密码若含 `@`、`:`、`/`、`#` 等字符必须 URL 编码；生产环境使用最小权限账号和随机令牌。
- TBase/CERDB 的镜像、许可证、CN/DN/GTM、JDBC 驱动、DDL 和初始化方式需由厂商确认；本仓库的 MySQL Compose 不能直接替代生产 TBase 集群。

## 本次验证边界

已完成：Python `compileall`、MySQL Compose 配置渲染、数据集 SQL 生成、三个 Java Maven 模块构建，以及初始化 SQL 文件检查。

应用镜像首次构建发现 GoView 前端锁定的 pnpm 11 需要 Node.js 22（使用 Node 20 会因缺少 `node:sqlite` 失败），因此构建阶段已统一调整为 `node:22-bookworm`，并固定使用 pnpm 9 安装以兼容锁文件中的依赖构建脚本。Python 镜像的 CPU 版 PyTorch 安装索引、单列车算法目录和预测产物共享路径已补齐。

Java 调用链已恢复为 Python 内部 HTTP 任务 API：报告渲染、Markdown/Word 导出、能源回收、单列车和蒸汽计算均通过 `PythonServiceClient` 调用；应用容器在 `PYTHON_SERVICE_REQUIRED=true` 时不会启动本地 Python。

本次按“只调整本地代码并同步 GitHub”的范围结束，未创建或启动容器。真实 MySQL 初始化和端到端业务验收尚未完成；Compose 配置通过不代表数据库或业务运行成功。部署前仍需在目标服务器验证数据库连接、登录、报告、趋势预测、能源回收、单列车算法、文件上传和 GoView。

本地验证结果：Python `compileall` 通过；数据集 SQL 生成校验通过（28 个文件、33 个车站、1390 个区间等）；`ruoyi-admin -am package -DskipTests` 通过。由于本机不执行容器流程，镜像构建和数据库初始化未作为本次完成条件。


## 12. 2026-11-14 GitHub 同步结果

- 本地拆分提交：`fc9c4e5625f7ece8b767dbb1f036202ea0aa1fda`。
- 因目标仓库旧历史存在缺失对象，GitHub 接收增量 pack 时返回 `did not receive expected object d1da62a...`；为确保目标仓库可完整拉取，基于已验证的当前工作树创建独立根提交：`41bb4959e36e2e8c91d97c3f9354e198c4276024`。
- 已使用 `git push --force --no-thin origin main` 覆盖同步至 `hqwssg/shsystem-new.git`，远端 `main` 已指向 `41bb4959e36e2e8c91d97c3f9354e198c4276024`。
- 本次仅调整本地代码并同步 GitHub，未创建或启动容器。
