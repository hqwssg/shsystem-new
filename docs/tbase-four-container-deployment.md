# CEOS 1.1 环境中的 TBase 五容器部署操作说明

本说明把参考项目的服务器操作方法适配到当前 TBase 五容器方案。参考项目中的 SSH 登录、上传部署包、创建 Docker 网络、按容器名互通、`docker ps`/`docker exec`/`curl` 检查等做法可以沿用；其中 MySQL 容器、旧项目容器名、旧端口、密码和脚本不能直接沿用。

服务器实际系统为 CEOS 1.1，内核 `4.19.90-2305.1.0.0200.ce1.x86_64`，架构 `x86_64`。后续系统包必须匹配该环境；不要直接使用仅标注为其他发行版的包。单台服务器仅用于测试模拟。TBase 数据库是否能在该主机或容器中运行，仍需依据当前版本兼容性资料验证。

## 1. 容器拓扑

本方案用于单台 Linux x86_64 主机上的测试模拟，共五个容器。三个 TBase 容器用于模拟 TBase 管理器要求的三个逻辑节点；它们仍共享同一台物理服务器的内核、磁盘和故障域，不等于三台服务器，也不提供物理机级高可用。

| 容器 | 用途 |
| --- | --- |
| `sh-app` | RuoYi、GoView、趋势预测 Java 平台、Nginx、Redis |
| `sh-python` | 报告、趋势预测算法、重空协同、能量回收 Python API |
| `tbase-node1` | TBase 虚拟节点一，承载厂商确认的管理/协调组件角色 |
| `tbase-node2` | TBase 虚拟节点二，承载厂商确认的数据节点及所需管理组件角色 |
| `tbase-node3` | TBase 虚拟节点三，承载厂商确认的第三个逻辑节点角色，使用独立数据目录 |

项目目录中的安装介质为 TBase/CERDB 2.15 OSS RPM 和 GIS RPM，不是 openGauss CERDB 介质。TBase OSS 对外安装手册要求至少两台主机、安装必选 OSS 角色，并在 CN/DN 节点安装 Agent；数据库节点通过 OSS 初始化。三个容器共用一台宿主机的内核、磁盘和网络，只能作为实验性“虚拟三节点”，不能视作三台独立主机、生产集群或厂商已支持的容器化部署。即使 TBase 最低要求是两台物理主机，三个容器也只能模拟逻辑拓扑，不能替代第二台物理主机。

TBase 手册的操作系统章节列出的是已测试的 CentOS 6.7 环境，并未由此证明 TBase 2.15 OSS RPM 支持 openEuler。openEuler 服务器可以运行 Docker，但 Docker 能运行不代表 TBase RPM、OSS 管理组件、SSH 安装脚本和内核参数在容器中兼容。

现有交付物是 RPM/安装压缩包，没有已确认的官方 TBase 容器镜像或容器安装步骤。因此在厂商确认容器化受支持，并给出镜像制作、权限、SSH、网络、存储、角色分配及初始化要求前，不要把 RPM 直接塞入普通容器镜像后宣称已部署。若厂商不支持容器部署，请改用两台虚拟机/物理机安装 TBase；应用和 Python 仍可用容器。

## 2. 主机准备

先确认宿主机操作系统、CPU 架构和资源满足所选 TBase 版本要求。安装手册列出的基础配置为每台至少 4 核、8 GB 内存、500 GB 磁盘；正式规划章节中数据节点建议资源更高。三个节点容器争用同一宿主机资源，宿主机应在厂商评估后分配足够 CPU、内存和磁盘空间。不得把此实验配置当作高可用部署。

在 Linux 宿主机执行基础检查。磁盘空间数值会随安装变化，当前值以实时 `df` 输出为准：

```bash
uname -m
cat /etc/os-release
nproc
free -h
df -h
docker version
docker compose version || docker-compose --version
sudo systemctl enable --now docker
```

必须使用厂商支持的操作系统、内核和 x86_64 介质组合。若实际使用 ARM 介质，宿主机架构和容器镜像也必须匹配；不要混用 ARM 与 x86_64 RPM。

### 2.1 openEuler 服务器检查

以下命令用于确认参考项目中的 openEuler 服务器环境，不代表已经完成 TBase 安装：

```bash
cat /etc/os-release
uname -r
uname -m
sudo systemctl status docker --no-pager
docker info
docker compose version || docker-compose --version
```

若显示 `docker: 'compose' is not a docker command`，说明 Docker Engine 已有，但 Compose v2 插件未安装；若 `docker-compose --version` 能显示版本，则服务器安装的是旧版独立命令。优先安装 Compose v2 插件。先检查当前软件源能提供的包：

```bash
cat /etc/openEuler-release 2>/dev/null || cat /etc/os-release
docker --version
docker-compose --version
rpm -qa | grep -Ei 'docker|compose'
sudo dnf list --available '*compose*'
```

如果软件源中有 `docker-compose-plugin`，按现场软件源安装并验证：

```bash
sudo dnf install -y docker-compose-plugin
docker compose version
```

若软件源只提供独立的 `docker-compose` 包，则安装后使用旧命令：

```bash
sudo dnf install -y docker-compose
docker-compose --version
```

这种情况下，将本手册后续命令中的 `docker compose` 写法替换为 `docker-compose`。如果 `dnf` 找不到这两个包，不要从不明来源下载二进制文件；先确认系统版本、已启用仓库及现场离线软件包来源，再安装与当前 Docker Engine 匹配的 Compose。安装完成后再继续基础镜像和容器网络检查。不要直接执行未经现场批准的全量系统升级；Docker/Compose 包名、版本和仓库地址应以现场软件源为准。

若检查结果与本项目服务器一致（`/etc/os-release` 显示 `CEOS 1.1`、Docker `18.09.0`、`docker-compose 1.22.0`），说明系统已有独立版 Compose，不需要再安装插件。后续本手册中的 `docker compose` 命令应写成 `docker-compose`，例如：

```bash
docker-compose --version
docker-compose -f compose.tbase-five-container.yml config
```

该环境的 `dnf` 仓库若因 DNS 无法解析而报错，不影响已安装的 `docker-compose`；不要为运行现有 Compose 命令而修改仓库或安装来源不明的软件。系统标识为 `CEOS 1.1`，不能仅凭其基于 openEuler 就认定 TBase 2.15 OSS 已认证兼容；仍须取得厂商对 CEOS 版本、内核及容器部署方式的确认。

可按参考项目验证 openEuler 基础镜像和临时 Docker 网络。该网络只供下方网络连通性测试使用，Compose 部署会按配置自行创建应用网络：

```bash
docker pull hub.oepkgs.net/openeuler/openeuler:24.03-lts
docker network inspect shsystem >/dev/null 2>&1 || \
  docker network create shsystem
```

这个基础镜像只适合验证 Docker 和网络，不可直接作为 TBase 节点镜像，除非厂商明确确认 TBase RPM、OSS 安装脚本及依赖支持该镜像。

仅做网络连通性验证时，可以临时创建两个 openEuler 容器。先检查名称是否已被占用；若已存在，选择其他测试名称，不要删除已有容器：

```bash
docker ps -a --filter name=^/tbase-netcheck-1$ --filter name=^/tbase-netcheck-2$
docker run -dit --name tbase-netcheck-1 --hostname tbase-netcheck-1 \
  --network shsystem hub.oepkgs.net/openeuler/openeuler:24.03-lts /bin/bash
docker run -dit --name tbase-netcheck-2 --hostname tbase-netcheck-2 \
  --network shsystem hub.oepkgs.net/openeuler/openeuler:24.03-lts /bin/bash
docker exec tbase-netcheck-1 getent hosts tbase-netcheck-2
docker exec tbase-netcheck-2 getent hosts tbase-netcheck-1
```

