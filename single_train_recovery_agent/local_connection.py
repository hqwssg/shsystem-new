"""Explicit DSN first, localhost-only development config fallback; never logs secrets."""
from urllib.parse import urlparse
import os
import pymysql
import yaml
from . import WORKSPACE
from database.mysql import connect_mysql

def connect():
    if os.environ.get('ENERGY_DATABASE_URL'):
        return connect_mysql(autocommit=True),'configured database'
    candidates=[WORKSPACE/'shuohuang-main/ruoyi-admin/target/classes/application.yml',WORKSPACE/'ruoyi-admin/target/classes/application.yml',WORKSPACE/'ruoyi-admin/src/main/resources/application.yml']
    path=next((p for p in candidates if p.is_file()),None)
    if path is None:raise ValueError('请配置 ENERGY_DATABASE_URL 后运行初始化或验收脚本')
    config=yaml.safe_load(path.read_text(encoding='utf-8'))
    master=config['spring']['datasource']['dynamic']['datasource']['master']
    url=urlparse(master['url'].removeprefix('jdbc:'))
    if url.hostname not in ('localhost','127.0.0.1'):raise ValueError('远程数据库必须显式配置 ENERGY_DATABASE_URL')
    db=pymysql.connect(host=url.hostname,port=url.port or 3306,user=master['username'],password=str(master['password']),database=url.path.lstrip('/'),charset='utf8mb4',autocommit=True)
    return db,f'{url.hostname}:{url.port or 3306}/{url.path.lstrip("/")}'
