[CmdletBinding()]
param(
    [string]$Python = 'python.exe',
    [string]$Btvs = 'btvs.exe',
    [string]$Tshark = 'tshark.exe',
    [Parameter(Mandatory = $true)]
    [string]$State,
    [string]$Workout,
    [switch]$ResetBinding,
    [ValidateScript({ $_ -gt 0 -and -not [double]::IsInfinity($_) -and -not [double]::IsNaN($_) })]
    [double]$Duration = 3600
)

$previousErrorAction = $ErrorActionPreference
$previousConsoleEncoding = [Console]::OutputEncoding
$previousOutputEncoding = $OutputEncoding
$previousPythonEncoding = $env:PYTHONIOENCODING
$previousPythonUtf8 = $env:PYTHONUTF8
$locationPushed = $false
$launcherExitCode = 1

try {
    $ErrorActionPreference = 'Stop'
    $utf8 = [System.Text.UTF8Encoding]::new($false)
    [Console]::OutputEncoding = $utf8
    $OutputEncoding = $utf8
    $env:PYTHONIOENCODING = 'utf-8'
    $env:PYTHONUTF8 = '1'

    # Resolve caller-relative paths before switching to the repository root.
    $pythonPath = (Get-Command -Name $Python -CommandType Application -ErrorAction Stop).Source
    $btvsPath = (Get-Command -Name $Btvs -CommandType Application -ErrorAction Stop).Source
    $tsharkPath = (Get-Command -Name $Tshark -CommandType Application -ErrorAction Stop).Source
    $statePath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($State)
    $launcherArguments = @(
        '-m', 'experiments.keep_device.launcher',
        '--btvs', $btvsPath, '--tshark', $tsharkPath, '--state', $statePath,
        '--duration', $Duration.ToString([System.Globalization.CultureInfo]::InvariantCulture)
    )
    if ($Workout) {
        $workoutPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Workout)
        $launcherArguments += @('--workout', $workoutPath)
    }
    if ($ResetBinding) { $launcherArguments += '--reset-binding' }

    Push-Location -LiteralPath (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
    $locationPushed = $true
    & $pythonPath @launcherArguments
    $launcherExitCode = $LASTEXITCODE
}
catch {
    Write-Error -Message $_.Exception.Message -ErrorAction Continue
}
finally {
    if ($locationPushed) { Pop-Location }
    $env:PYTHONIOENCODING = $previousPythonEncoding
    $env:PYTHONUTF8 = $previousPythonUtf8
    [Console]::OutputEncoding = $previousConsoleEncoding
    $OutputEncoding = $previousOutputEncoding
    $ErrorActionPreference = $previousErrorAction
}

exit $launcherExitCode
