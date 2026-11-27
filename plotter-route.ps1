# Test browser access to one plotter IP. Keep only a successful test route.
$ErrorActionPreference = 'Stop'
$ip = '192.168.2.15'
$prefix = "$ip/32"
$gateway = '192.168.1.1'
$lan = Get-NetIPConfiguration -InterfaceAlias Ethernet
if (@($lan.IPv4DefaultGateway.NextHop) -notcontains $gateway) {
    throw 'Expected Keenetic gateway not found on Ethernet. No changes made.'
}
if (Get-NetRoute -AddressFamily IPv4 -DestinationPrefix $prefix -ErrorAction SilentlyContinue) {
    throw 'A route to the plotter already exists. It was left unchanged.'
}
Get-Command curl.exe -ErrorAction Stop | Out-Null
$params = @{
    DestinationPrefix = $prefix
    InterfaceIndex = $lan.InterfaceIndex
    NextHop = $gateway
    RouteMetric = 1
    PolicyStore = 'ActiveStore'
}
$route = New-NetRoute @params
$keep = $false
try {
    curl.exe --noproxy '*' --fail --silent --show-error --max-time 5 --output NUL "http://$ip/"
    if ($LASTEXITCODE -eq 0) {
        $keep = $true
        Write-Host "OK: http://$ip/ (route lasts until Windows restarts)."
    } else {
        Write-Host 'Plotter did not respond over HTTP.'
    }
} finally {
    if (-not $keep) {
        $route | Remove-NetRoute -Confirm:$false -ErrorAction Stop
        Write-Host 'Temporary route removed.'
    }
}
