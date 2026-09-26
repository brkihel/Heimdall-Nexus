<#
.SYNOPSIS
  Removes Heimdall Nexus from this Windows machine.

.DESCRIPTION
  Run in PowerShell as administrator:

      powershell -ExecutionPolicy Bypass -File .\deploy\windows\uninstall.ps1

  Always removes the services, firewall rules, scheduled update task and the
  code in "%ProgramFiles%\HeimdallNexus". Worlds, backups, the site and
  settings in "%ProgramData%\HeimdallNexus" are kept unless -RemoveData is
  given, and Heimdall's private Python is kept unless -RemovePython is given.

  -RemoveData    also erase worlds, backups, the site and every setting
  -RemovePython  also uninstall Heimdall's private Python
  -Yes           do not ask for confirmation
#>
param([switch]$RemoveData, [switch]$RemovePython, [switch]$Yes)

$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Open PowerShell as administrator and run this script again.'
}
$appBase = Join-Path $env:ProgramFiles 'HeimdallNexus'
$dataBase = Join-Path $env:ProgramData 'HeimdallNexus'

if (-not $Yes) {
    "This removes the Heimdall Nexus services and code from this computer."
    if ($RemoveData) { "It ALSO ERASES worlds, backups, the site and settings in $dataBase." }
    else { "Worlds, backups, the site and settings stay in $dataBase." }
    if ((Read-Host 'Type REMOVE to continue') -ne 'REMOVE') { 'Nothing was changed.'; exit 1 }
}

'Stopping and removing the services...'
$names = 'heimdall-web', 'heimdall-panel', 'heimdall-sagas-jobs', 'heimdall-jobs', 'heimdall-valheim', 'heimdall-executor'
foreach ($name in $names) {
    $service = Get-Service -Name $name -ErrorAction SilentlyContinue
    if (-not $service) { continue }
    if ($service.Status -ne 'Stopped') {
        # The game saves the world when it stops: give it the time it needs.
        Stop-Service -Name $name -Force -ErrorAction SilentlyContinue
        $service.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(180))
    }
    & sc.exe delete $name | Out-Null
    "  $name removed"
}

'Removing the service accounts profiles...'
# Windows keeps a profile for each service account; it stays loaded until the
# next restart, so what cannot go now goes once at the next boot.
$profiles = Get-CimInstance Win32_UserProfile -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPath -like '*\ServiceProfiles\heimdall-*' }
$left = @()
foreach ($profile in $profiles) {
    try { Remove-CimInstance -InputObject $profile -ErrorAction Stop } catch { $left += $profile.LocalPath }
}
if ($left) {
    $cleanup = "Get-CimInstance Win32_UserProfile | Where-Object { `$_.LocalPath -like '*\ServiceProfiles\heimdall-*' } | Remove-CimInstance; " +
               "Unregister-ScheduledTask -TaskName 'heimdall-cleanup-profiles' -Confirm:`$false"
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -NonInteractive -Command `"$cleanup`""
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    Register-ScheduledTask -TaskName 'heimdall-cleanup-profiles' -Action $action -Trigger (New-ScheduledTaskTrigger -AtStartup) `
        -Principal $principal -Description 'Heimdall Nexus: removes the leftover service profiles once, then removes itself.' -Force | Out-Null
    "  $($left.Count) profile(s) in use; removed at the next restart"
}

'Removing firewall rules and the update task...'
Get-NetFirewallRule -DisplayName 'Heimdall Nexus - *' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Unregister-ScheduledTask -TaskName 'heimdall-self-update' -Confirm:$false -ErrorAction SilentlyContinue

if ($RemovePython) {
    'Uninstalling Heimdall''s private Python...'
    $target = Join-Path $appBase 'python'
    $installed = (Get-ItemProperty 'HKLM:\SOFTWARE\Python\PythonCore\3.12\InstallPath' -ErrorAction SilentlyContinue).'(default)'
    # Only the Python that lives in Heimdall's folder, never another one. Its
    # bundle must run before the folder goes: without the files it fails (1603).
    if ($installed -and ($installed.TrimEnd('\') -eq $target)) {
        $bundles = Get-ChildItem 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
                                 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall' -ErrorAction SilentlyContinue |
            ForEach-Object { Get-ItemProperty $_.PSPath } |
            Where-Object { $_.DisplayName -like 'Python 3.12.* (64-bit)' -and $_.QuietUninstallString -match 'Package Cache' }
        foreach ($bundle in $bundles) {
            $exe = ($bundle.QuietUninstallString -split '"')[1]
            $process = Start-Process -FilePath $exe -ArgumentList '/uninstall /quiet' -Wait -PassThru
            "  Python uninstaller finished with code $($process.ExitCode)"
        }
    }
}

'Removing the shortcuts and the Windows apps entry...'
$links = (Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs\Heimdall Nexus.lnk'),
         (Join-Path $env:PUBLIC 'Desktop\Heimdall Nexus.lnk')
$links | Where-Object { Test-Path $_ } | Remove-Item -Force
Remove-Item 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\HeimdallNexus' -Recurse -ErrorAction SilentlyContinue

'Removing the code...'
$keep = if ($RemovePython) { @() } else { @('python') }
if (Test-Path $appBase) {
    Get-ChildItem $appBase -Force | Where-Object { $keep -notcontains $_.Name } | Remove-Item -Recurse -Force
    if (-not (Get-ChildItem $appBase -Force)) { Remove-Item $appBase -Force }
}

if ($RemoveData -and (Test-Path $dataBase)) {
    'Erasing the data...'
    # Junctions are removed as links, never followed.
    Get-ChildItem $dataBase -Recurse -Force -Attributes ReparsePoint -ErrorAction SilentlyContinue |
        ForEach-Object { $_.Delete() }
    Remove-Item $dataBase -Recurse -Force
}
'Heimdall Nexus was removed.'
