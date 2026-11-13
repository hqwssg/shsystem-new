# 算法演示数据初始化交付

本包为重空协同、储能选址定容和单列车能量回收新增 2026-11-10 演示项目与版本，不更新应用代码。先部署对应的 2026-11-09 算法代码补丁及 Python 运行目录。

将 `algorithm-demo-data-init-20261110.tar.gz` 与校验文件上传到服务器 `/opt`，执行：

```sh
cd /opt
sha256sum -c algorithm-demo-data-init-20261110.tar.gz.sha256
tar -xzf algorithm-demo-data-init-20261110.tar.gz
cd /opt/algorithm-demo-data-init-20261110
ALGORITHM_DEMO_DB_PASSWORD='1275410782h' bash init_algorithm_demo.sh --container ruoyi-db --database carbon_emissions --user root --account admin
```

上面的命令使用已提供的数据库密码，不会再交互询问。`--user` 是 MySQL 账号，`--account` 是用于解析实际部门的既有网站登录账号。该密码会出现在 shell 历史记录及短暂的进程环境中。只有看到 `ALGORITHM_DEMO_INIT_OK` 和 `Completed` 才算初始化完成，并记录输出的实际部门 ID 与范围备份目录。发生错误时先核对错误和数据，不要使用 `--force` 或盲目重跑。

核对数据时先将只读脚本复制进数据库容器，再交互执行：

```sh
docker cp /opt/algorithm-demo-data-init-20261110/verify_algorithm_demo.sql ruoyi-db:/tmp/verify_algorithm_demo.sql
docker exec -it ruoyi-db mysql -uroot -p --default-character-set=utf8mb4 carbon_emissions
```

在 MySQL 提示符输入密码后执行：

```sql
SOURCE /tmp/verify_algorithm_demo.sql;
```

应核对两个重空版本、一个单列车版本、54 个冻结数据文件、规划配置及初始化输出部门的两个启用绑定。刷新页面并用对应既有网站账号登录。

常规重空任务选择“新版常规任务演示（2026-11-10）”；储能规划选择“储能选址定容演示（2026-11-10）”；单列车任务选择“新版单列车回收演示（2026-11-10）”。储能规划数据为功能测试用的小型合成算例，不用于投资决策。初始化不会创建或运行计算任务。

`rollback_visibility.sql` 仅用于隐藏本次演示项目。先将占位部门 ID 改成初始化输出的实际 ID，再执行；它不删除版本、任务、结果或其他数据。

初始化器会在写入前备份固定演示 ID 范围内的相关行，不是全库备份。要求 MySQL 8.x、已有算法表结构，数据库容器含 `mysql` 和 `mysqldump`，并授予说明文件列出的权限。不会执行建表迁移或连接服务器外部服务。
