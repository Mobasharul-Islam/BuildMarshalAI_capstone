<#
.SYNOPSIS
    Get BuildMarshalAI's ports back from Hyper-V / WSL.

.DESCRIPTION
    Windows allocates ports to Hyper-V's NAT driver out of the TCP *dynamic
    port range*, and a port it has taken cannot be bound by anything else:
    bind() fails with WSAEACCES -- "an attempt was made to access a socket in a
    way forbidden by its access permissions" -- even with nothing listening.

    Windows' own default dynamic range is 49152-65535, which leaves ordinary
    service ports alone. Docker Desktop and some VPN clients move it down to
    start at 1024, and then everything from 1024 upwards is fair game. That is
    the cause: with a range starting at 1024, ports like 8000 and 8317 are
    inside it, so they get taken at boot, and a single-port exclusion cannot
    reliably hold them because the range re-grabs blocks on the next start.

        netsh int ipv4 show dynamicport tcp
        netsh int ipv4 show excludedportrange protocol=tcp

    So this script does two things:

      1. Puts the dynamic range back to the Windows default, which takes the
         whole 1024-49151 span out of contention. This is the actual fix.
         Skip it with -KeepDynamicRange.
      2. Adds the ports as persistent exclusions as well, so they are held
         even if something moves the range down again.

    A reboot is needed for blocks already handed out this boot to be released.

    Requires Administrator; it elevates itself if needed.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\RESERVE-PORTS.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\RESERVE-PORTS.ps1 -Revert
#>
param(
    [int[]]$Ports = @(5500, 8000, 8317),
    [switch]$Revert,
    [switch]$KeepDynamicRange,
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"

# ── Elevate ──────────────────────────────────────────────────────────────
# The elevated copy runs in a new window, so it pauses at the end: a window
# that opens and closes again looks exactly like a script that did nothing.
$identity = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Reserving ports needs Administrator. Asking for elevation..." -ForegroundColor Cyan
    Write-Host "Watch the new window -- it stays open so you can read the result." -ForegroundColor Cyan
    $arguments = @("-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"",
                   "-Ports", ($Ports -join ","))
    if ($Revert) { $arguments += "-Revert" }
    if ($KeepDynamicRange) { $arguments += "-KeepDynamicRange" }
    Start-Process -FilePath "powershell.exe" -ArgumentList $arguments -Verb RunAs
    return
}

function Test-PortBindable([int]$Port) {
    try {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
        $listener.Start(); $listener.Stop()
        return $true
    } catch {
        return $false
    }
}

function Get-DynamicRange {
    $text = (netsh int ipv4 show dynamicport tcp) -join "`n"
    $start = [regex]::Match($text, '(?m)Start Port\s*:\s*(\d+)')
    $count = [regex]::Match($text, '(?m)Number of Ports\s*:\s*(\d+)')
    if (-not $start.Success -or -not $count.Success) { return $null }
    return [pscustomobject]@{
        Start = [int]$start.Groups[1].Value
        Count = [int]$count.Groups[1].Value
    }
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "BuildMarshalAI port reservation" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

$range = Get-DynamicRange
if ($range) {
    $last = $range.Start + $range.Count - 1
    Write-Host "Dynamic port range : $($range.Start)-$last" -ForegroundColor DarkGray
}
Write-Host "Excluded ranges before:" -ForegroundColor DarkGray
netsh int ipv4 show excludedportrange protocol=tcp | Write-Host

$rangeChanged = $false

# ── 1. The cause: a dynamic range that reaches down over our ports ───────
if (-not $Revert -and -not $KeepDynamicRange -and $range -and $range.Start -lt 10000) {
    $last = $range.Start + $range.Count - 1
    Write-Host ""
    Write-Host "The TCP dynamic port range is $($range.Start)-$last." -ForegroundColor Yellow
    Write-Host "Windows' default is 49152-65535. Something (usually Docker Desktop)" -ForegroundColor Yellow
    Write-Host "moved it down, which is why ports like 8000 and 8317 get taken at" -ForegroundColor Yellow
    Write-Host "boot. Putting it back is the fix; it is the Microsoft default, and" -ForegroundColor Yellow
    Write-Host "Docker and WSL work normally with it." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  To undo later:  netsh int ipv4 set dynamicport tcp start=$($range.Start) num=$($range.Count)" -ForegroundColor DarkGray
    Write-Host ""

    $answer = Read-Host "Set the dynamic range back to the Windows default? [Y/n]"
    if ($answer -eq "" -or $answer -match '^[Yy]') {
        netsh int ipv4 set dynamicport tcp start=49152 num=16384 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  dynamic range set to 49152-65535" -ForegroundColor Green
            $rangeChanged = $true
        } else {
            Write-Host "  could not change the dynamic range" -ForegroundColor Red
        }
    } else {
        Write-Host "  left alone -- the exclusions below may not survive a reboot." -ForegroundColor Yellow
    }
}

