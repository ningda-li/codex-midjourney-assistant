param(
    [string]$Port = "9230",
    [string]$ProfileDir = "",
    [string]$Browser = "",
    [string]$BrowserPath = "",
    [string]$EdgePath = "",
    [string]$PageUrl = "https://www.midjourney.com/imagine",
    [string]$OutputFile = "",
    [switch]$DetectOnly
)

$ErrorActionPreference = "Stop"

function Get-CodexHome {
    $skillRoot = Split-Path -Parent $PSScriptRoot
    $skillsRoot = Split-Path -Parent $skillRoot
    return Split-Path -Parent $skillsRoot
}

function Get-IsolatedBrowserRoot {
    $codexHome = Get-CodexHome
    return Join-Path $codexHome "memories\midjourney-assistant\isolated-browser"
}

function Get-LegacyEdgeProfileDir {
    return Join-Path (Get-IsolatedBrowserRoot) "edge-profile"
}

function Get-ProfilesRoot {
    return Join-Path (Get-IsolatedBrowserRoot) "profiles"
}

function Get-DefaultStatePath {
    return Join-Path (Get-IsolatedBrowserRoot) "runtime-state.json"
}

function Normalize-BrowserKey {
    param([string]$Value)
    if ($null -eq $Value) {
        return ""
    }
    return $Value.Trim().ToLowerInvariant()
}

function Normalize-PathValue {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return ""
    }
    try {
        return [System.IO.Path]::GetFullPath($Value)
    }
    catch {
        return $Value
    }
}

function Test-SamePath {
    param(
        [string]$Left,
        [string]$Right
    )
    return (Normalize-PathValue $Left).ToLowerInvariant() -eq (Normalize-PathValue $Right).ToLowerInvariant()
}

function Get-StatePayload {
    param([string]$StatePath)
    if (-not (Test-Path -LiteralPath $StatePath)) {
        return @{}
    }
    $content = Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8
    if ([string]::IsNullOrWhiteSpace($content)) {
        return @{}
    }
    try {
        $payload = $content | ConvertFrom-Json
    }
    catch {
        return @{}
    }
    if ($null -eq $payload) {
        return @{}
    }
    return $payload
}

function Get-SupportedBrowsers {
    $programFiles = $env:ProgramFiles
    $programFilesX86 = ${env:ProgramFiles(x86)}
    $localAppData = $env:LOCALAPPDATA

    return @(
        [PSCustomObject]@{
            key             = "edge"
            name            = "Edge"
            process_name    = "msedge.exe"
            candidate_paths = @(
                (Join-Path $programFilesX86 "Microsoft\Edge\Application\msedge.exe"),
                (Join-Path $programFiles "Microsoft\Edge\Application\msedge.exe")
            )
        },
        [PSCustomObject]@{
            key             = "chrome"
            name            = "Chrome"
            process_name    = "chrome.exe"
            candidate_paths = @(
                (Join-Path $programFiles "Google\Chrome\Application\chrome.exe"),
                (Join-Path $programFilesX86 "Google\Chrome\Application\chrome.exe"),
                (Join-Path $localAppData "Google\Chrome\Application\chrome.exe")
            )
        },
        [PSCustomObject]@{
            key             = "brave"
            name            = "Brave"
            process_name    = "brave.exe"
            candidate_paths = @(
                (Join-Path $programFiles "BraveSoftware\Brave-Browser\Application\brave.exe"),
                (Join-Path $programFilesX86 "BraveSoftware\Brave-Browser\Application\brave.exe"),
                (Join-Path $localAppData "BraveSoftware\Brave-Browser\Application\brave.exe")
            )
        },
        [PSCustomObject]@{
            key             = "vivaldi"
            name            = "Vivaldi"
            process_name    = "vivaldi.exe"
            candidate_paths = @(
                (Join-Path $programFiles "Vivaldi\Application\vivaldi.exe"),
                (Join-Path $programFilesX86 "Vivaldi\Application\vivaldi.exe"),
                (Join-Path $localAppData "Vivaldi\Application\vivaldi.exe")
            )
        },
        [PSCustomObject]@{
            key             = "arc"
            name            = "Arc"
            process_name    = "arc.exe"
            candidate_paths = @(
                (Join-Path $localAppData "Programs\Arc\Arc.exe")
            )
        }
    )
}