这些临时网络检查容器没有安装 TBase，不能执行 OSS 安装、CN/DN/GTM 初始化或数据库连接验收。验证结束后，只能删除明确由网络检查步骤创建的临时容器；不要对 `tbase-node1`、`tbase-node2`、`tbase-node3` 执行清理命令。

### 2.2 服务器登录和文件上传

参考项目使用 SSH/Xftp 将部署包放入服务器。按现场端口和账号替换占位符：

```bash
ssh -p <SSH_PORT> <USER>@<SERVER_IP>
mkdir -p /opt/shsystem-tbase
mkdir -p /opt/shsystem-tbase/images
mkdir -p /opt/shsystem-tbase/vendor/tbase
mkdir -p /opt/shsystem-tbase/tbase/node1
mkdir -p /opt/shsystem-tbase/tbase/node2
mkdir -p /opt/shsystem-tbase/shared
mkdir -p /opt/shsystem-tbase/app-data
mkdir -p /opt/shsystem-tbase/logs
mkdir -p /opt/shsystem-tbase/backup
```

所有本次部署文件统一放在 `/opt/shsystem-tbase` 下，不放入其他项目目录：

```text
/opt/shsystem-tbase/compose.tbase-five-container.yml
/opt/shsystem-tbase/.env
/opt/shsystem-tbase/images/                 应用和 Python 镜像或离线镜像包
/opt/shsystem-tbase/vendor/tbase/           TBase 安装包、许可证和校验文件
/opt/shsystem-tbase/tbase/node1/            数据库节点一持久化数据
/opt/shsystem-tbase/tbase/node2/            数据库节点二持久化数据
/opt/shsystem-tbase/tbase/node3/            数据库节点三持久化数据
/opt/shsystem-tbase/shared/                 应用与 Python 共享文件
/opt/shsystem-tbase/app-data/               应用持久化数据
/opt/shsystem-tbase/logs/                   部署相关日志
/opt/shsystem-tbase/backup/                 备份文件
```

通过 Xftp、SCP 或批准的文件传输工具上传配置、镜像和厂商介质。数据库数据目录由宿主机创建并挂载，不要把运行数据放在项目源码目录或容器可写层中。

不要上传或在命令行明文记录生产密码；`.env`、许可证和 SSH 密钥应限制权限。

### 2.3 TBase 安装文件上传清单

先在服务器确认 CPU 架构：

```bash
uname -m
```

只有输出 `x86_64` 时，才按下面清单上传 x86_64 文件。当前本地交付目录为：

`E:\U盘内容\集团国能CEOS+CERDB\集团版数据库CEDB（基于TBase）`

通过 Xftp 连接服务器后，左侧打开上述本地目录，右侧进入 `/opt/shsystem-tbase/vendor/tbase/`，先上传下面列出的两个 x86_64 介质文件并保留原文件名。当前 `/opt/shsystem-tbase` 是指向 `/home/shsystem-tbase` 的符号链接，因此文件实际保存在 `/home` 分区。RAR 是 TBase OSS 主安装介质；GIS RPM 是配套组件：

| 本地文件 | 上传到服务器 | 用途 |
| --- | --- | --- |
| `tbase-xerdb_x86_2.15.21.1_5.21.3.4.rar` | `/opt/shsystem-tbase/vendor/tbase/tbase-xerdb_x86_2.15.21.1_5.21.3.4.rar` | x86 版 TBase OSS 安装介质 |
| `cerdb-gis-1.1.2.0-CEOS1.x86_64.rpm` | `/opt/shsystem-tbase/vendor/tbase/cerdb-gis-1.1.2.0-CEOS1.x86_64.rpm` | x86_64 GIS RPM |

不要上传 `cerdb-gis-1.1.2.0-CEOS1.aarch64.rpm`，它是 ARM 架构，不能用于 `x86_64` 服务器。不要把整个 ARM 文件夹上传到本次 x86_64 介质目录。若 `uname -m` 输出 `aarch64`，先停止本清单的上传步骤：当前顶层 OSS 压缩包是 x86 版，应改用对应 ARM 的整套 OSS 介质并向厂商确认 CEOS 版本兼容性。

当前交付目录顶层没有单独的许可证文件，因此不用从该目录寻找或上传许可证。若厂商另外提供许可证，再按前文要求单独传入受限目录。

在服务器上核对上传结果：

```bash
sudo install -d -m 0750 /opt/shsystem-tbase/vendor/tbase
cd /opt/shsystem-tbase/vendor/tbase
ls -lh
sha256sum ./*
file ./*
rpm -K ./cerdb-gis-1.1.2.0-CEOS1.x86_64.rpm
rpm -qip ./cerdb-gis-1.1.2.0-CEOS1.x86_64.rpm
```

上传校验通过后，检查解压空间和 RPM 依赖。当前 GIS RPM 已安装在宿主机，不要重复安装。RPM 的包元数据显示安装内容约 3.84 GB，安装脚本会创建 `/data/cerdb`、写入 systemd 服务并启动 `cerdb`。RAR 已经解压到 `/home/tbase-oss/12.tbase-xerdb_x86_2.15.21.1_5.21.3.4/`，后续不要重复解压或覆盖现有数据库目录。以下命令仅用于复核当前文件和空间：

```bash
df -h / /opt /data 2>/dev/null || true
df -i / /opt /data 2>/dev/null || true
rpm -q cerdb-gis
sudo systemctl is-active cerdb
sudo du -sh /data/cerdb /home/tbase-oss
```

此前 `bsdtar -xOf ... | wc -c` 曾返回 0，不能据此认定归档未压缩或内容为空；当前以已解压目录中的实际文件为准。不要把 GIS RPM 装进普通 Docker 容器，因为其脚本依赖宿主机的 systemd、`/data` 和服务管理。

### 2.4 使用独立数据分区

可以将本项目介质、容器数据和数据库数据放到独立数据分区；不应移动 `/usr`、`/etc`、`/var` 等整个系统目录。服务器当前 `/home` 是独立 ext4 逻辑卷，容量约 365G；`/opt/shsystem-tbase` 通过符号链接落在 `/home`，`/data` 通过 bind mount 落在 `/home/cerdb-data`。Docker 仍在根分区的 `/var/lib/docker`，LVM 卷组没有未分配空间。先确认目标路径现有内容：

```bash
lsblk -o NAME,TYPE,SIZE,FSTYPE,MOUNTPOINT,UUID
findmnt -T /home
findmnt -T /opt/shsystem-tbase
findmnt -T /data
ls -ld /home /opt/shsystem-tbase /data /data/cerdb 2>/dev/null
du -sh /opt/shsystem-tbase /data 2>/dev/null
df -hT / /home
```

可把安装介质和项目目录放在 `/home` 分区。当前 `/opt/shsystem-tbase` 已通过符号链接指向 `/home/shsystem-tbase`；`/data` 也已 bind mount 到 `/home/cerdb-data`。不要移动整个系统目录或删除 Docker 数据来腾空间。根卷所在卷组没有空闲 extent，不能直接扩展根逻辑卷；不要为了腾空间在线缩小 `/home` 的 ext4 文件系统。

迁移目录时保留回退副本；完成挂载配置、重启验证和数据核对后才考虑清理。CERDB GIS RPM 固定写入 `/data/cerdb`，并在宿主机安装脚本中操作 systemd；当前该路径已绑定到 `/home/cerdb-data`。当前 `/home` 可用约 338G，低于 TBase 手册给出的每台至少 500G 基础磁盘规模，只能用于受限的测试尝试，不能视为满足该基线。

