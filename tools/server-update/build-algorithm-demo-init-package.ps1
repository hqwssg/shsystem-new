$ErrorActionPreference = 'Stop'

$Root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$Source = Join-Path $PSScriptRoot 'algorithm-demo-data-init-20261110'
$Name = 'algorithm-demo-data-init-20261110'
$Destination = Join-Path $Root "deploy-package/$Name"
$Archive = Join-Path $Root "deploy-package/$Name.tar.gz"

if (-not (Test-Path -LiteralPath $Source)) { throw "Missing source package: $Source" }
if (Test-Path -LiteralPath $Destination) { Remove-Item -LiteralPath $Destination -Recurse -Force }
if (Test-Path -LiteralPath $Archive) { Remove-Item -LiteralPath $Archive -Force }
if (Test-Path -LiteralPath "$Archive.sha256") { Remove-Item -LiteralPath "$Archive.sha256" -Force }

New-Item -ItemType Directory -Path $Destination | Out-Null
Get-ChildItem -LiteralPath $Source -File | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $Destination
}

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$Readme = @'
# Algorithm demo data initialization

This package adds the 2026-11-10 demo project and versions for heavy-empty coordination, energy storage planning, and single-train regenerative braking. It does not update application code. Deploy the matching 2026-11-09 algorithm patch and its Python runtime first.

## Server execution

Upload this archive to `/opt`, then run:

```sh
cd /opt
sha256sum -c algorithm-demo-data-init-20261110.tar.gz.sha256
tar -xzf algorithm-demo-data-init-20261110.tar.gz
cd /opt/algorithm-demo-data-init-20261110
ALGORITHM_DEMO_DB_PASSWORD='1275410782h' bash init_algorithm_demo.sh --container ruoyi-db --database carbon_emissions --user root --account admin
```

The command above passes the known database password without an interactive prompt. `--user` is the MySQL account; `--account` is an existing website login used to resolve the real department binding. For a different deployment, change these values and the password to match its configuration. The password is visible in shell history and briefly in the process environment.

Proceed only after seeing `ALGORITHM_DEMO_INIT_OK` and `Completed`. Record the printed department ID and scoped backup directory. If an error occurs, do not use `--force` or rerun blindly; inspect the message and verify current rows first.

## Verify

```sh
docker cp /opt/algorithm-demo-data-init-20261110/verify_algorithm_demo.sql ruoyi-db:/tmp/verify_algorithm_demo.sql
docker exec -it ruoyi-db mysql -uroot -p --default-character-set=utf8mb4 carbon_emissions
```

Run `SOURCE /tmp/verify_algorithm_demo.sql;` in the MySQL prompt. Verify the two heavy versions, one single-train version, 54 frozen dataset files, planning inputs, and enabled bindings for the printed department. Refresh the browser and sign in with the selected existing website account.

Choose `新版常规任务演示（2026-11-10）` for the five regular heavy-empty workflows. Choose `储能选址定容演示（2026-11-10）` for storage planning. Choose `新版单列车回收演示（2026-11-10）` for single-train tasks. The storage planning version is a small synthetic functional test case and must not be used for investment decisions. Initialization does not create or calculate tasks.

`rollback_visibility.sql` only disables visibility for the specific project and department after its placeholder variable is replaced with the printed department ID. It does not delete versions, tasks, results, or other data.

The initializer creates a scoped backup of rows matching its fixed demo IDs before writing. It does not create a full database backup. It requires MySQL 8.x, the existing algorithm schema, `mysqldump` and `mysql` in the database container, and the documented grants. It performs no schema migration and does not contact a remote server during package generation.
'@
[IO.File]::WriteAllText((Join-Path $Destination 'README.md'), $Readme, $Utf8NoBom)

$Records = foreach ($File in (Get-ChildItem -LiteralPath $Destination -File | Where-Object Name -ne 'SHA256SUMS' | Sort-Object Name)) {
    "$( (Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash.ToLowerInvariant() )  $($File.Name)"
}
[IO.File]::WriteAllText((Join-Path $Destination 'SHA256SUMS'), ($Records -join "`n") + "`n", $Utf8NoBom)

& tar.exe -czf $Archive -C (Split-Path $Destination -Parent) $Name
if ($LASTEXITCODE -ne 0) { throw 'Archive creation failed.' }
$ArchiveHash = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText("$Archive.sha256", "$ArchiveHash  $Name.tar.gz`n", $Utf8NoBom)
Write-Output "PACKAGE=$Archive"
Write-Output "SHA256=$ArchiveHash"