function Convert-ToBrowserCandidate {
    param(
        $Definition,
        [string]$ResolvedPath,
        [string]$Source
    )
    return [PSCustomObject]@{
        key            = $Definition.key
        name           = $Definition.name
        process_name   = $Definition.process_name
        path           = (Normalize-PathValue $ResolvedPath)
        source         = $Source
    }
}

function New-CustomBrowserCandidate {
    param(
        [string]$ResolvedPath,
        [string]$Source,
        [string]$BrowserName = ""
    )
    $normalizedPath = Normalize-PathValue $ResolvedPath
    $fileName = [System.IO.Path]::GetFileName($normalizedPath).ToLowerInvariant()
    $definition = Get-SupportedBrowsers |
        Where-Object { $_.candidate_paths | Where-Object { Test-SamePath $_ $normalizedPath } } |
        Select-Object -First 1
    if ($null -eq $definition) {
        $definition = Get-SupportedBrowsers | Where-Object { $_.process_name -eq $fileName } | Select-Object -First 1
    }
    $defaultName = if (-not [string]::IsNullOrWhiteSpace($BrowserName)) {
        $BrowserName
    }
    elseif ($null -ne $definition) {
        $definition.name
    }
    else {
        [System.IO.Path]::GetFileNameWithoutExtension($normalizedPath)
    }
    $defaultKey = if ($null -ne $definition) {
        $definition.key
    }
    else {
        $fallbackKey = [System.IO.Path]::GetFileNameWithoutExtension($normalizedPath)
        if ([string]::IsNullOrWhiteSpace($fallbackKey)) {
            $fallbackKey = "custom"
        }
        $fallbackKey.ToLowerInvariant()
    }
    $defaultProcess = if ($null -ne $definition) {
        $definition.process_name
    }
    else {
        $fileName
    }
    return [PSCustomObject]@{
        key          = $defaultKey
        name         = $defaultName
        process_name = $defaultProcess
        path         = $normalizedPath
        source       = $Source
    }
}

function Get-InstalledBrowserCandidates {
    foreach ($definition in Get-SupportedBrowsers) {
        $resolvedPath = $definition.candidate_paths |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) -and (Test-Path -LiteralPath $_) } |
            Select-Object -First 1
        if (-not [string]::IsNullOrWhiteSpace($resolvedPath)) {
            Convert-ToBrowserCandidate -Definition $definition -ResolvedPath $resolvedPath -Source "installed"
        }
    }
}

function Resolve-BrowserSelection {
    param(
        [string]$PreferredBrowser,
        [string]$PreferredPath,
        $StatePayload
    )
    $explicitPath = Normalize-PathValue $PreferredPath
    if (-not [string]::IsNullOrWhiteSpace($explicitPath)) {
        if (-not (Test-Path -LiteralPath $explicitPath)) {
            throw "未找到指定的浏览器可执行文件：$explicitPath"
        }
        return New-CustomBrowserCandidate -ResolvedPath $explicitPath -Source "explicit_path"
    }

    $explicitPreferredKey = Normalize-BrowserKey $PreferredBrowser
    $preferredKey = $explicitPreferredKey
    if ([string]::IsNullOrWhiteSpace($preferredKey)) {
        $preferredKey = Normalize-BrowserKey ([string]$StatePayload.browser_key)
    }
    $stateBrowserPath = Normalize-PathValue ([string]$StatePayload.browser_path)
    $stateBrowserKey = Normalize-BrowserKey ([string]$StatePayload.browser_key)
    if (-not [string]::IsNullOrWhiteSpace($stateBrowserPath) -and (Test-Path -LiteralPath $stateBrowserPath)) {
        if ([string]::IsNullOrWhiteSpace($preferredKey) -or [string]::IsNullOrWhiteSpace($stateBrowserKey) -or $stateBrowserKey -eq $preferredKey) {
            return New-CustomBrowserCandidate -ResolvedPath $stateBrowserPath -Source "state_reuse" -BrowserName ([string]$StatePayload.browser_name)
        }
    }

    $installedCandidates = @(Get-InstalledBrowserCandidates)
    if (-not [string]::IsNullOrWhiteSpace($preferredKey)) {
        $preferredCandidate = $installedCandidates | Where-Object { $_.key -eq $preferredKey } | Select-Object -First 1
        if ($null -ne $preferredCandidate) {
            $preferredCandidate.source = if (-not [string]::IsNullOrWhiteSpace($stateBrowserKey)) { "state_key_preferred" } else { "preferred_browser" }
            return $preferredCandidate
        }
        if (-not [string]::IsNullOrWhiteSpace($explicitPreferredKey)) {
            throw "指定的浏览器未安装：$explicitPreferredKey"
        }
    }

    if ($installedCandidates.Count -gt 0) {
        $defaultCandidate = $installedCandidates[0]
        $defaultCandidate.source = "installed_default"
        return $defaultCandidate
    }

    $supportedNames = (Get-SupportedBrowsers | ForEach-Object { $_.name }) -join " / "
    throw "未找到可用的 Chromium 浏览器。建议先安装 Edge，再继续首次测试或后台自动生成。当前支持：$supportedNames"
}

