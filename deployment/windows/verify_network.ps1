$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$netstat = & netstat.exe -ano -p tcp
$postgresAddresses = @($netstat | ForEach-Object {
    if ($_ -match '^\s*TCP\s+(\S+):5432\s+\S+\s+LISTENING\s+\d+\s*$') {
        $matches[1].Trim('[', ']')
    }
})
if (-not $postgresAddresses) {
    throw "PostgreSQL is not listening on TCP 5432."
}
$unsafePostgresAddresses = $postgresAddresses | Where-Object {
    $_ -notin @("127.0.0.1", "::1")
}
if ($unsafePostgresAddresses) {
    $addresses = ($unsafePostgresAddresses | Sort-Object -Unique) -join ", "
    throw "PostgreSQL is listening beyond localhost: $addresses"
}

$waitressAddresses = @($netstat | ForEach-Object {
    if ($_ -match '^\s*TCP\s+(\S+):8080\s+\S+\s+LISTENING\s+\d+\s*$') {
        $matches[1].Trim('[', ']')
    }
})
[pscustomobject]@{
    PostgreSQLAddresses = ($postgresAddresses | Sort-Object -Unique) -join ", "
    WaitressAddresses = ($waitressAddresses | Sort-Object -Unique) -join ", "
}