RAR 解压、GIS 安装和数据库运行都需要额外空间。TBase 安装手册给出的基础磁盘规模为每台至少 500 GB；小容量数据分区只解决当前根分区不足问题，不能据此认为满足数据库部署要求。

### 2.4.1 将 TBase 容器迁移到项目专用 Docker 守护进程

当前 Docker Engine 18.09 的 `data-root` 属于整个守护进程，不能只对某个容器设置。由于同一守护进程还运行 RuoYi 等项目，禁止修改现有 `docker.service` 的 `data-root`、停止其服务、清空 `/var/lib/docker` 或执行全局 `docker system prune`。本方案新增独立的 `tbase-docker.service`，其数据、运行目录和 socket 单独放在 `/home`；现有 Docker 守护进程及非 TBase 容器保持原样。专用 daemon 与现有 daemon 仍共享宿主机内核、网络栈和 Docker 可执行文件，因此开始前须确认 CEOS 对运行第二个 dockerd 的支持、当前 `dockerd` 路径、存储驱动、cgroup 驱动、网络/IPTables 要求及 systemd unit 配置。未确认第二个 daemon 可以隔离运行时停止，不得直接套用其他发行版 unit。

迁移目标示例：

```text
/home/tbase-docker/                 专用 daemon 的 data-root
/home/tbase-docker-exec/            专用 daemon 的 exec-root
/run/tbase-docker/                  PID、containerd 和临时运行状态
/run/tbase-docker.sock              专用 Docker API socket
/home/tbase-oss/tbase-containers/   TBase 节点数据和导出备份
```

先在现有默认 Docker CLI 下只读盘点。此阶段不要改 daemon 配置或清理容器；确保记录镜像、启动参数、环境变量、网络、挂载、端口映射、特权/capabilities 和重启策略。检查是否有敏感环境变量，输出在受限文件中保存，不要贴到工单或聊天中：

```bash
set -eu
command -v dockerd
docker version
docker info --format 'root={{.DockerRootDir}} storage={{.Driver}} cgroup={{.CgroupDriver}}'
df -hT / /home
df -i / /home
docker ps -a --filter name='^/tbase-node[123]$'
for c in tbase-node1 tbase-node2 tbase-node3; do
  docker inspect -f 'name={{.Name}} image={{.Config.Image}} hostname={{.Config.Hostname}} user={{.Config.User}} network_mode={{.HostConfig.NetworkMode}} privileged={{.HostConfig.Privileged}} restart={{.HostConfig.RestartPolicy.Name}} entrypoint={{json .Config.Entrypoint}} cmd={{json .Config.Cmd}}' "$c"
  docker inspect -f 'mounts={{json .Mounts}} ports={{json .HostConfig.PortBindings}} networks={{json .NetworkSettings.Networks}} cap_add={{json .HostConfig.CapAdd}} devices={{json .HostConfig.Devices}}' "$c"
  docker diff "$c"
done
du -sh /home/tbase-oss/tbase-containers/node1 /home/tbase-oss/tbase-containers/node2 /home/tbase-oss/tbase-containers/node3
```

确认 `/home` 有足够空间容纳三份 rootfs 导出、镜像、运行数据和回退副本；当前约 331G 可用，但按 `du` 和 `df` 实测决定。若 `/home` 空间不够、节点数据目录位置与预期不符、容器使用未盘点的匿名卷，或三个节点中有非本项目数据，立即停止。不要在旧 daemon 上运行 `docker commit`：它会把新镜像写入当前根分区，根分区只有约 1.7G 可用空间。

先创建仅供 TBase 使用的目录，并保存受限的配置清单。不要把 `.inspect.json` 中可能包含的密码、令牌或私钥公开：

```bash
sudo install -d -m 0700 /home/tbase-docker /home/tbase-docker-exec \
  /home/tbase-docker-backup /home/tbase-docker-backup/rootfs \
  /home/tbase-docker-backup/inspect /run/tbase-docker
for c in tbase-node1 tbase-node2 tbase-node3; do
  docker inspect "$c" > "/home/tbase-docker-backup/inspect/$c.inspect.json"
  chmod 0600 "/home/tbase-docker-backup/inspect/$c.inspect.json"
done
```

安装并启动独立 daemon 前，必须从当前 `dockerd --help`、现有 systemd unit 和 CEOS 厂商说明确认 18.09 支持所需选项，并为新 daemon 使用独立的 `--data-root=/home/tbase-docker`、`--exec-root=/home/tbase-docker-exec`、`--pidfile=/run/tbase-docker/dockerd.pid`、Unix socket `/run/tbase-docker.sock`、独立 bridge 名称/IP 段。不要显式设置 `--containerd`，除非另行安装并启动一个专供该 daemon 使用的 containerd 实例；该选项指定外部 containerd socket，指向不存在的 socket 会导致 dockerd 启动失败。不得与默认 daemon 共用 socket、PID、exec-root、containerd socket、bridge 名称或地址池。若现有 CEOS unit 使用额外参数、配置文件或厂商补丁，制作新的 systemd unit 时只复制经核实且适用于第二实例的设置；不编辑 `/usr/lib/systemd/system/docker.service` 或 `/etc/docker/daemon.json`。启动后用专用 socket 检查 `docker info` 确认 `DockerRootDir=/home/tbase-docker`、存储驱动和网络无冲突。daemon 启动失败或改变了默认 daemon/其他项目网络时，立即停止新 daemon 并回滚新建 unit，不继续迁移。

确认专用 daemon 稳定运行后，再迁移 TBase 容器。下面导出的是容器根文件系统，不包含 bind mount/volume；`/data` 等持久数据仍在 `/home/tbase-oss/tbase-containers/`，必须独立备份。容器 rootfs 导出可能包含数据库软件、配置和凭据，目录权限保持 `0700`。为保证文件一致性，应安排停机窗口，仅停止三个 TBase 容器；不要停止或重启其他容器。先停止节点写入并按 Etcd/TBase 的维护要求停服务，再继续：

```bash
set -euo pipefail
for c in tbase-node1 tbase-node2 tbase-node3; do
  docker stop "$c"
done
for c in tbase-node1 tbase-node2 tbase-node3; do
  docker export "$c" | gzip -1 > "/home/tbase-docker-backup/rootfs/$c.rootfs.tar.gz"
  test -s "/home/tbase-docker-backup/rootfs/$c.rootfs.tar.gz"
  gzip -t "/home/tbase-docker-backup/rootfs/$c.rootfs.tar.gz"
done
tar -C /home/tbase-oss/tbase-containers -czf \
  /home/tbase-docker-backup/tbase-node-data.tar.gz node1 node2 node3 packages
gzip -t /home/tbase-docker-backup/tbase-node-data.tar.gz
df -hT /home
```

任何停止或导出失败时，不删除旧容器、旧镜像或备份；使用默认 daemon 启动已停止的 TBase 节点恢复原服务。导出成功后，使用专用 Docker socket 分别 `docker import` 三份 rootfs，并按 inspect 清单重建容器。重建时必须恢复原有 systemd 启动方式、环境、网络别名/IP（如安装配置依赖固定地址）、端口映射、权限、重启策略，以及每个节点独立的数据挂载和只读安装包挂载；不要把三个节点挂到同一个数据目录。rootfs 导入不会自动保留原镜像的 `ENTRYPOINT`、`CMD`、镜像标签和容器参数，不能仅靠 `docker import` 就视为完成。启动命令和 systemd/cgroup 挂载必须以保存的 inspect 和 CEOS 已验证配置为准，不要猜测或直接添加 `--privileged`。

