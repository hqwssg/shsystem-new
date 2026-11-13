# openEuler 24.03 LTS-SP4 + MySQL 容器部署手册

本文覆盖 Windows 本地下载、创建 openEuler 虚拟机、Xftp 上传、Docker 初始化、MySQL 启动、验收、备份和故障排查。

## 1. 先确认仓库现状

参考附件《服务器操作步骤.docx》只作为 SSH、Xftp、`docker load`、`docker exec`、`docker ps` 和 `curl` 的操作参考。附件中的真实 IP、用户名、密码、端口和令牌不写入本文，现场使用 `<SERVER_IP>`、`<SSH_USER>`、`<SSH_PORT>`、`<MYSQL_ROOT_PASSWORD>` 等占位符替换。

当前 MySQL 方案在 `docker/docker-compose.yml`：`ruoyi-db` 为 MySQL 5.7，`ruoyi-web` 内含 Java、Python 预测、Redis 和 Nginx，`ruoyi-screen` 为 GoView + SQLite。根目录 `compose.three-container.yml` 是 CERDB 方案，使用 `cerdb`、`psycopg`、`CERDB_*`，不能直接用于 MySQL。

因此当前项目可以使用 MySQL 完成整体功能，但现状的三个容器是 `ruoyi-db`、`ruoyi-web`、`ruoyi-screen`，Python 暂时随 `ruoyi-web` 运行。若要求严格的“应用 + Python + MySQL”三个容器，必须先完成第 8 节的 MySQL 镜像和 Compose 适配。

## 2. 架构和资源

```text
浏览器 --80--> ruoyi-web (RuoYi + Python + Redis + Nginx)
浏览器 --3000--> ruoyi-screen (GoView + SQLite)
ruoyi-web -- ruoyi-db:3306 --> MySQL 5.7
```

建议虚拟机至少 4 vCPU、8 GB RAM、100 GB 系统盘和 100 GB 以上数据盘，架构为 `x86_64`。单台虚拟机不等于三台物理服务器，不提供数据库高可用。

## 3. Windows 下载和打包

以下在 PowerShell 执行。`$work`、`<...>` 按现场修改。

### 3.1 openEuler ISO

```powershell
$work = 'C:\deploy\shsystem-openEuler'
New-Item -ItemType Directory -Force "$work\iso", "$work\images", "$work\package" | Out-Null
$iso = 'https://repo.openeuler.org/openEuler-24.03-LTS-SP4/ISO/x86_64/openEuler-24.03-LTS-SP4-x86_64-dvd.iso'
$sum = 'https://repo.openeuler.org/openEuler-24.03-LTS-SP4/ISO/x86_64/openEuler-24.03-LTS-SP4-x86_64-dvd.iso.sha256sum'
curl.exe -L --fail --retry 3 -o "$work\iso\openEuler-24.03-LTS-SP4-x86_64-dvd.iso" $iso
curl.exe -L --fail --retry 3 -o "$work\iso\openEuler-24.03-LTS-SP4-x86_64-dvd.iso.sha256sum" $sum
Get-FileHash "$work\iso\openEuler-24.03-LTS-SP4-x86_64-dvd.iso" -Algorithm SHA256
Get-Content "$work\iso\openEuler-24.03-LTS-SP4-x86_64-dvd.iso.sha256sum"
```

以校验文件中的 SHA256 为准；校验失败时不要挂载 ISO。现场若使用内网镜像仓库，替换 URL。

### 3.2 Docker 镜像

ISO 是虚拟机介质，Docker 镜像是容器介质。当前 MySQL 方案在构建机执行：

先按项目构建流程生成 `ruoyi-admin.jar`、GoView WAR、预测平台 JAR、前端 `dist` 和其他依赖文件，并确认它们已复制到 `docker/web-main`、`docker/web-screen` 对应目录；仓库中的 `readme.txt` 不能替代这些构建产物。然后执行：

