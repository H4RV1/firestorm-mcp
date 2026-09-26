param([string]$Viewer, [string]$DataDir, [switch]$LoginScreen, [switch]$DryRun, [switch]$ScriptEditor)
$ErrorActionPreference = 'Stop'
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $venvPython)) { throw 'Run Install.cmd first.' }
$launchArgs = @('-m', 'firestorm_mcp.launcher')
if ($Viewer) { $launchArgs += @('--viewer', $Viewer) }
if ($DataDir) { $launchArgs += @('--data-dir', $DataDir) }
if ($LoginScreen) { $launchArgs += '--login-screen' }
if ($DryRun) { $launchArgs += '--dry-run' }
if ($ScriptEditor) { $launchArgs += '--script-editor' }
& $venvPython @launchArgs
if ($LASTEXITCODE) { throw 'Firestorm was not launched. See the reason above.' }