function Resolve-ProfileDir {
    param(
        [string]$RequestedProfileDir,
        $StatePayload,
        $BrowserSelection
    )
    if (-not [string]::IsNullOrWhiteSpace($RequestedProfileDir)) {
        return Normalize-PathValue $RequestedProfileDir
    }

    $stateProfileDir = Normalize-PathValue ([string]$StatePayload.profile_dir)
    $stateBrowserPath = Normalize-PathValue ([string]$StatePayload.browser_path)
    $stateBrowserKey = Normalize-BrowserKey ([string]$StatePayload.browser_key)
    if (-not [string]::IsNullOrWhiteSpace($stateProfileDir)) {
        if (
            (-not [string]::IsNullOrWhiteSpace($stateBrowserPath) -and (Test-SamePath $stateBrowserPath $BrowserSelection.path)) -or
            (-not [string]::IsNullOrWhiteSpace($stateBrowserKey) -and $stateBrowserKey -eq $BrowserSelection.key) -or
            ([string]::IsNullOrWhiteSpace($stateBrowserKey) -and $BrowserSelection.key -eq "edge" -and ([System.IO.Path]::GetFileName($stateProfileDir).ToLowerInvariant() -eq "edge-profile"))
        ) {
            return $stateProfileDir
        }
    }

    $legacyEdgeProfileDir = Get-LegacyEdgeProfileDir
    if ($BrowserSelection.key -eq "edge" -and (Test-Path -LiteralPath $legacyEdgeProfileDir)) {
        return $legacyEdgeProfileDir
    }

    return Join-Path (Get-ProfilesRoot) $BrowserSelection.key
}

function Get-MatchingDebugProcess {
    param(
        [string]$ProcessName,
        [string]$ProfileDir,
        [int]$Port
    )
    return Get-CimInstance Win32_Process -Filter ("name='{0}'" -f $ProcessName) |
        Where-Object {
            $_.CommandLine -match [regex]::Escape("--remote-debugging-port=$Port") -and
            $_.CommandLine -match [regex]::Escape($ProfileDir)
        } |
        Select-Object -First 1
}

function Test-PortInUse {
    param([int]$Port)
    try {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
        $listener.Start()
        $listener.Stop()
        return $false
    }
    catch {
        return $true
    }
}