```powershell
Set-Location 'D:\idea库\RuoYi-new\shsystem-new'
docker pull mysql:5.7
docker compose -f docker/docker-compose.yml build ruoyi-db ruoyi-web ruoyi-screen
docker image ls
docker save -o "$work\images\mysql-5.7.tar" mysql:5.7
docker save -o "$work\images\ruoyi-web-1.0.0.tar" <WEB_IMAGE_FROM_docker_image_ls>
docker save -o "$work\images\ruoyi-screen-1.0.0.tar" <SCREEN_IMAGE_FROM_docker_image_ls>
Get-FileHash "$work\images\*.tar" -Algorithm SHA256
```

严格三容器镜像只能在 MySQL 适配完成后导出：

```powershell
docker save -o "$work\images\sh-app-mysql-1.0.0.tar" <MYSQL_APP_IMAGE>:1.0.0
docker save -o "$work\images\sh-python-mysql-1.0.0.tar" <MYSQL_PYTHON_IMAGE>:1.0.0
```

### 3.3 部署文件

```powershell
$repo = 'D:\idea库\RuoYi-new\shsystem-new'
New-Item -ItemType Directory -Force "$work\package\docker" | Out-Null
Copy-Item "$repo\docker\docker-compose.yml" "$work\package\docker\"
Copy-Item "$repo\docker\mysql" "$work\package\docker\" -Recurse
Copy-Item "$repo\docker\web-main" "$work\package\docker\" -Recurse
Copy-Item "$repo\docker\web-screen" "$work\package\docker\" -Recurse
```

## 4. 创建虚拟机

在 VMware、ESXi、Proxmox 或 KVM 中创建 Linux `x86_64` 虚拟机，将 ISO 挂载为光驱，分配至少 4 vCPU、8 GB 内存、100 GB 系统盘和数据盘，配置业务网卡、静态 IP、主机名、SSH 和 `Asia/Shanghai` 时区。KVM 宿主机模板如下；不要在待安装的虚拟机内运行：

### 4.1 虚拟机文件单独存放

Windows 文件 `E:\Downloading\openEuler-24.03-LTS-SP4-everything-x86_64-dvd.iso` 应上传到**虚拟化宿主机**的独立存储目录。建议为本项目单独建立目录，例如：

```text
/data/vm-images/shsystem-openeuler2403sp4/
├── iso/
│   └── openEuler-24.03-LTS-SP4-everything-x86_64-dvd.iso
├── disks/
│   ├── system.qcow2
│   └── data.qcow2
└── backup/
```

`/data` 应是宿主机单独挂载的数据盘；如果现场没有 `/data`，可将同样的目录建在已确认容量充足的 `/home/vm-images/` 或虚拟化平台指定的数据存储中。不要把虚拟机磁盘长期放在宿主机根分区，也不要把 ISO 上传到新建虚拟机内部。

使用 KVM/libvirt 时，在宿主机上创建并授权目录：

```bash
sudo mkdir -p /data/vm-images/shsystem-openeuler2403sp4/{iso,disks,backup}
sudo chown -R <LIBVIRT_USER>:<LIBVIRT_GROUP> /data/vm-images/shsystem-openeuler2403sp4
```

其中 `<LIBVIRT_USER>:<LIBVIRT_GROUP>` 以宿主机实际运行 QEMU 的账号为准，可先检查：

```bash
ps -eo user,group,comm | grep -E 'qemu|libvirtd' | head
```

Xftp 连接的是宿主机的 SSH 地址，将 ISO 上传到：

```text
/data/vm-images/shsystem-openeuler2403sp4/iso/
```

VMware/ESXi 应上传到该项目专用 Datastore 文件夹，Proxmox 应上传到对应存储的 ISO 内容目录；目录名称可以不同，但 ISO、系统盘、数据盘和备份应保持在同一个项目专用存储范围内。

```bash
virt-install --name shsystem-openeuler2403sp4 --memory 8192 --vcpus 4 \
  --disk path=/data/vm-images/shsystem-openeuler2403sp4/disks/system.qcow2,size=100,format=qcow2 \
  --cdrom /data/vm-images/shsystem-openeuler2403sp4/iso/openEuler-24.03-LTS-SP4-everything-x86_64-dvd.iso \
  --os-variant generic --network network=default,model=virtio --graphics vnc
```

安装完成后卸载 ISO，登录检查：

```bash
cat /etc/os-release
cat /etc/openEuler-release 2>/dev/null || true
uname -m
df -h
free -h
nproc
```