重建后逐项验证节点只使用专用 daemon、数据仍落在 `/home`、Etcd 三成员健康、SSH 免密互通、TBase 已安装文件与配置存在、相关网络和端口正常，并检查应用连接。确认三节点、Etcd、TBase/OSS、数据读写和重启恢复全部验收后，旧 daemon 中只删除明确属于 TBase 的旧容器和不再使用的 TBase 镜像，以回收 `/` 空间。删除前再次以容器名和镜像 ID 检查对象归属；禁止 `docker system prune`、`docker volume prune` 或删除共享基础镜像。最后分别记录默认与专用 daemon 的 `docker info`、容器清单、挂载和磁盘用量。

失败回滚时，停止专用 daemon 中新建的 TBase 容器，并通过专用 socket 移除这些新对象；通过默认 Docker socket 启动旧的 `tbase-node1`、`tbase-node2`、`tbase-node3`。不要删除 `/home/tbase-docker-backup`、节点数据、旧容器或旧镜像，直到旧路径下的集群恢复且数据核对完成。两个 daemon 的命令必须始终显式区分 socket，例如默认 `docker ...` 与 `docker -H unix:///run/tbase-docker.sock ...`；不要修改 `DOCKER_HOST` 为全局 shell/profile 设置。

`sha256sum` 的结果应与厂商提供的校验值核对；如果没有厂商校验值，这一步只能记录文件摘要，不能证明文件来源或完整性。GIS RPM 已在当前 CEOS 环境直接尝试安装并启动。后续先检查 OSS 归档中的说明和脚本，再逐步尝试部署；该测试不能证明厂商认证或生产部署兼容性。若厂商另行提供许可证，将其通过受控方式单独存放在 `/opt/shsystem-tbase/vendor/tbase/license/`，并按厂商要求设置权限；不要把许可证放入镜像仓库或代码仓库。

### 2.5 当前服务器实际部署进度（2026-11-13）

以下为用户提供的服务器执行结果，不代表 TBase OSS 集群或五容器部署已完成：

- `/opt/shsystem-tbase` 已改为指向 `/home/shsystem-tbase` 的符号链接；旧副本已移至 `/home/shsystem-tbase-migration-backup`。保留该备份，待确认迁移和部署文件完整后再决定是否清理。
- `/home/cerdb-data` 已 bind mount 到 `/data`，并已写入 `/etc/fstab`。`findmnt -T /data` 显示来源为 `/dev/mapper/ceos-home[/cerdb-data]`。
- 已安装 `cerdb-gis-1.1.2.0-CEOS1.x86_64.rpm`。安装后实测 `/data/cerdb` 占用约 3.7G；其内容实际位于 `/home` 分区。
- `cerdb.service` 当前为 `active (running)`；安装脚本已启用并启动服务。安装后 `/` 约剩 6.9G，`/home` 约剩 338G。
- 服务当前监听 `0.0.0.0:5432` 和 `0.0.0.0:5433`，表示绑定了所有 IPv4 地址。应在防火墙中只允许应用容器、Python 容器和管理网段访问，不能直接暴露到公网。
- 服务日志出现 `cerdb.version` 缺失、`GAUSSLOG`/`GS_CLUSTER_NAME`/`GAUSS_WARNING_TYPE` 未设置、`AlarmItem` 配置异常、`gscgroup_cerdb.cfg` 不存在、`could not create any HA TCP/IP sockets` 及 memory protect 初始化告警。虽然服务已启动，这些告警仍需在继续部署前记录和检查；不要据此认定 OSS 节点集群已就绪。
- `/home` 可用空间仍低于手册给出的每台至少 500G 基础磁盘要求，本机安装仅作受限测试尝试。Docker 仍使用 `/var/lib/docker`，本次没有迁移 Docker。
- 用户随后确认只迁移 TBase 项目，不影响同一宿主机的 RuoYi 等容器；对应的独立 Docker 守护进程迁移步骤已补入本节。CEOS 服务器尚未执行该迁移，当前默认 Docker 的 `DockerRootDir` 仍是 `/var/lib/docker`；必须先完成只读盘点、空间核对和 CEOS 对双 dockerd 的兼容性检查。
- 迁移备份已创建：三个 TBase 节点宿主机数据目录各约 123M；三个容器均已停止，rootfs 导出通过 `gzip -t`，节点数据归档通过压缩完整性检查。`/home` 实测约 329G 可用。默认 Docker 为 `overlay2`/`cgroupfs`，dockerd 路径 `/usr/bin/dockerd`，现有启动参数只有 `--live-restore`；TBase 网络为 `172.19.0.0/24`，当前 `docker network inspect` 未列出活动端点。新 daemon 尚未启动，旧容器、旧网络和旧镜像必须保留。
- TBase OSS RAR 已成功解压到 `/home/tbase-oss/12.tbase-xerdb_x86_2.15.21.1_5.21.3.4/`。归档内已发现 `tbase_oss-2.15.21.1-i.x86_64.rpm`、`tbase_pgxz-5.21.3.4-i.x86_64.rpm`、`tbase_mgr.sh`、安装手册、校验文件和 `oss_password`。其中 `oss_password` 可能包含敏感凭据，不得打印、复制到工单或提交代码仓库。
- OSS RPM 核验失败：`rpm -K` 对两个 RPM 均返回 `DIGESTS NOT OK`；`rpm -qip` 报告 `tbase_oss` 的 Header SHA1 digest BAD，并称其不是 RPM 包，而 `tbase_pgxz` 可读出版本 `5.21.3.4` 元数据。当前校验文件 `md5.txt` 却列出 `tbase_pgxz-5.21.3.1-i.x86_64.rpm`，与实际文件版本不一致；`X86平台md5.txt` 的终端输出也不完整。因此介质完整性尚未验证，暂停安装。
- 后续完整输出确认：两个 RPM 文件本身均识别为 x86_64 RPM，但实际 MD5 与 `md5.txt` 中相应值不符；`tbase_oss` 的 SHA1 Header digest 检查失败，`tbase_pgxz` 的 RPM 内部 digest 检查失败。`X86平台md5.txt` 只有一个 32 位摘要，当前没有证据说明它对应哪个文件。可能是归档内容与校验文件版本不匹配，也可能是解压或传输损坏；目前不能判定具体原因。
- 管理器及辅助脚本目前都是 `0644`（无可执行位）。安装说明要求 `tbase_mgr.sh` 与配套文件位于同一目录并具有可执行权限；在介质完整性确认前不要 `chmod` 或执行脚本。脚本会读取相邻 `conf/`、`script/` 文件并修改系统服务/配置。
- 再次提取到 `/home/tbase-oss/rpm-compare.SsN9kP/` 后，顶层和 `tbase_mirror/pgxzm/` 的四个 RPM 文件均为预期大小，但 SHA256 分别为顶层 OSS `1a9b84ffb44857082a1045a9fee55b82e32f9a29d22c9c7ff643f48198d410f0`、顶层 PGXZ `97a1486ac27496477faba9caaf8759398b1076581dd52e3f6d95ea310ee192bf`、mirror OSS `ce6108765952683b2805646494bc6c6d9c1acc071bb257b7610f99408083cec5`、mirror PGXZ `70ed430ffd7be270d482e427226151a45e21e5786d5750fcf3e90a6fe682833e`。四份的 `rpm -K` 均为 `DIGESTS NOT OK`，而且摘要与此前顶层提取结果、原 OSS_DIR 文件及随包 MD5 不符；RAR 内存在同名但内容不同的 RPM 副本。RAR5 提取结果不稳定，不能据此选择或安装任何一份 RPM。

已核实 RPM 脚本会在宿主机创建 `/data/cerdb`、写入 CERDB 环境配置、启用 `cerdb.service` 并启动数据库。以下迁移和安装命令仅作历史记录，不要整段重复执行；当前仅需运行状态检查命令：

