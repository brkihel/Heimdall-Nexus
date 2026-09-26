<#
.SYNOPSIS
  Heimdall Nexus for Windows: prepares Python and opens the visual installer.

.DESCRIPTION
  Run from the repository folder, in PowerShell as administrator:

      powershell -ExecutionPolicy Bypass -File .\deploy\windows\install.ps1

  Installs a private Python 3.12 in "%ProgramFiles%\HeimdallNexus\python"
  (outside PATH, so it never replaces another Python), checks the installer's
  signature, and starts the wizard on http://127.0.0.1:8765 in your browser.

  -Direct   also listen on this machine's network addresses (plain HTTP),
            for installing from another computer on a network you trust.
  -Check    only verify this machine, without changing anything.
#>
param([switch]$Direct, [switch]$Check, [int]$Port = 8765)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$identity = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Open PowerShell as administrator and run this script again.'
}
if (-not [Environment]::Is64BitOperatingSystem) { throw 'Heimdall Nexus needs 64-bit Windows.' }
$build = [Environment]::OSVersion.Version.Build
if ($build -lt 17763) { throw 'Heimdall Nexus needs Windows 10 1809, Windows Server 2019 or newer.' }

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if (-not (Test-Path (Join-Path $repo 'servicos\painel\app.py'))) { throw "This does not look like the Heimdall Nexus folder: $repo" }
$free = (Get-PSDrive -Name ($env:ProgramData.Substring(0, 1))).Free / 1GB
"Windows build $build, $([math]::Round($free)) GB free on the data drive."
if ($free -lt 10) { throw 'At least 10 GB free are needed for Valheim, worlds and backups.' }
if ($Check) { 'This machine can run the Heimdall Nexus installer.'; exit 0 }

$appBase = Join-Path $env:ProgramFiles 'HeimdallNexus'
$python = Join-Path $appBase 'python\python.exe'
if (-not (Test-Path $python)) {
    'Installing a private Python 3.12 for Heimdall...'
    $url = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe'
    $setup = Join-Path $env:TEMP 'heimdall-python-3.12.10-amd64.exe'
    Invoke-WebRequest -Uri $url -OutFile $setup -UseBasicParsing
    $signature = Get-AuthenticodeSignature -LiteralPath $setup
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Python Software Foundation') {
        Remove-Item -LiteralPath $setup -Force
        throw 'The Python installer is not signed by the Python Software Foundation.'
    }
    # TargetDir is quoted: an unquoted path with a space would install to C:\Program.
    $target = Join-Path $appBase 'python'
    $arguments = "/quiet InstallAllUsers=1 `"TargetDir=$target`" Include_launcher=0 PrependPath=0 " +
                 'Include_test=0 Include_doc=0 Include_tcltk=0 AssociateFiles=0 Shortcuts=0 CompileAll=1'
    $process = Start-Process -FilePath $setup -ArgumentList $arguments -Wait -PassThru
    Remove-Item -LiteralPath $setup -Force
    if ($process.ExitCode -ne 0 -or -not (Test-Path $python)) { throw "Python setup failed ($($process.ExitCode))." }
}
& $python --version

$wizard = @('-X', 'utf8', (Join-Path $repo 'deploy\setup_server.py'), '--port', $Port)
if ($Direct) { $wizard += '--direct' }
& $python @wizard
exit $LASTEXITCODE