必须确认 openEuler 24.03 LTS-SP4 和 `x86_64`。

### 4.2 ISO 已上传后的 KVM 部署步骤

以下命令在 **KVM/libvirt 宿主机**执行，不是在待安装的虚拟机内执行。假设 ISO 已上传到：

```text
/data/vm-images/shsystem-openeuler2403sp4/iso/openEuler-24.03-LTS-SP4-everything-x86_64-dvd.iso
```

1. 检查宿主机工具和 ISO：

```bash
sudo systemctl enable --now libvirtd
sudo virsh list --all
sudo virt-install --version
sudo test -r /data/vm-images/shsystem-openeuler2403sp4/iso/openEuler-24.03-LTS-SP4-everything-x86_64-dvd.iso
```

2. 确认 QEMU 可以访问 ISO 和磁盘目录：

```bash
ls -lh /data/vm-images/shsystem-openeuler2403sp4/iso/
namei -l /data/vm-images/shsystem-openeuler2403sp4/iso/openEuler-24.03-LTS-SP4-everything-x86_64-dvd.iso
getent passwd qemu || getent passwd libvirt-qemu || true
sudo chmod 755 /data /data/vm-images /data/vm-images/shsystem-openeuler2403sp4
sudo chmod 755 /data/vm-images/shsystem-openeuler2403sp4/iso /data/vm-images/shsystem-openeuler2403sp4/disks
sudo chmod 644 /data/vm-images/shsystem-openeuler2403sp4/iso/openEuler-24.03-LTS-SP4-everything-x86_64-dvd.iso
```

3. 确认虚拟机名称和磁盘没有占用：

```bash
sudo virsh list --all --name
sudo test ! -e /data/vm-images/shsystem-openeuler2403sp4/disks/system.qcow2
```

4. 创建 100 GB qcow2 系统盘：

```bash
sudo qemu-img create -f qcow2 /data/vm-images/shsystem-openeuler2403sp4/disks/system.qcow2 100G
sudo qemu-img info /data/vm-images/shsystem-openeuler2403sp4/disks/system.qcow2
```

5. 创建并启动虚拟机：

```bash
sudo virt-install \
  --connect qemu:///system \
  --name shsystem-openeuler2403sp4 \
  --memory 8192 \
  --vcpus 4 \
  --disk path=/data/vm-images/shsystem-openeuler2403sp4/disks/system.qcow2,format=qcow2,bus=virtio \
  --cdrom /data/vm-images/shsystem-openeuler2403sp4/iso/openEuler-24.03-LTS-SP4-everything-x86_64-dvd.iso \
  --os-variant generic \
  --network network=default,model=virtio \
  --graphics vnc,listen=127.0.0.1 \
  --noautoconsole
```

6. 查看状态和 VNC 显示号：

```bash
sudo virsh list --all
sudo virsh domblklist shsystem-openeuler2403sp4
sudo virsh vncdisplay shsystem-openeuler2403sp4
```

使用宿主机 `virt-manager` 连接 `qemu:///system` 打开图形控制台。没有图形桌面时，可用 SSH 隧道转发 VNC；不要把 VNC 端口直接暴露到公网：

```bash
ssh -L 5901:127.0.0.1:5901 <SSH_USER>@<SERVER_IP> -p <SSH_PORT>
```

实际端口以 `virsh vncdisplay` 为准，`:1` 通常对应 `5901`。

7. 在安装界面中选择系统盘，设置主机名、`Asia/Shanghai` 时区、管理员账号、强密码和静态网络。安装完成后在虚拟机内检查：

```bash
cat /etc/os-release
uname -m
ip addr
```

8. 安装完成后卸载 ISO，设置虚拟机自动启动：

```bash
sudo virsh change-media shsystem-openeuler2403sp4 sda --eject --config
sudo virsh domblklist shsystem-openeuler2403sp4
sudo virsh autostart shsystem-openeuler2403sp4
```

如果光驱设备不是 `sda`，以 `domblklist` 输出的设备名为准。ISO 可以继续保留在 `iso/` 目录，系统运行使用 `disks/system.qcow2`。

## 5. openEuler 初始化