```bash
findmnt -T /opt/shsystem-tbase
findmnt -T /data

sudo systemctl status cerdb --no-pager -l
sudo journalctl -u cerdb -n 100 --no-pager
sudo du -sh /data/cerdb
df -hT / /data
```

TBase OSS 介质当前处于**核验失败、暂停安装**状态。实际从 RAR 分别提取顶层和 `tbase_mirror/pgxzm/` 两套同名 RPM 后，四个文件大小虽分别为 93M 和 493M，但 SHA256 两两不一致，四个文件的 `rpm -K` 全部返回 `DIGESTS NOT OK`。提取摘要还与此前提取结果及 `/home/tbase-oss/12.tbase-xerdb_x86_2.15.21.1_5.21.3.4/` 中已有文件摘要不一致。现有证据表明 `bsdtar` 提取过程或其读取的 RAR 内容不稳定；不能据此判断哪份 RPM 正确，也不能选择任何一份进行安装。

不要重复用 `bsdtar` 提取 RPM，也不要安装上述任何副本、修改管理脚本权限或执行管理脚本。不要删除核验目录、覆盖现有解压文件或触碰 `/data/cerdb`。服务器未检测到 `unrar`、`7zz` 或 `7z`。已确认系统为 CEOS 1.1、内核 `4.19.90-2305.1.0.0200.ce1.x86_64`、架构 `x86_64`；默认路由存在，DNS 配置为 `114.114.114.114` 和 `8.8.8.8`，但 `yum.ce.cloud`、`yum.ce.inc` 均无法解析，已配置的 `amd64` DNF 仓库不可用。按离线方式准备解压工具：

```bash
RAR=/home/shsystem-tbase/vendor/tbase/tbase-xerdb_x86_2.15.21.1_5.21.3.4.rar
```

1. 在 Windows PowerShell 中下载官方 Linux x86_64 独立版 `7zz` 压缩包。下载的是 Linux 程序，不是 Windows 版 7-Zip：

```powershell
$DownloadDir = Join-Path $env:USERPROFILE 'Downloads\ceos-tbase-tools'
New-Item -ItemType Directory -Force -Path $DownloadDir | Out-Null
$SevenZipVersion = '2501'
$SevenZipUrl = "https://www.7-zip.org/a/7z${SevenZipVersion}-linux-x64.tar.xz"
$SevenZipArchive = Join-Path $DownloadDir "7z${SevenZipVersion}-linux-x64.tar.xz"
Invoke-WebRequest -Uri $SevenZipUrl -OutFile $SevenZipArchive
Get-Item $SevenZipArchive | Select-Object FullName,Length
Get-FileHash -Algorithm SHA256 $SevenZipArchive
tar -tf $SevenZipArchive
```

如果官方地址返回 404，不要换成 Windows 安装包；打开 `https://www.7-zip.org/download.html`，确认最新的 **Linux x64** 压缩包文件名后，只修改 `$SevenZipVersion` 或 `$SevenZipUrl` 再执行。保存 `Get-FileHash` 输出，上传后用于服务器端比对。

2. 在服务器创建离线工具目录，并用 Xftp 将 `$SevenZipArchive` 上传到该目录：

```bash
sudo install -d -m 0750 /home/shsystem-tbase/vendor/tools/7zip
```

Xftp 目标目录：`/home/shsystem-tbase/vendor/tools/7zip/`。上传后在服务器确认文件名、大小和 SHA256：

```bash
cd /home/shsystem-tbase/vendor/tools/7zip
ls -lh
sha256sum ./7z*-linux-x64.tar.xz
file ./7z*-linux-x64.tar.xz
```

将服务器 SHA256 与 Windows 上传前保存的摘要比对。解压并确认独立程序，不需要 DNF 安装：

```bash
cd /home/shsystem-tbase/vendor/tools/7zip
tar -xJf ./7z*-linux-x64.tar.xz
SEVENZIP=$(find "$PWD" -type f -name 7zz -print -quit)
test -n "$SEVENZIP" || { echo '未找到 7zz'; exit 1; }
chmod 0755 "$SEVENZIP"
"$SEVENZIP" i
```

确认 7zz 可以读取 RAR5 后，使用它将 RPM 提取到全新的临时目录，对提取文件重新计算 SHA256 并运行 `rpm -K`。提取结果仍不稳定或 `rpm -K` 仍失败时继续暂停，不得安装 TBase RPM。不要使用未经确认来源的 Windows 解压软件生成 RPM 文件，也不要用 7zz 绕过 RPM 摘要校验。

上传 7zz 压缩包后的实际服务器操作顺序如下。`WINDOWS_SHA256` 必须替换为 Windows `Get-FileHash` 保存的真实值；如果不一致，停止操作：

```bash
set -e
TOOL_DIR=/home/shsystem-tbase/vendor/tools/7zip
ARCHIVE=$(find "$TOOL_DIR" -maxdepth 1 -type f -name '7z*-linux-x64.tar.xz' -print -quit)
test -n "$ARCHIVE" || { echo '未找到已上传的 Linux x64 7zz 压缩包'; exit 1; }
ls -lh "$ARCHIVE"
file "$ARCHIVE"
sha256sum "$ARCHIVE"
WINDOWS_SHA256='请替换为Windows_Get-FileHash输出的SHA256'
test "$WINDOWS_SHA256" = '请替换为Windows_Get-FileHash输出的SHA256' && { echo '请先填写 WINDOWS_SHA256'; exit 1; }
test "$(sha256sum "$ARCHIVE" | awk '{print tolower($1)}')" = "$(printf '%s' "$WINDOWS_SHA256" | tr '[:upper:]' '[:lower:]')" || { echo '7zz压缩包SHA256不一致'; exit 1; }

EXTRACT_DIR="$TOOL_DIR/7zz-bin"
rm -rf "$EXTRACT_DIR"
install -d -m 0750 "$EXTRACT_DIR"
tar -xJf "$ARCHIVE" -C "$EXTRACT_DIR"
SEVENZIP=$(find "$EXTRACT_DIR" -type f -name 7zz -print -quit)
test -n "$SEVENZIP" || { echo '解压后未找到7zz'; exit 1; }
chmod 0755 "$SEVENZIP"
"$SEVENZIP" i

RAR=/home/shsystem-tbase/vendor/tbase/tbase-xerdb_x86_2.15.21.1_5.21.3.4.rar
test -f "$RAR" || { echo '未找到TBase RAR'; exit 1; }
sha256sum "$RAR"
"$SEVENZIP" t "$RAR"
"$SEVENZIP" l "$RAR" | grep -E 'tbase_(oss-2\.15\.21\.1|pgxz-5\.21\.3\.4)-i\.x86_64\.rpm$'
```

如果 `7zz t` 失败，或列出的 RPM 路径与后续命令不一致，保留现状并停止，不要继续提取。确认测试通过后，再提取到新的核验目录：

```bash
TMP_DIR=$(mktemp -d /home/tbase-oss/7zz-rpm-check.XXXXXX)
echo "核验目录: $TMP_DIR"
"$SEVENZIP" x "$RAR" -y -o"$TMP_DIR" \
  '12.tbase-xerdb_x86_2.15.21.1_5.21.3.4/tbase_oss-2.15.21.1-i.x86_64.rpm' \
  '12.tbase-xerdb_x86_2.15.21.1_5.21.3.4/tbase_pgxz-5.21.3.4-i.x86_64.rpm'
find "$TMP_DIR" -type f -name '*.rpm' -exec ls -lh {} \;
find "$TMP_DIR" -type f -name '*.rpm' -exec sha256sum {} \;
find "$TMP_DIR" -type f -name '*.rpm' -exec file {} \;
find "$TMP_DIR" -type f -name '*.rpm' -exec rpm -K {} \;
```

