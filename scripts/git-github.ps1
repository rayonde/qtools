[CmdletBinding()]
param(
    [Parameter(Position = 0, ValueFromRemainingArguments = $true)]
    [string[]] $GitArgs
)

$ErrorActionPreference = 'Stop'
$HostName = 'github.com'
$PublicDnsServers = @('1.1.1.1', '8.8.8.8', '223.5.5.5')
$HostsPath = Join-Path $env:SystemRoot 'System32\drivers\etc\hosts'
$CachePath = Join-Path (git rev-parse --git-dir) 'github-ip-cache'

if (-not $GitArgs -or $GitArgs.Count -eq 0) {
    throw "Usage: .\scripts\git-github.ps1 <git arguments>`nExample: .\scripts\git-github.ps1 push origin main:main"
}

function Get-PublicDnsAddresses {
    $addresses = @()
    foreach ($server in $PublicDnsServers) {
        try {
            $addresses += Resolve-DnsName -Name $HostName -Type A -Server $server -DnsOnly -ErrorAction Stop |
                Where-Object { $_.Type -eq 'A' } |
                Select-Object -ExpandProperty IPAddress
        }
        catch {
            Write-Verbose "Public DNS $server failed: $($_.Exception.Message)"
        }
    }
    return $addresses
}

function Get-HostsAddresses {
    $addresses = @()
    foreach ($line in Get-Content -LiteralPath $HostsPath -ErrorAction SilentlyContinue) {
        $entry = ($line -replace '#.*$', '').Trim()
        if (-not $entry) { continue }

        $parts = $entry -split '\s+'
        if ($parts.Count -ge 2 -and $parts[1..($parts.Count - 1)] -contains $HostName) {
            $addresses += $parts[0]
        }
    }
    return $addresses
}

function Get-CachedAddress {
    if (Test-Path -LiteralPath $CachePath) {
        $value = (Get-Content -LiteralPath $CachePath -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
        if ($value) { return $value }
    }
    return $null
}
function Get-ConfiguredAddress {
    $value = & git config --local --get http.curloptResolve 2>$null
    if ($value -match ':443:(\d{1,3}(?:\.\d{1,3}){3})$') {
        return $Matches[1]
    }
    return $null
}

function Test-GitHubAddress {
    param([string] $IpAddress)

    $code = & curl.exe --silent --show-error --output NUL --write-out '%{http_code}' `
        --connect-timeout 3 --max-time 8 `
        --resolve "${HostName}:443:$IpAddress" "https://$HostName/" 2>$null

    $statusCode = 0
    if ([int]::TryParse(([string]$code).Trim(), [ref]$statusCode)) {
        return $statusCode -ge 200 -and $statusCode -lt 400
    }
    return $false
}

$candidates = @(
    @(Get-PublicDnsAddresses)
    @(Get-HostsAddresses)
    @(Get-CachedAddress)
    @(Get-ConfiguredAddress)
) | Where-Object { $_ -match '^\d{1,3}(\.\d{1,3}){3}$' } | Select-Object -Unique

if (-not $candidates) {
    throw "No candidate IP addresses found for $HostName."
}

$selectedIp = $null
foreach ($ip in $candidates) {
    Write-Host "Testing $HostName via $ip ... " -NoNewline
    if (Test-GitHubAddress -IpAddress $ip) {
        Write-Host 'OK'
        $selectedIp = $ip
        break
    }
    Write-Host 'unavailable'
}

if (-not $selectedIp) {
    throw "No reachable IP address found for $HostName. Candidates: $($candidates -join ', ')"
}

try {
    Set-Content -LiteralPath $CachePath -Value $selectedIp -Encoding ascii
}
catch {
    Write-Verbose "Could not update IP cache: $($_.Exception.Message)"
}

Write-Host "Using $HostName -> $selectedIp"
& git -c "http.curloptResolve=${HostName}:443:$selectedIp" @GitArgs
exit $LASTEXITCODE