包名以现场批准的软件源为准：

```bash
sudo dnf clean all
sudo dnf makecache
sudo dnf install -y curl ca-certificates tar unzip vim rsync firewalld openssl
sudo systemctl enable --now firewalld
sudo timedatectl set-timezone Asia/Shanghai
sudo dnf install -y docker
sudo systemctl enable --now docker
sudo docker version
sudo docker info
sudo usermod -aG docker <SSH_USER>
sudo dnf install -y docker-compose-plugin
docker compose version
```

如果现场只有独立命令，使用 `sudo dnf install -y docker-compose` 和 `docker-compose --version`，后续统一该命令。不要混装 Docker Engine，不要从不明地址下载二进制。

只开放必要入口：

```bash
sudo firewall-cmd --permanent --add-port=<SSH_PORT>/tcp
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

不要对公网开放 `3306`、`6379`、`8090`、`8091`。

## 6. Xftp 上传和导入

```bash
sudo mkdir -p /opt/shsystem/{compose,images,backup,logs}
sudo chown -R <SSH_USER>:<SSH_USER> /opt/shsystem
chmod 700 /opt/shsystem/compose
```

Xftp 会话填写主机 `<SERVER_IP>`、端口 `<SSH_PORT>`、用户 `<SSH_USER>`，将 `$work\images` 上传到 `/opt/shsystem/images/`，将 `$work\package` 内容上传到 `/opt/shsystem/compose/`。也可用：

```powershell
scp -P <SSH_PORT> "$work\images\*.tar" "<SSH_USER>@<SERVER_IP>:/opt/shsystem/images/"
scp -P <SSH_PORT> -r "$work\package\*" "<SSH_USER>@<SERVER_IP>:/opt/shsystem/compose/"
```

服务器导入：

```bash
cd /opt/shsystem
sha256sum images/*.tar
docker load -i images/mysql-5.7.tar
docker load -i images/ruoyi-web-1.0.0.tar
docker load -i images/ruoyi-screen-1.0.0.tar
docker image ls
cd /opt/shsystem/compose
mkdir -p docker/mysql/data docker/mysql/logs docker/web-main/uploadPath docker/web-main/redis-data docker/web-screen/upload docker/web-screen/sqllite
```

首次初始化前确认 `docker/mysql/data` 为空；已有数据时禁止删除。

## 7. 当前 MySQL 方案启动和验收

创建 `/opt/shsystem/compose/.env`，使用随机密码/令牌并设置 `chmod 600`：

```dotenv
MYSQL_ROOT_PASSWORD=<MYSQL_ROOT_PASSWORD>
PREDICTION_API_KEY=<PREDICTION_API_KEY>
GOVIEW_AUDIT_SECRET=<GOVIEW_AUDIT_SECRET>
WEB_PUBLIC_URL=http://<SERVER_IP>
SCREEN_PUBLIC_URL=http://<SERVER_IP>:3000
```

```bash
openssl rand -base64 32
openssl rand -hex 32
chmod 600 /opt/shsystem/compose/.env
cd /opt/shsystem/compose
docker compose --env-file .env -f docker/docker-compose.yml config > /tmp/shsystem-compose.yml
docker compose --env-file .env -f docker/docker-compose.yml up -d
docker compose --env-file .env -f docker/docker-compose.yml ps
docker inspect --format '{{json .State.Health}}' ruoyi-db
docker logs --tail=200 ruoyi-db
docker logs --tail=200 ruoyi-web
docker logs --tail=200 ruoyi-screen
docker exec -e MYSQL_PWD='<MYSQL_ROOT_PASSWORD>' ruoyi-db mysql -uroot -h127.0.0.1 -NBe "SELECT VERSION(), DATABASE();"
docker exec -e MYSQL_PWD='<MYSQL_ROOT_PASSWORD>' ruoyi-db mysql -uroot -h127.0.0.1 carbon_emissions -NBe "SHOW TABLES;"
docker exec ruoyi-web getent hosts ruoyi-db
curl -fsS -I http://<SERVER_IP>/
curl -fsS -I http://<SERVER_IP>:3000/
```

首次启动时，MySQL 入口脚本按文件名顺序执行 `docker/mysql/db/*.sql`；非空数据目录不会重复执行。浏览器访问 `http://<SERVER_IP>/` 和 `http://<SERVER_IP>:3000/`。

## 8. 严格三容器适配要求

不能直接使用 `compose.three-container.yml`。必须先：

1. 制作 MySQL 版应用镜像，移除 CERDB/PostgreSQL 参数，确认 MySQL JDBC 驱动、URL 和迁移脚本。
2. 制作 MySQL 版 Python 镜像，移除 `psycopg`、`CERDB_*` 默认值，安装实际 MySQL 驱动。
3. 将 Python 地址改为 `http://sh-python:8091`、`http://sh-python:8090`。
4. 创建 `compose.mysql-three-container.yml`，服务名为 `mysql`、`sh-python`、`sh-app`，只映射 `sh-app:80`，数据库和 Python 仅在内部网络可见。
5. 明确 GoView SQLite、上传和报告目录的持久化位置。

适配后才执行：

```bash
docker load -i /opt/shsystem/images/mysql-5.7.tar
docker load -i /opt/shsystem/images/sh-app-mysql-1.0.0.tar
docker load -i /opt/shsystem/images/sh-python-mysql-1.0.0.tar
cd /opt/shsystem/compose
docker compose --env-file .env -f compose.mysql-three-container.yml config
docker compose --env-file .env -f compose.mysql-three-container.yml up -d
docker compose --env-file .env -f compose.mysql-three-container.yml ps
docker exec sh-app getent hosts mysql
docker exec sh-app getent hosts sh-python
docker exec sh-python getent hosts mysql
```

未完成适配时，使用第 7 节；不要把 CERDB 配置文本替换成 `mysql` 后直接启动。

## 9. 备份、升级和排查

```bash
mkdir -p /opt/shsystem/backup/$(date +%F)
docker exec -e MYSQL_PWD='<MYSQL_ROOT_PASSWORD>' ruoyi-db mysqldump -uroot --single-transaction --routines --triggers carbon_emissions > /opt/shsystem/backup/$(date +%F)/carbon_emissions.sql
tar -czf /opt/shsystem/backup/$(date +%F)/web-files.tgz -C /opt/shsystem/compose/docker/web-main uploadPath -C /opt/shsystem/compose/docker/web-screen upload sqllite
sha256sum /opt/shsystem/backup/$(date +%F)/*
```

升级前记录镜像标签、Compose 渲染结果和备份校验值，上传新镜像后先 `docker load`、`docker compose config`，再更新目标服务。禁止全局 `docker system prune`。

| 现象 | 处理 |
| --- | --- |
| Compose 命令不存在 | 检查 `docker compose version` 或 `docker-compose --version`，统一使用已安装命令 |
| MySQL 不健康 | 查看 `docker logs ruoyi-db`、密码、磁盘、数据目录和 3306 冲突 |
| 应用连不到库 | 确认 URL 使用 `ruoyi-db:3306`，执行 `docker exec ruoyi-web getent hosts ruoyi-db` |
| SQL 未初始化 | 仅空数据目录自动执行；已有目录按迁移流程处理，不能删除业务数据 |
| 页面 502/预测失败 | 查看 `ruoyi-web` 日志、Java/Python 进程、Nginx、令牌和内存 |
| GoView 数据丢失 | 检查 `docker/web-screen/sqllite`、`upload` 挂载及备份 |

## 10. 上线前清单

- [ ] ISO SHA256 正确，虚拟机为 openEuler 24.03 LTS-SP4、`x86_64`。
- [ ] Docker、Compose 版本和镜像 SHA256 已记录。
- [ ] `.env` 已替换密码、令牌和地址，权限为 `600`。
- [ ] MySQL、上传、报告和 SQLite 目录位于持久化磁盘。
- [ ] 防火墙未暴露 MySQL、Redis、Python 端口。
- [ ] Compose 配置无未替换变量，MySQL 为 `healthy`。
- [ ] 已验证登录、数据库读写、文件上传、报表和预测功能。
- [ ] 已完成一次备份并验证文件可读取。
- [ ] 若要求严格三容器，已完成 MySQL 版应用/Python 镜像和独立 Python 联调。

