$ErrorActionPreference = "SilentlyContinue"

Write-Host "Stopping BuildMarshalAI services..." -ForegroundColor Cyan

$ports = @(8000, 5500, 8317, 8903)
$stopped = 0

foreach ($port in $ports) {
    $connections = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($connections) {
        foreach ($conn in $connections) {
            $procId = $conn.OwningProcess
            if ($procId -gt 0) {
                $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
                if ($proc) {
                    $name = $proc.ProcessName
                    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
                    Write-Host "Stopped $name on port $port (PID: $procId)" -ForegroundColor Yellow
                    $stopped++
                }
            }
        }
    }
}

# Also ensure any lingering cli-proxy-api processes are stopped
Get-Process -Name "cli-proxy-api" -ErrorAction SilentlyContinue | ForEach-Object {
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    Write-Host "Stopped cli-proxy-api process (PID: $($_.Id))" -ForegroundColor Yellow
    $stopped++
}

if ($stopped -gt 0) {
    Write-Host "All BuildMarshalAI services have been stopped." -ForegroundColor Green
} else {
    Write-Host "No active BuildMarshalAI services found running." -ForegroundColor Gray
}
