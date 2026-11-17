<#
Restore drill for Windows PowerShell (same idea as scripts/restore-check.sh): restores a dump into a THROW-AWAY database,
prints row counts next to the live database, then drops the scratch database. Never touches live data.

  powershell -ExecutionPolicy Bypass -File scripts\restore-check.ps1 backups\queuecare-YYYYMMDDTHHMMSSZ.dump
#>
param([Parameter(Mandatory = $true)][string]$Dump)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
if (-not (Test-Path $Dump)) { throw "No such file: $Dump" }

# Read the few values we need from .env.production (it is not executed as code).
$cfg = @{}
Get-Content ".env.production" | ForEach-Object {
    if ($_ -match '^\s*([A-Z_]+)=(.*?)\s*(\s#.*)?$') { $cfg[$Matches[1]] = $Matches[2] }
}
$user = $cfg["POSTGRES_USER"]; $db = $cfg["POSTGRES_DB"]; $pw = $cfg["POSTGRES_PASSWORD"]
if (-not $user -or -not $db -or -not $pw) { throw "POSTGRES_USER/POSTGRES_DB/POSTGRES_PASSWORD missing in .env.production" }

$compose = @("compose", "-f", "docker-compose.prod.yml", "--env-file", ".env.production")
$scratch = "restore_check_" + (Get-Random -Maximum 99999)
$remote = "/tmp/restore-check.dump"

function Run-Psql([string]$Database, [string]$Sql) {
    & docker @compose exec -T -e "PGPASSWORD=$pw" postgres psql -v ON_ERROR_STOP=1 -U $user -d $Database -c $Sql
    if ($LASTEXITCODE -ne 0) { throw "psql failed" }
}

try {
    Run-Psql "postgres" "CREATE DATABASE $scratch"
    # Copy the file INTO the container (no binary piping through PowerShell, which would corrupt it).
    & docker @compose cp $Dump "postgres:$remote"
    if ($LASTEXITCODE -ne 0) { throw "docker cp failed" }
    & docker @compose exec -T -e "PGPASSWORD=$pw" postgres pg_restore -U $user -d $scratch --no-owner --exit-on-error $remote
    if ($LASTEXITCODE -ne 0) { throw "pg_restore failed" }

    $q = "SELECT 'clinics' AS table_name, count(*) FROM clinics UNION ALL SELECT 'users', count(*) FROM users UNION ALL SELECT 'appointments', count(*) FROM appointments UNION ALL SELECT 'queue_tokens', count(*) FROM queue_tokens"
    Write-Host "== restored copy =="; Run-Psql $scratch $q
    Write-Host "== live database ==";  Run-Psql $db $q
    Write-Host "Restore succeeded. Row counts can differ by whatever changed since the dump."
}
finally {
    & docker @compose exec -T -e "PGPASSWORD=$pw" postgres psql -U $user -d postgres -c "DROP DATABASE IF EXISTS $scratch WITH (FORCE)" | Out-Null
    & docker @compose exec -T postgres rm -f $remote | Out-Null
}
