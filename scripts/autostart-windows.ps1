# TaskWA unattended autostart for Windows.
# Registers a Scheduled Task that runs at logon: starts Docker Desktop,
# waits for the engine, then `docker compose up -d` in this repo folder.
#
#   powershell -ExecutionPolicy Bypass -File scripts\autostart-windows.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\autostart-windows.ps1 -Uninstall
param(
    [switch]$Uninstall,
    [switch]$Run          # internal: the payload the scheduled task executes
)

$TaskName = "TaskWA Autostart"
$RepoDir  = Split-Path -Parent $PSScriptRoot

if ($Run) {
    $dockerExe = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dockerExe) { Start-Process $dockerExe }
    for ($i = 0; $i -lt 60; $i++) {
        docker info *> $null
        if ($LASTEXITCODE -eq 0) { break }
        Start-Sleep -Seconds 5
    }
    Set-Location $RepoDir
    docker compose up -d
    exit
}

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "TaskWA autostart removed."
    exit
}

$scriptPath = Join-Path $PSScriptRoot "autostart-windows.ps1"
$action  = New-ScheduledTaskAction -Execute "powershell.exe" `
           -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$scriptPath`" -Run"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Force | Out-Null

Write-Host "TaskWA autostart installed for: $RepoDir"
Write-Host "Also recommended: enable automatic sign-in (netplwiz) and, in your"
Write-Host "PC's BIOS/UEFI, 'Restore AC power' so the machine boots after a power cut."
