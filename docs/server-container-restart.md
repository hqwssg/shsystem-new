# 服务器容器重启手册

本文记录当前服务器环境（`ruoyi-db`、`ruoyi-web`、`ruoyi-screen`）已经验证过的重启方式。

服务器地址：`202.115.17.253`  
主系统端口：`53221`  
大屏端口：`53231`  
数据库：`carbon_emissions`

## 1. 重要说明

当前三个容器的入口不是完整的 systemd 启动流程。尤其是 `ruoyi-db` 的 PID 1 为 `/bin/bash`，所以：

```bash
docker restart ruoyi-db
```

只能重启容器，不会自动启动容器内的 MySQL。每次服务器或容器重启后，都必须按本文第 2 节启动数据库进程。

不要执行以下命令：

```bash
docker compose down -v
docker system prune --volumes
rm -rf /var/lib/mysql
```

这些命令可能删除数据库数据或 Docker 数据卷。

## 2. 完整启动顺序

以下命令在服务器宿主机执行。数据库密码按当前环境填写为 `1275410782h`。

### 2.1 检查磁盘和启动数据库容器

```bash
df -h /
docker start ruoyi-db 2>/dev/null || true
```

根分区建议保持至少 4 GB 可用空间。历史备份应放在空间较大的 `/home` 分区；当前环境的备份目录为 `/home/ruoyi-backups`，`/opt/ruoyi-backups` 是兼容旧脚本的软链接。

### 2.2 启动容器内 MySQL

```bash
docker exec -u 0 ruoyi-db sh -lc \
'install -d -o mysql -g mysql -m 755 /var/run/mysqld'

if ! docker exec ruoyi-db mysqladmin \
  -h127.0.0.1 -uroot -p'1275410782h' ping >/dev/null 2>&1; then
  docker exec -d -u 0 ruoyi-db \
    /usr/sbin/mysqld --defaults-file=/etc/my.cnf --user=mysql
fi

sleep 15
docker exec ruoyi-db mysqladmin \
  -h127.0.0.1 -uroot -p'1275410782h' ping
```

成功标志：

```text
mysqld is alive
```

如果失败，先查看日志，不要重复启动多个 MySQL 进程：

```bash
docker exec -u 0 ruoyi-db sh -lc \
'tail -n 200 /var/log/mysqld.log 2>/dev/null || true; ps -ef | grep -E "[m]ysqld|[m]ariadbd" || true'
docker logs --tail=200 ruoyi-db
```

### 2.3 启动主业务和大屏容器

确认数据库显示 `mysqld is alive` 后执行：

```bash
docker start ruoyi-web ruoyi-screen 2>/dev/null || true

docker exec ruoyi-web sh -lc \
'if [ -x /usr/local/bin/start-ruoyi-web.sh ]; then sh /usr/local/bin/start-ruoyi-web.sh; fi'

docker exec ruoyi-screen sh -lc \
'if [ -x /usr/local/bin/start-ruoyi-screen.sh ]; then sh /usr/local/bin/start-ruoyi-screen.sh; fi'

docker ps
```

### 2.4 验证端口和页面

```bash
curl -I --max-time 10 http://127.0.0.1:53221/
curl -I --max-time 10 http://127.0.0.1:53231/
```

外部访问地址：

```text
http://202.115.17.253:53221/
http://202.115.17.253:53231/
```

## 3. 报告默认数据初始化（仅需要时执行）

数据库和主业务启动后，才执行初始化脚本：

```bash
bash /opt/carbon-report-init/init_report_defaults.sh \
  --container ruoyi-db \
  --database carbon_emissions \
  --user root \
  --backup-dir /opt/ruoyi-backups/report-defaults-$(date +%Y%m%d-%H%M%S)
```

脚本提示密码时输入 `1275410782h`。成功标志为：

```text
REPORT_DEFAULTS_INIT_OK
```

该脚本会先备份、使用事务并保持幂等，不需要在成功后重启业务容器。

## 4. 启动失败时的最小排查

按以下顺序采集信息：

```bash
df -h /
docker ps -a
docker logs --tail=200 ruoyi-db
docker logs --tail=200 ruoyi-web
docker logs --tail=200 ruoyi-screen
```

磁盘不足时，只处理已确认无用的旧压缩包或旧备份；不要删除 `/var/lib/mysql`、Docker 数据目录或正在使用的容器层。