本次使用 7zz 重新读取 RAR5 后，两个 RPM 均通过 `rpm -K`，结果为 `digests OK`；此前用 `bsdtar` 得到的 `DIGESTS NOT OK` 是其读取/提取结果异常，不能作为当前 7zz 提取结果的结论。两个 RPM 随后已安装。服务器输出显示 `tbase_oss-2.15.21.1-i.x86_64`、`tbase_pgxz-5.21.3.4-i.x86_64` 和既有 `cerdb-gis-1.1.2.0-CEOS1.x86_64` 均已安装。`cerdb.service` 为 `active (running)`，当前监听 `0.0.0.0`、`[::]` 上的 5432 和 5433。日志仍有 `GAUSSLOG`、`GS_CLUSTER_NAME`、`GAUSS_WARNING_TYPE`、`cerdb.version`、AlarmItem、gscgroup 和 HA socket 等告警；服务启动不表示这些配置问题已经解决，也不表示 TBase OSS 节点或 CN/DN/GTM 已初始化。数据库端口绑定所有网卡，部署期间应通过防火墙限制来源，不要直接暴露公网。

当前先只读确认 OSS RPM 安装了哪些文件、脚本和文档。截图中的提示符显示当前目录为 `tbase`，但 `TMP_DIR` 变量可能已在新 shell 中丢失，因此下面通过 RPM 数据库和已解压介质定位，不依赖该变量：

```bash
set -e
rpm -ql tbase_oss-2.15.21.1-i.x86_64
rpm -ql tbase_pgxz-5.21.3.4-i.x86_64
rpm -q --scripts tbase_oss-2.15.21.1-i.x86_64
find /home/tbase-oss -type f \
  \( -iname '*install*.pdf' -o -iname '*install*.doc*' -o -iname '*readme*' \
     -o -name 'tbase_mgr.sh' -o -name 'role.info' \) -print
find /home/tbase-oss -type f -name 'tbase_mgr.sh' -exec ls -l {} \;
sudo systemctl status cerdb --no-pager -l
sudo ss -lntp | grep -E ':(5432|5433)\\b' || true
```

不要运行找到的管理脚本或初始化脚本。先把 `rpm -ql`、`rpm -q --scripts` 和 `find` 输出发回，以便根据实际安装文件确认 OSS 安装流程、角色配置和对当前 GIS CERDB 数据目录的影响。不要读取 `oss_password`，不要停止/重启 `cerdb.service`，不要覆盖 `/data/cerdb`。
```

用户提供的原始 RAR SHA256 为 `5ee4ba73633fca1c72860c532a335897a5fcb04bb6c46d6f0b8cd1173d8a7793`；该值只能用于确认本地归档是否变化，不能单独证明介质来源可信。不要执行 `cat .../oss_password`、`bash .../tbase_mgr.sh` 或 `rpm -Uvh tbase_oss...`。RPM 服务启动不等于 TBase OSS 的 OSS 管理组件、CN/DN/GTM 已安装或初始化；也不等于已确认 CEOS 容器化方案受支持。不要把 OSS 包装入现有容器或覆盖当前数据库目录。

## 3. TBase OSS 介质检查与部署前置条件

以下事项目前尚未从已解压安装介质和现有执行结果中确认。按本次要求先检查归档内的手册、脚本和配置，再以实际执行反馈逐步验证；本说明不要求先联系厂商。对容器运行方式、节点角色和安装命令没有证据支持的内容仍标记为待确认，不直接猜测执行。

1. TBase 2.15.21.1 OSS 的节点安装和 OSS 管理组件要求；容器化支持情况尚未验证。
2. 每个容器是否必须运行 systemd、SSH 服务或特权模式；需要哪些 Linux capabilities、内核参数、ulimit 和宿主机设置。
3. 三个逻辑节点的静态地址、主机名解析、SSH 免密用户、端口清单和防火墙规则。
4. `role.info` 的准确格式，以及 CenterMaster/Slave、ConfdbMaster/Slave、Agent、Alarm、CGI、TStudio 在三个逻辑节点上的受支持分配方式。
5. CN、DN、GTM 的节点规划、初始化顺序、数据目录属主/权限、许可证安装步骤。
6. 支持的 JDBC 驱动坐标/版本、Python 驱动/连接方式、连接串、备份恢复方式和健康检查命令。

7. openEuler 版本、内核、glibc、systemd/SSH 运行方式是否受支持；如果不支持，是否提供可在 openEuler Docker 宿主机上运行的官方 TBase 基础镜像。
8. TBase RPM 是否只能安装在受支持的主机系统，还是允许在厂商提供的容器基础镜像中安装；是否需要 `--privileged`、host network 或宿主机内核模块。

现有手册确认至少两台物理主机和必选角色，但没有给出本项目容器化所需的镜像、容器启动参数及完整节点角色映射。本次已允许在一台服务器上使用三个 TBase 容器模拟三个逻辑节点；这只用于测试，不能替代两台物理主机的故障隔离和生产高可用。在实际检查归档前，不要猜测 `role.info`、端口、镜像 entrypoint 或初始化命令；应先以包内文件为依据逐项确认。

### 3.1 两种兼容性结果

- **包内资料支持容器化：** 使用包内规定的节点镜像或制作规范，在本说明的 `tbase-node1`、`tbase-node2`、`tbase-node3` 容器中执行安装和初始化流程。
- **包内资料未支持容器化：** 不在 openEuler 容器中猜测安装参数。保留 `sh-app` 和 `sh-python` 容器，将 TBase OSS 按其支持的主机方式部署；应用和 Python 使用固定内网地址连接数据库。单机测试仍需记录为兼容性尝试。

## 4. 创建持久化目录和网络

厂商确认容器方案及数据路径后，在宿主机创建独立持久化目录。示例路径须按厂商指定的 UID/GID 和 DataDir 调整：

```bash
sudo install -d -m 0750 /opt/shsystem-tbase/tbase/node1
sudo install -d -m 0750 /opt/shsystem-tbase/tbase/node2
sudo install -d -m 0750 /opt/shsystem-tbase/tbase/node3
sudo install -d -m 0750 /opt/shsystem-tbase/shared
sudo install -d -m 0750 /opt/shsystem-tbase/app-data
sudo install -d -m 0750 /opt/shsystem-tbase/logs
sudo install -d -m 0750 /opt/shsystem-tbase/backup
```

设置目录属主前，先从厂商文档确认容器内运行用户；不要默认使用固定 UID。三个 TBase 节点必须有各自独立的数据目录，不能把同一数据目录同时挂载给多个节点。应用和 Python 共享报告/上传文件的目录按当前项目要求挂载到两容器相同路径。

`.env` 中的宿主机路径统一填写为以下目录；容器内目标路径仍按应用和厂商要求配置：

```dotenv
SHARED_DATA_HOST_PATH=/opt/shsystem-tbase/shared
TBASE_NODE1_DATA=/opt/shsystem-tbase/tbase/node1
TBASE_NODE2_DATA=/opt/shsystem-tbase/tbase/node2
TBASE_NODE3_DATA=/opt/shsystem-tbase/tbase/node3
TBASE_PACKAGE_HOST_PATH=/opt/shsystem-tbase/vendor/tbase
```

先使用厂商规定的容器网络和节点地址方案。若厂商确认可使用 Docker bridge 静态地址，再在 Compose 中配置专用网络、固定地址及容器 hostname；若安装器要求宿主机网络或特定 DNS/SSH 行为，则按厂商规范实现。不要直接暴露 TBase 管理端口到公网。

参考项目的容器互通检查可以改为：

```bash
docker exec tbase-node1 getent hosts tbase-node2
docker exec tbase-node2 getent hosts tbase-node1
docker exec tbase-node3 getent hosts tbase-node1
docker exec tbase-node3 getent hosts tbase-node2
docker exec sh-app getent hosts tbase-node1
docker exec sh-python getent hosts tbase-node1
```

`ping` 不一定安装在精简镜像中，不能以缺少 `ping` 作为数据库故障结论；优先使用 `getent hosts`、厂商客户端和 TCP 检查命令。

## 5. 准备五容器 Compose 配置

仓库中的 `compose.tbase-five-container.yml` 是待适配草案，不是可直接部署的 TBase 配置。只有厂商提供或书面确认了容器镜像、启动命令、用户、挂载点、网络及健康检查后，才补齐并使用五容器 Compose 文件。配置结构包含两个应用服务和三个数据库节点服务：

```yaml
services:
  sh-app:
    image: ${APP_IMAGE:?set APP_IMAGE}
    restart: unless-stopped
    environment:
      CERDB_JDBC_URL: ${CERDB_JDBC_URL:?set vendor-confirmed JDBC URL}
      CERDB_JDBC_DRIVER: ${CERDB_JDBC_DRIVER:?set vendor-confirmed JDBC driver}
      CERDB_APP_USER: ${CERDB_APP_USER:?set application user}
      CERDB_APP_PASSWORD: ${CERDB_APP_PASSWORD:?set application password}
      PYTHON_SERVICE_URL: http://sh-python:8091
      PREDICTION_BASE_URL: http://sh-python:8090
    ports:
      - "${WEB_PORT:-80}:80"
    volumes:
      - ${SHARED_DATA_HOST_PATH:?set shared path}:/srv/shared

  sh-python:
    image: ${PYTHON_IMAGE:?set PYTHON_IMAGE}
    restart: unless-stopped
    environment:
      CERDB_DSN: ${CERDB_DSN:?set vendor-supported Python connection}
      PYTHON_INTERNAL_TOKEN: ${PYTHON_INTERNAL_TOKEN:?set token}
    expose:
      - "8090"
      - "8091"
    volumes:
      - ${SHARED_DATA_HOST_PATH:?set shared path}:/srv/shared

  tbase-node1:
    image: ${TBASE_NODE_IMAGE:?set vendor-confirmed node image}
    hostname: tbase-node1
    restart: unless-stopped
    # Add vendor-confirmed command, roles, network, privileges, and mounts here.
    volumes:
      - ${TBASE_NODE1_DATA:?set node1 data path}:/vendor-confirmed/data/path

  tbase-node2:
    image: ${TBASE_NODE_IMAGE:?set vendor-confirmed node image}
    hostname: tbase-node2
    restart: unless-stopped
    # Add vendor-confirmed command, roles, network, privileges, and mounts here.
    volumes:
      - ${TBASE_NODE2_DATA:?set node2 data path}:/vendor-confirmed/data/path

  tbase-node3:
    image: ${TBASE_NODE_IMAGE:?set vendor-confirmed node image}
    hostname: tbase-node3
    restart: unless-stopped
    # Add vendor-confirmed command, roles, network, privileges, and mounts here.
    volumes:
      - ${TBASE_NODE3_DATA:?set node3 data path}:/vendor-confirmed/data/path

