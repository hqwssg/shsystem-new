# Monthly report and analysis update

Package: `PACKAGE_NAME_PLACEHOLDER`

This is a code-only update for the monthly report and monthly analysis changes. It contains the main backend JAR, carbon model JAR, main UI, GoView UI, and report renderer. It does not contain SQL, database exports, Redis data, GoView SQLite data, uploads, or application configuration.

The apply script verifies the outer package checksum separately from the package manifest, checks database connectivity and the three expected monthly tables before changing application files, then restarts the application processes in `ruoyi-web` and `ruoyi-screen`. It does not restart `ruoyi-db`, execute SQL, create a server backup, or change business data.

## Known limitations

The source delivery's `已知问题.txt` lists unresolved production risks, including node-rollup authorization scope and monthly report values not being bound to a calculation-task snapshot. This package does not fix those issues. Do not treat a successful install as proof of correct production authorization or report values. Complete the listed security and data-consistency review before using the new monthly node analysis or monthly report figures as authoritative production results.

The package requires the existing monthly collection and calculation-node production pipelines and all three tables to already exist. It does not create missing tables or backfill historical monthly results. The apply script stops before replacing files if MySQL is unavailable or any required table is missing.

## Upload and update

Upload the archive and adjacent `.sha256` file to `/opt/` using the existing file-transfer method. Run on the server host:

```bash
cd /opt
sha256sum -c PACKAGE_NAME_PLACEHOLDER.tar.gz.sha256
tar -xzf PACKAGE_NAME_PLACEHOLDER.tar.gz
cd /opt/PACKAGE_NAME_PLACEHOLDER
sha256sum -c SHA256SUMS
```

If checksum verification succeeds, first inspect the current services and database:

```bash
docker ps --filter name=ruoyi-db --filter name=ruoyi-web --filter name=ruoyi-screen
docker exec ruoyi-db mysqladmin -h127.0.0.1 -uroot ping
```

Only continue when MySQL reports `mysqld is alive`. Do not repeatedly start another `mysqld` process if it is already running. If it is unavailable, stop here and inspect `docker logs --tail=200 ruoyi-db` and the database process log before deploying.

Run the no-SQL update. It prompts for the database password without echoing it; do not put the password in shell history or logs.

```bash
set -o pipefail
bash ./apply-update.sh 2>&1 | tee /opt/PACKAGE_NAME_PLACEHOLDER.log
```

The script keeps `ruoyi-db` running, replaces only application-owned frontend directories, application JARs, and the report renderer, and restarts all processes managed by the existing web and screen startup scripts. It leaves Redis and GoView SQLite data, uploads, runtime configuration, and MySQL data in place. No backup is made by this update.

If the script stops before replacing files, no application files were changed. If a failure happens during replacement, the script attempts to restart services but cannot restore replaced files because server-side backups are intentionally disabled. Preserve the terminal log and container logs and fix forward; do not rerun database initialization.

## Post-update checks

```bash
curl -I --max-time 10 http://127.0.0.1:53221/
curl -I --max-time 10 http://127.0.0.1:53221/carbon-model/
curl -I --max-time 10 http://127.0.0.1:53231/
docker exec ruoyi-web pgrep -af java
docker exec ruoyi-screen pgrep -af java
docker exec ruoyi-web nginx -t
docker exec ruoyi-screen nginx -t
```

The GoView project page should open without the warning dialog and show `返回主页面` in the header. Validate authenticated and restricted-user monthly analysis, cross-year report activity, missing months, and old report regeneration separately before relying on those figures.