# ── 2. Hold the ports explicitly as well ─────────────────────────────────
# winnat owns its blocks while it runs, so an exclusion cannot go underneath it.
$winnatWasRunning = $false
$winnat = Get-Service -Name winnat -ErrorAction SilentlyContinue
if ($winnat -and $winnat.Status -eq "Running") {
    $winnatWasRunning = $true
    Write-Host "`nStopping winnat (Hyper-V NAT) so it releases its blocks..." -ForegroundColor Cyan
    Stop-Service -Name winnat -Force
}

try {
    foreach ($port in $Ports) {
        netsh int ipv4 delete excludedportrange protocol=tcp startport=$port numberofports=1 store=persistent 2>&1 | Out-Null
        if ($Revert) {
            Write-Host "  released $port" -ForegroundColor Yellow
            continue
        }
        $output = netsh int ipv4 add excludedportrange protocol=tcp startport=$port numberofports=1 store=persistent 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  reserved $port" -ForegroundColor Green
        } else {
            Write-Host "  could not reserve $port (it is inside a block already handed out)" -ForegroundColor Yellow
            $output | ForEach-Object { Write-Host "      $_" -ForegroundColor DarkGray }
        }
    }
} finally {
    if ($winnatWasRunning) {
        Write-Host "Starting winnat again..." -ForegroundColor Cyan
        Start-Service -Name winnat
    }
}

# ── 3. Prove it, and be straight about what is left to do ────────────────
Write-Host "`nExcluded ranges after:" -ForegroundColor DarkGray
netsh int ipv4 show excludedportrange protocol=tcp | Write-Host

Write-Host "`nBind test:" -ForegroundColor Cyan
$failed = @()
foreach ($port in $Ports) {
    $listening = [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
    if ($listening) {
        Write-Host "  $port : in use by a running service (fine)" -ForegroundColor Green
    } elseif (Test-PortBindable $port) {
        Write-Host "  $port : bindable" -ForegroundColor Green
    } else {
        Write-Host "  $port : still blocked" -ForegroundColor Yellow
        $failed += $port
    }
}

Write-Host ""
if ($Revert) {
    Write-Host "Reservations removed." -ForegroundColor Yellow
} elseif ($failed.Count -eq 0) {
    Write-Host "All ports are available." -ForegroundColor Green
    Write-Host "Run START-BUILDMARSHAL.ps1 again." -ForegroundColor Green
} else {
    Write-Host "Still blocked: $($failed -join ', ')" -ForegroundColor Yellow
    if ($rangeChanged) {
        Write-Host ""
        Write-Host "This is expected. The blocks handed out during THIS boot are still" -ForegroundColor Yellow
        Write-Host "held; the new dynamic range only applies from the next one." -ForegroundColor Yellow
        Write-Host "REBOOT, then run START-BUILDMARSHAL.ps1 -- the usual ports come back." -ForegroundColor Cyan
    } else {
        Write-Host "Reboot and run this script again, or rerun it and accept the" -ForegroundColor Yellow
        Write-Host "dynamic-range change, which is what actually frees these ports." -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host "Either way BuildMarshalAI runs right now: START-BUILDMARSHAL.ps1" -ForegroundColor Green
    Write-Host "moves each service to a free port on its own." -ForegroundColor Green
}

if (-not $NoPause) {
    Write-Host ""
    Read-Host "Press Enter to close this window"
}