networks:
  shsystem:
    internal: true
```

### 5.1 现有两个节点与第三节点检查

服务器上已有的 `tbase-node1` 和 `tbase-node2` 不要用 `docker commit` 复制，也不要用 Compose 强制重建。先记录它们的镜像、启动参数、挂载和网络：

```bash
for c in tbase-node1 tbase-node2; do
  echo "=== $c ==="
  docker inspect -f 'image={{.Config.Image}} hostname={{.Config.Hostname}}' "$c"
  docker inspect -f '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}' "$c"
  docker inspect -f 'entrypoint={{json .Config.Entrypoint}} cmd={{json .Config.Cmd}}' "$c"
  docker inspect -f '{{range .NetworkSettings.Networks}}{{println .IPAddress}}{{end}}' "$c"
done
```

如果检查结果显示 `tbase-node1` 和 `tbase-node2` 已经加入同一个现有网络（本次服务器为 `tbase-net`），第三节点必须加入这个网络。此时不要直接执行本节后面的 `docker-compose up`，因为 Compose 文件默认使用独立的 `shsystem` 网络，并且会尝试接管同名容器。先确认第三节点名称未被占用，并记录现有节点的实际镜像、入口、命令和挂载：

```bash
docker network inspect tbase-net >/dev/null
docker ps -a --filter name='^/tbase-node3$'
for c in tbase-node1 tbase-node2; do
  echo "=== $c ==="
  docker inspect -f 'image={{.Config.Image}} hostname={{.Config.Hostname}}' "$c"
  docker inspect -f 'entrypoint={{json .Config.Entrypoint}} cmd={{json .Config.Cmd}}' "$c"
  docker inspect -f '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}' "$c"
done
```

只有在确认 `tbase-node1` 的镜像、启动命令、容器内数据目录和 TBase 角色可以复用时，才按下面模板创建第三节点。模板中的镜像、入口、命令、权限、环境变量和容器内挂载点必须替换为检查结果及厂商安装要求；不能把 node1 的数据目录挂到 node3：

```bash
sudo install -d -m 0750 /opt/shsystem-tbase/tbase/node3
docker run -dit \
  --name tbase-node3 \
  --hostname tbase-node3 \
  --network tbase-net \
  -v /opt/shsystem-tbase/tbase/node3:/vendor-confirmed/tbase-data \
  -v /opt/shsystem-tbase/vendor/tbase:/vendor-confirmed/packages:ro \
  <与现有节点一致且已确认的 TBase 镜像> \
  <厂商确认的启动命令>
```

创建后先只做网络和挂载检查，不执行 OSS 初始化：

```bash
docker ps -a --filter name='tbase-node'
for c in tbase-node1 tbase-node2 tbase-node3; do
  echo "=== $c ==="
  docker inspect -f '{{range .NetworkSettings.Networks}}{{println .NetworkID .IPAddress}}{{end}}' "$c"
  docker exec "$c" getent hosts tbase-node1 tbase-node2 tbase-node3
  docker exec "$c" sh -c 'test -d /vendor-confirmed/tbase-data && df -h /vendor-confirmed/tbase-data'
