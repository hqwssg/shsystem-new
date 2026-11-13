-- 在具有 CREATEDB 权限的管理连接中执行；业务迁移由 migrations/ 管理。
-- PostgreSQL 不支持在事务中执行 CREATE DATABASE。
SELECT 'CREATE DATABASE carbon_emissions ENCODING ''UTF8'' TEMPLATE template0'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'carbon_emissions')\gexec

