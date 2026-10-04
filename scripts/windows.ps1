# ASCII source for Windows PowerShell 5.1. Settings are stored as UTF-8.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Install', 'Connect')]
    [string]$Action,
    [string]$Distro,
    [string]$Repository,
    [string]$State,
    [string]$Workspace,
    [ValidateSet('documents', 'full')]
    [string]$Mode = 'documents',
    [switch]$AcceptFullPermissions,
    [switch]$SkipWorker
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

function Invoke-WslChecked {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    $previousPreference = $ErrorActionPreference
    try {
        # In PowerShell 5.1 native stderr can be an ErrorRecord; use the exit code.
        $ErrorActionPreference = 'Continue'
        & $script:WslCommand @Arguments
        $nativeExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($nativeExitCode -ne 0) { throw "WSL command failed (exit $nativeExitCode)." }
}

try {
    if ($Action -ne 'Install' -and ($AcceptFullPermissions -or $SkipWorker -or $PSBoundParameters.ContainsKey('Mode'))) {
        throw 'Mode and permission choices apply only to Install.'
    }
    if ($Mode -eq 'full' -and -not $AcceptFullPermissions) {
        throw 'Full mode has WSL user permissions. Pass -Mode full -AcceptFullPermissions only if you accept this access.'
    }
    if ($SkipWorker -and $Mode -ne 'full') { throw '-SkipWorker requires explicitly accepted full mode.' }
    $script:WslCommand = (Get-Command wsl.exe -ErrorAction Stop).Source
    if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA is unavailable.' }
    $settingsDirectory = Join-Path $env:LOCALAPPDATA 'LocalWorkspaceMCPWSL'
    $settingsPath = Join-Path $settingsDirectory 'settings.json'
    if (Test-Path -LiteralPath $settingsPath) {
        $settings = Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not $Distro) { $Distro = [string]$settings.distro }
        if (-not $Repository) { $Repository = [string]$settings.repository }
        if (-not $State) { $State = [string]$settings.state }
        if (-not $Workspace) { $Workspace = [string]$settings.workspace }
    }
    if (-not $Repository) { $Repository = '~/local-workspace-mcp' }
    if (-not $State) { $State = '~/.local/state/local-workspace-mcp-wsl' }
    if (-not $Workspace) { $Workspace = '~/LocalWorkspace' }
    foreach ($path in @($Repository, $State)) {
        if (-not ($path.StartsWith('/') -or $path.StartsWith('~/'))) {
            throw 'Repository and State must be absolute Linux paths or ~/ paths.'
        }
    }
    # Native Windows argument quoting cannot represent arbitrary embedded quotes.
    foreach ($value in @($Distro, $Repository, $State, $Workspace)) {
        if ($value -match '["\r\n]') { throw 'Paths and distribution names cannot contain quotes or line breaks.' }
    }
    $available = @(Invoke-WslChecked -Arguments @('--list', '--quiet') |
        ForEach-Object { ([string]$_).Replace([string][char]0, '').Trim() } | Where-Object { $_ })
    if (-not $Distro) {
        if ($available.Count -eq 1) { $Distro = $available[0] }
        else { throw 'Specify -Distro using a name from wsl --list --quiet. Complete WSL first-run setup first.' }
    }
    if ($available -notcontains $Distro) { throw "WSL distribution '$Distro' is not installed." }
    $prefix = @('--distribution', $Distro, '--exec')
    if (-not ($Workspace.StartsWith('/') -or $Workspace.StartsWith('~/'))) {
        $absolute = [System.IO.Path]::GetFullPath($Workspace)
        $converted = @(Invoke-WslChecked -Arguments ($prefix + @('wslpath', '-a', '-u', $absolute)))
        if ($converted.Count -ne 1 -or -not ([string]$converted[0]).StartsWith('/')) {
            throw 'wslpath did not return one absolute Linux workspace path.'
        }
        $Workspace = ([string]$converted[0]).Trim()
    }
    # Fixed Python bootstrap; all user values remain argv, never shell/Python source.
    $bootstrap = "import os,runpy,sys; p=os.path.expanduser(sys.argv.pop(1)); runpy.run_path(os.path.join(p,'scripts','windows_wsl.py'),run_name='__main__')"
    $arguments = $prefix + @('python3', '-c', $bootstrap, $Repository, $Action.ToLowerInvariant(), '--state', $State)
    if ($Action -eq 'Install') {
        $arguments += @('--workspace', $Workspace, '--mode', $Mode)
        if ($AcceptFullPermissions) { $arguments += '--accept-full-permissions' }
        if ($SkipWorker) { $arguments += '--skip-worker' }
    }
    Invoke-WslChecked -Arguments $arguments
    if ($Action -eq 'Install') {
        New-Item -ItemType Directory -Force -Path $settingsDirectory | Out-Null
        $saved = [ordered]@{ distro = $Distro; repository = $Repository; state = $State; workspace = $Workspace }
        $utf8 = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllText($settingsPath, ($saved | ConvertTo-Json) + [Environment]::NewLine, $utf8)
        Write-Host "Installation succeeded. Saved non-secret choices to $settingsPath. Next: Connect ChatGPT.cmd."
    }
    exit 0
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