done
```

若采用这条“保留现有节点并追加 node3”的路径，应用和 Python 容器也必须加入 `tbase-net`，或通过厂商确认的可达网络访问 TBase；不能让它们只加入 Compose 自动创建的 `shsystem`。只有在三节点已经完成厂商规定的 OSS 安装、角色配置和集群初始化后，才填写应用的 CERDB 连接参数并启动 `sh-app`、`sh-python`。

三个容器均在同一台 CEOS 主机时，只能验证节点发现、SSH、端口、角色和初始化流程；它们不构成三台物理主机，也不提供故障隔离。

### 5.2 保留现有数据库节点时启动应用和 Python

服务器当前的 `tbase-node1`、`tbase-node2` 已加入 `tbase-net`。在第三个节点创建并加入同一网络后，不要用五容器 Compose 接管同名数据库容器；该文件会尝试创建同名服务并使用另一张网络。使用仓库中的 `compose.app-python-tbase-net.yml`，它只创建 `sh-app` 和 `sh-python`，并把两个服务加入现有外部网络：

```bash
cd /opt/shsystem-tbase
docker network inspect tbase-net >/dev/null
docker-compose --env-file .env -f compose.app-python-tbase-net.yml config
docker-compose --env-file .env -f compose.app-python-tbase-net.yml up -d
docker-compose --env-file .env -f compose.app-python-tbase-net.yml ps
```

启动前必须确认三个数据库节点已经完成厂商规定的 OSS 安装、角色配置、CN/DN/GTM 初始化和就绪检查。`compose.app-python-tbase-net.yml` 不会安装或初始化 TBase，也不会停止、重建或删除 `tbase-node1`、`tbase-node2`、`tbase-node3`。

上面是结构示意，不是可直接启动的数据库 Compose 文件。仓库中的草案目前包含待厂商确认的镜像、变量、容器内路径、command、角色、network、权限和健康检查占位内容，需先依据厂商答复校订。Compose 的 `depends_on` 只能控制启动顺序，不能替代 TBase 集群初始化和数据库就绪检查。

## 6. 部署顺序

在获得厂商支持方案后，按以下顺序操作：

1. 根据厂商指南制作或导入与 CEOS/x86_64 兼容的 TBase 节点镜像，并用该镜像启动三个具有不同角色和独立数据目录的节点容器；不得将不匹配的 RPM 或未授权许可证放入镜像。
2. 按厂商确认的主机名、地址和 SSH 方式启动三个节点容器。检查节点互通、时间同步、独立磁盘挂载、系统参数和安装用户。
3. 按厂商给出的角色映射填写 `role.info`，核对 OSS 必选角色与 CN/DN Agent 分配。
4. 在厂商指定的节点上执行官方 OSS 安装命令。此前手册中的 `bash ./tbase_mgr/tbase_mgr.sh install` 只能在其规定环境中使用；容器内能否运行必须由厂商确认。
5. 登录 TBase OSS，上传许可证，按厂商说明创建协调节点（CN）、数据节点（DN）和 GTM 并初始化集群。
6. 按厂商命令检查 OSS 组件和 CN/DN/GTM 状态；用官方客户端执行连接、建表、事务、中文、时间、JSON、并发读写和备份恢复 POC。
7. 使用已验证的 JDBC/Python 驱动和 CERDB/TBase 连接配置构建应用及 Python 镜像。先迁移测试数据并验收，再导入业务数据。
8. 启动 `sh-python` 和 `sh-app`，验证内部 Python API、趋势预测 API、应用数据库连接和文件共享。

### 6.1 openEuler 服务器上的实际执行顺序

在服务器上执行。Compose 文件和 `.env` 固定放在部署根目录，镜像与介质分别放入其子目录：

```bash
cd /opt/shsystem-tbase
chmod 600 .env
docker load -i images/shsystem-images.tar  # 如果使用离线镜像包
docker-compose --env-file .env -f compose.tbase-five-container.yml config
```

若镜像包文件名不同，请替换为 `images/` 下的实际文件名。在 CEOS 1.1 当前环境中，将上面的 `docker compose` 改为 `docker-compose`。

先检查并启动三个数据库节点容器。若节点是手工创建的，先使用上一节的检查命令，不要直接执行此命令：

```bash
docker-compose --env-file .env -f compose.tbase-five-container.yml up -d tbase-node1 tbase-node2 tbase-node3
docker-compose --env-file .env -f compose.tbase-five-container.yml ps
docker-compose --env-file .env -f compose.tbase-five-container.yml logs --tail=200 tbase-node1 tbase-node2 tbase-node3
```

然后执行厂商要求的 OSS 安装、许可证上传和 CN/DN/GTM 初始化。只有数据库官方检查命令返回就绪，才启动应用容器：

```bash
docker-compose --env-file .env -f compose.tbase-five-container.yml up -d sh-python sh-app
docker-compose --env-file .env -f compose.tbase-five-container.yml ps
```

不要使用参考项目中的 `docker start ruoyi-db`、`mysqld`、`mysqladmin`、`MYSQL_PWD` 或 `jdbc:mysql://...` 命令；本方案中数据库服务名是三个 TBase 节点，连接方式由厂商 JDBC/客户端决定。

示例检查 Compose 语法及服务状态（文件名以实际创建的配置为准）：

```bash
docker-compose --env-file .env -f compose.tbase-five-container.yml config
docker-compose --env-file .env -f compose.tbase-five-container.yml up -d tbase-node1 tbase-node2 tbase-node3
docker-compose --env-file .env -f compose.tbase-five-container.yml ps
docker-compose --env-file .env -f compose.tbase-five-container.yml logs --tail=200 tbase-node1 tbase-node2 tbase-node3
```

数据库集群完成官方初始化并确认就绪后再启动应用服务：

```bash
docker-compose --env-file .env -f compose.tbase-five-container.yml up -d sh-python sh-app
docker-compose --env-file .env -f compose.tbase-five-container.yml ps
docker-compose --env-file .env -f compose.tbase-five-container.yml logs --tail=200 sh-python sh-app
curl --fail http://127.0.0.1/actuator/health
curl --fail http://127.0.0.1:8091/health
```

## 7. TBase 连接及 MySQL 迁移

应用 JDBC URL、驱动类、端口和 Python DSN 必须使用厂商确认且通过 POC 的值。不要因 TBase 基于 PostgreSQL 生态就默认 JDBC 或 `psycopg` 一定兼容。若 Python 驱动不受支持，应改由 Python 服务调用应用 API 读取/提交必要数据。

迁移前停止旧系统写入并备份 MySQL、GoView SQLite、上传文件及报告文件。逐项转换 MySQL 的 `AUTO_INCREMENT`、反引号、`ON UPDATE`、JSON、分页、函数、upsert、锁语义及时间类型；在 TBase 隔离库导入并核对表结构、索引、序列、记录数、中文、汇总结果和关键业务报表。不要将 MySQL dump 直接导入 TBase。数据库备份与恢复仅使用厂商命令，并先做恢复演练。

GoView 当前使用 SQLite，仍是 TBase 之外的独立持久化文件，必须备份。应用镜像应不含 Python；TBase 节点和 Python API 不暴露公网。当前 Python 任务状态保存在进程内存，容器重启可能丢失进行中任务。

## 8. 验收和限制

验收登录权限、碳排放核算、报告 DOCX/PDF 中文输出、趋势预测、重空协同、能量回收、GoView 读写、文件持久化、数据库节点状态、备份恢复和容器重启后的行为。记录所有厂商版本、镜像摘要、角色映射、端口和数据路径。

三个 TBase 节点容器即使启动成功，也仍共享单机故障域，不能提供多台物理机之间的故障隔离；容器内存、磁盘和网络竞争可能影响数据库。正式环境应按厂商支持的多主机拓扑部署，不能将本手册中的单机模拟当作生产或高可用方案。

## 9. 参考项目命令的适配关系

| 参考项目操作 | TBase 五容器适配 |
| --- | --- |
| openEuler 服务器 SSH 登录 | 保留，替换为现场服务器地址、端口和账号 |
| `docker pull` openEuler 基础镜像 | 仅用于 Docker/网络验证；TBase 节点必须使用厂商确认镜像 |
| 创建 Docker 网络 | 保留思路，本文示例使用 `shsystem`，具体网络模式听从厂商要求 |
| `ruoyi-db` MySQL 容器 | 业务部署改为 `tbase-node1`、`tbase-node2`、`tbase-node3`；现有 ruoyi-db 不要在测试时停止或删除 |
| `mysqladmin ping`、`mysql` 查询 | 删除，改用 TBase 厂商客户端和数据库健康检查命令 |
| Web/大屏 `curl` 检查 | 保留，改为检查 `sh-app` 的 `/actuator/health` 和业务入口 |
| `docker ps`、`docker exec`、日志检查 | 保留，并增加三个 TBase 节点、CN/DN/GTM 状态检查 |
| 固定密码、固定公网 IP 和旧端口 | 删除，改用 `.env` 中的现场值和最小防火墙开放规则 |