function Resolve-DebugPort {
    param(
        [string]$RequestedPort,
        [string]$ResolvedProfileDir,
        $BrowserSelection,
        $StatePayload
    )

    $basePort = 9230
    try {
        if (-not [string]::IsNullOrWhiteSpace($RequestedPort)) {
            $basePort = [int]$RequestedPort
        }
    }
    catch {
        $basePort = 9230
    }

    $candidatePorts = New-Object System.Collections.Generic.List[int]
    $seenPorts = @{}

    function Add-PortCandidate {
        param([int]$PortValue)
        if ($PortValue -le 0) {
            return
        }
        $key = [string]$PortValue
        if ($seenPorts.ContainsKey($key)) {
            return
        }
        $seenPorts[$key] = $true
        [void]$candidatePorts.Add($PortValue)
    }

    $statePort = 0
    try {
        $statePort = [int]$StatePayload.port
    }
    catch {
        $statePort = 0
    }

    $stateProfileDir = Normalize-PathValue ([string]$StatePayload.profile_dir)
    $stateBrowserKey = Normalize-BrowserKey ([string]$StatePayload.browser_key)
    $stateBrowserPath = Normalize-PathValue ([string]$StatePayload.browser_path)
    $stateMatchesSelection = (
        (-not [string]::IsNullOrWhiteSpace($stateProfileDir) -and (Test-SamePath $stateProfileDir $ResolvedProfileDir)) -and (
            ((-not [string]::IsNullOrWhiteSpace($stateBrowserPath)) -and (Test-SamePath $stateBrowserPath $BrowserSelection.path)) -or
            ((-not [string]::IsNullOrWhiteSpace($stateBrowserKey)) -and $stateBrowserKey -eq $BrowserSelection.key)
        )
    )
    if ($stateMatchesSelection) {
        Add-PortCandidate -PortValue $statePort
    }

    Add-PortCandidate -PortValue $basePort
    foreach ($offset in 1..20) {
        Add-PortCandidate -PortValue ($basePort + $offset)
    }

    foreach ($candidatePort in $candidatePorts) {
        $existing = Get-MatchingDebugProcess -ProcessName $BrowserSelection.process_name -ProfileDir $ResolvedProfileDir -Port $candidatePort
        if ($null -ne $existing) {
            return [PSCustomObject]@{
                port     = $candidatePort
                existing = $existing
            }
        }
        if (-not (Test-PortInUse -Port $candidatePort)) {
            return [PSCustomObject]@{
                port     = $candidatePort
                existing = $null
            }
        }
    }

    throw "No available isolated-browser debug port was found. Close conflicting debug instances and retry."
}

$statePath = Get-DefaultStatePath
$statePayload = Get-StatePayload -StatePath $statePath
$preferredPath = if (-not [string]::IsNullOrWhiteSpace($BrowserPath)) { $BrowserPath } else { $EdgePath }
$browserSelection = Resolve-BrowserSelection -PreferredBrowser $Browser -PreferredPath $preferredPath -StatePayload $statePayload
$resolvedProfileDir = Resolve-ProfileDir -RequestedProfileDir $ProfileDir -StatePayload $statePayload -BrowserSelection $browserSelection
$debugPortInfo = Resolve-DebugPort -RequestedPort $Port -ResolvedProfileDir $resolvedProfileDir -BrowserSelection $browserSelection -StatePayload $statePayload
$resolvedPort = [int]$debugPortInfo.port

if ($DetectOnly) {
    [PSCustomObject]@{
        ok                       = $true
        browser_detection_only   = $true
        browser_key              = $browserSelection.key
        browser_name             = $browserSelection.name
        browser_path             = $browserSelection.path
        browser_process_name     = $browserSelection.process_name
        browser_detection_source = $browserSelection.source
        profile_dir              = $resolvedProfileDir
        port                     = $resolvedPort
        state_path               = $statePath
    } | ConvertTo-Json -Depth 6
    exit 0
}

New-Item -ItemType Directory -Force -Path $resolvedProfileDir | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $statePath) | Out-Null

$existing = $debugPortInfo.existing

$launched = $false
if ($null -eq $existing) {
    $proc = Start-Process -FilePath $browserSelection.path -ArgumentList @(
        "--remote-debugging-port=$resolvedPort",
        "--user-data-dir=$resolvedProfileDir",
        "--new-window",
        $PageUrl
    ) -PassThru
    $pidValue = $proc.Id
    $launched = $true
}
else {
    $pidValue = [int]$existing.ProcessId
}

$timestamp = [DateTimeOffset]::Now.ToString("o")
$result = [PSCustomObject]@{
    ok                       = $true
    launched                 = $launched
    process_id               = $pidValue
    port                     = $resolvedPort
    profile_dir              = $resolvedProfileDir
    page_url                 = $PageUrl
    state_path               = $statePath
    browser_key              = $browserSelection.key
    browser_name             = $browserSelection.name
    browser_path             = $browserSelection.path
    browser_process_name     = $browserSelection.process_name
    browser_detection_source = $browserSelection.source
    last_seen_at             = $timestamp
    updated_at               = $timestamp
}

$result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $statePath -Encoding UTF8

$json = $result | ConvertTo-Json -Depth 6
if (-not [string]::IsNullOrWhiteSpace($OutputFile)) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputFile) | Out-Null
    Set-Content -LiteralPath $OutputFile -Value ($json + [Environment]::NewLine) -Encoding UTF8
}

$json
