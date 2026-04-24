param(
    [string]$Prompt,
    [string]$PromptContains = "",
    [string]$WindowHandle = "",
    [string]$TaskFile = "",
    [string]$OutputFile = "",
    [int]$StartTimeoutSec = 45,
    [int]$CompleteTimeoutSec = 300,
    [int]$PollIntervalMs = 1500,
    [int]$CompletionConfirmSec = 20,
    [int]$CompletionConfirmPolls = 2,
    [int]$PostCompleteSettleMs = 1200,
    [switch]$DisableCalibration,
    [string]$ScreenshotPath = ""
)

$ErrorActionPreference = "Stop"

function Get-ShellCommand {
    $powershellCommand = Get-Command powershell -ErrorAction SilentlyContinue
    if ($null -ne $powershellCommand) {
        return $powershellCommand.Source
    }
    $pwshCommand = Get-Command pwsh -ErrorAction SilentlyContinue
    if ($null -ne $pwshCommand) {
        return $pwshCommand.Source
    }
    throw "No available PowerShell runtime was found"
}

$script:ShellCommand = Get-ShellCommand

function Invoke-JsonScript {
    param(
        [string]$ScriptPath,
        [string[]]$Arguments = @()
    )

    $command = @(
        "-ExecutionPolicy", "Bypass",
        "-File", $ScriptPath
    ) + $Arguments

    try {
        $output = & $script:ShellCommand @command 2>&1
    }
    catch {
        $message = $_.Exception.Message
        throw "Script failed: $ScriptPath`n$message"
    }

    if ($LASTEXITCODE -ne 0) {
        $message = ($output | Out-String).Trim()
        throw "Script failed: $ScriptPath`n$message"
    }

    $jsonText = ($output | Out-String).Trim()
    if ([string]::IsNullOrWhiteSpace($jsonText)) {
        throw "Script returned empty output: $ScriptPath"
    }

    try {
        return $jsonText | ConvertFrom-Json
    }
    catch {
        throw "Script returned invalid JSON: $ScriptPath`n$jsonText"
    }
}

function Load-TaskPayload {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $null
    }
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Task file not found: $Path"
    }

    $content = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    if ([string]::IsNullOrWhiteSpace($content)) {
        throw "Task file is empty: $Path"
    }

    try {
        return $content | ConvertFrom-Json
    }
    catch {
        throw "Task file is not valid JSON: $Path"
    }
}

function Write-Result {
    param(
        [hashtable]$Payload
    )

    foreach ($key in $script:TaskMetadata.Keys) {
        if (-not $Payload.ContainsKey($key)) {
            $Payload[$key] = $script:TaskMetadata[$key]
        }
    }

    $json = ([PSCustomObject]$Payload) | ConvertTo-Json -Depth 10
    if ([string]::IsNullOrWhiteSpace($OutputFile)) {
        $json
        return
    }

    $directory = Split-Path -Path $OutputFile -Parent
    if (-not [string]::IsNullOrWhiteSpace($directory)) {
        New-Item -ItemType Directory -Force -Path $directory | Out-Null
    }
    Set-Content -LiteralPath $OutputFile -Value ($json + [Environment]::NewLine) -Encoding UTF8
    $json
}

function Get-ProbeNeedle {
    param([string]$SourcePrompt)
    $base = ($SourcePrompt -split "\s--")[0]
    $normalized = ($base -replace "\s+", " ").Trim()
    if ($normalized.Length -gt 96) {
        return $normalized.Substring(0, 96).Trim()
    }
    return $normalized
}

function Get-RegionStatePriority {
    param(
        [string]$State
    )

    switch ($State) {
        "generating" { return 0 }
        "submitting" { return 1 }
        "completed" { return 2 }
        default { return 99 }
    }
}

function Select-TargetRegion {
    param(
        $Probe,
        [string[]]$BaselineRegionKeys,
        [string]$LockedRegionKey
    )

    $regions = @($Probe.regions)
    if ($null -eq $regions -or $regions.Count -eq 0) {
        return $null
    }

    if (-not [string]::IsNullOrWhiteSpace($LockedRegionKey)) {
        return @($regions | Where-Object { [string]$_.region_key -eq $LockedRegionKey } | Select-Object -First 1)[0]
    }

    $baselineLookup = @{}
    foreach ($key in @($BaselineRegionKeys)) {
        if (-not [string]::IsNullOrWhiteSpace([string]$key)) {
            $baselineLookup[[string]$key] = $true
        }
    }

    $newRegions = @(
        $regions |
            Where-Object { -not $baselineLookup.ContainsKey([string]$_.region_key) } |
            Sort-Object `
                @{ Expression = { Get-RegionStatePriority -State ([string]$_.region_state) } }, `
                @{ Expression = { [double]$_.region_bounds.top } }, `
                @{ Expression = { -([int]$_.score) } }
    )

    if ($newRegions.Count -gt 0) {
        return $newRegions[0]
    }

    if ($baselineLookup.Count -eq 0) {
        return @(
            $regions |
                Sort-Object `
                    @{ Expression = { Get-RegionStatePriority -State ([string]$_.region_state) } }, `
                    @{ Expression = { [double]$_.region_bounds.top } }, `
                    @{ Expression = { -([int]$_.score) } } |
                Select-Object -First 1
        )[0]
    }

    return $null
}

function Test-TargetRegionCompleted {
    param($Region)

    if ($null -eq $Region) {
        return $false
    }

    return ([string]$Region.region_state -eq "completed" -and [int]$Region.region_image_count -gt 0)
}

function Add-StatusTransition {
    param(
        [System.Collections.Generic.List[string]]$Transitions,
        [string]$Status
    )

    if ([string]::IsNullOrWhiteSpace($Status)) {
        return
    }

    if ($Transitions.Count -eq 0 -or $Transitions[$Transitions.Count - 1] -ne $Status) {
        $Transitions.Add($Status)
    }
}

function New-ProbeSnapshot {
    param(
        $Probe,
        $TargetRegion = $null
    )

    return [PSCustomObject]@{
        at = (Get-Date).ToString("o")
        status = [string]$Probe.status
        matched_prompt_count = [int]$Probe.matched_prompt_count
        matched_progress_count = [int]$Probe.matched_progress_count
        max_prompt_index = [int]$Probe.max_prompt_index
        max_progress_index = [int]$Probe.max_progress_index
        target_region_key = if ($null -ne $TargetRegion) { [string]$TargetRegion.region_key } else { "" }
        target_region_state = if ($null -ne $TargetRegion) { [string]$TargetRegion.region_state } else { "" }
        target_region_image_count = if ($null -ne $TargetRegion) { [int]$TargetRegion.region_image_count } else { 0 }
    }
}

$scriptsRoot = $PSScriptRoot
$browserPreflightScript = Join-Path $scriptsRoot "browser_preflight.ps1"
$windowStateProbeScript = Join-Path $scriptsRoot "window_state_probe.ps1"
$windowControlGateScript = Join-Path $scriptsRoot "window_control_gate.ps1"
$submitScript = Join-Path $scriptsRoot "midjourney_visible_window_submit.ps1"
$statusProbeScript = Join-Path $scriptsRoot "midjourney_status_probe.ps1"
$captureScript = Join-Path $scriptsRoot "midjourney_window_capture.ps1"

$taskPayload = Load-TaskPayload -Path $TaskFile
$promptSource = ""
if ($null -ne $taskPayload) {
    if ([string]::IsNullOrWhiteSpace($Prompt)) {
        if ($null -ne $taskPayload.prompt_package -and -not [string]::IsNullOrWhiteSpace([string]$taskPayload.prompt_package.prompt_text)) {
            $Prompt = [string]$taskPayload.prompt_package.prompt_text
            $promptSource = "prompt_package"
        }
        elseif (-not [string]::IsNullOrWhiteSpace([string]$taskPayload.current_prompt)) {
            $Prompt = [string]$taskPayload.current_prompt
            $promptSource = "current_prompt"
        }
    }
    elseif ([string]::IsNullOrWhiteSpace($promptSource)) {
        $promptSource = "cli_argument"
    }
    if ([string]::IsNullOrWhiteSpace($PromptContains) -and $null -ne $taskPayload.artifacts) {
        $PromptContains = [string]$taskPayload.artifacts.prompt_contains
    }
    if ([string]::IsNullOrWhiteSpace($WindowHandle) -and $null -ne $taskPayload.ui_state) {
        $WindowHandle = [string]$taskPayload.ui_state.window_handle
    }
    if ([string]::IsNullOrWhiteSpace($WindowHandle) -and $null -ne $taskPayload.artifacts) {
        $WindowHandle = [string]$taskPayload.artifacts.window_handle
    }
}
elseif (-not [string]::IsNullOrWhiteSpace($Prompt)) {
    $promptSource = "cli_argument"
}

if ([string]::IsNullOrWhiteSpace($promptSource) -and -not [string]::IsNullOrWhiteSpace($Prompt)) {
    $promptSource = "current_prompt"
}

if ([string]::IsNullOrWhiteSpace($Prompt)) {
    throw "-Prompt is required"
}

$hasCjkPrompt = [regex]::IsMatch($Prompt, "[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]")
$hasLatinPrompt = [regex]::IsMatch($Prompt, "[A-Za-z]")
if ($hasCjkPrompt -or -not $hasLatinPrompt) {
    Write-Result -Payload @{
        ok = $false
        blocked_by_context = $true
        blocked_reason = "english_prompt_required"
        result_available = $false
        probe_needle = ""
    }
    exit 0
}

$script:TaskMetadata = @{
    task_id = if ($null -ne $taskPayload) { [string]$taskPayload.task_id } else { "" }
    project_id = if ($null -ne $taskPayload) { [string]$taskPayload.project_id } else { "" }
    mode = if ($null -ne $taskPayload) { [string]$taskPayload.mode } else { "" }
    round_index = if ($null -ne $taskPayload) { [int]$taskPayload.round_index } else { 0 }
    task_phase = if ($null -ne $taskPayload) { [string]$taskPayload.task_phase } else { "" }
    prompt_source = $promptSource
}

$probeNeedle = if ([string]::IsNullOrWhiteSpace($PromptContains)) {
    Get-ProbeNeedle -SourcePrompt $Prompt
}
else {
    ($PromptContains -replace "\s+", " ").Trim()
}

if ([string]::IsNullOrWhiteSpace($probeNeedle)) {
    throw "Cannot derive probe text from -Prompt"
}

$preflight = Invoke-JsonScript -ScriptPath $browserPreflightScript
if ([string]::IsNullOrWhiteSpace($WindowHandle)) {
    if (-not $preflight.candidate_found -or $null -eq $preflight.candidate) {
        Write-Result -Payload @{
            ok = $false
            blocked_by_ui = $true
            blocked_reason = "midjourney_window_not_found"
            result_available = $false
            probe_needle = $probeNeedle
            preflight = $preflight
        }
        exit 0
    }
    $WindowHandle = [string]$preflight.candidate.window_handle
}

$windowState = Invoke-JsonScript -ScriptPath $windowStateProbeScript -Arguments @(
    "-WindowHandle", $WindowHandle
)
$gate = Invoke-JsonScript -ScriptPath $windowControlGateScript -Arguments @(
    "-WindowHandle", $WindowHandle
)

if (-not $gate.ok -or (-not $gate.can_direct_input -and -not $gate.can_activate_by_click)) {
    Write-Result -Payload @{
        ok = $false
        blocked_by_ui = $true
        blocked_reason = if ($gate.blocked_reason) { $gate.blocked_reason } else { "window_gate_blocked" }
        result_available = $false
        probe_needle = $probeNeedle
        preflight = $preflight
        window_state = $windowState
        gate = $gate
    }
    exit 0
}

$baselineProbe = Invoke-JsonScript -ScriptPath $statusProbeScript -Arguments @(
    "-WindowHandle", $WindowHandle,
    "-PromptContains", $probeNeedle
)

$baselineRegionKeys = @($baselineProbe.region_keys | ForEach-Object { [string]$_ })
$statusTransitions = New-Object 'System.Collections.Generic.List[string]'
$probeTimeline = New-Object System.Collections.ArrayList
[void]$probeTimeline.Add((New-ProbeSnapshot -Probe $baselineProbe))
Add-StatusTransition -Transitions $statusTransitions -Status ([string]$baselineProbe.status)

$submitArgs = @(
    "-WindowHandle", $WindowHandle,
    "-Prompt", $Prompt
)
if ($DisableCalibration) {
    $submitArgs += "-DisableCalibration"
}
$submitResult = Invoke-JsonScript -ScriptPath $submitScript -Arguments $submitArgs

$startObserved = $false
$generationObserved = $false
$completedObserved = $false
$startProbe = $null
$completeProbe = $null
$newPromptSeenAt = $null
$completedWithoutGenerationCount = 0
$calibrationSaved = $false
$statusProbeFallbackNeeded = $false
$statusProbeFailure = ""
$lockedRegionKey = ""
$lockedRegion = $null
$finalTargetRegion = $null
$startDeadline = (Get-Date).AddSeconds($StartTimeoutSec)

while ((Get-Date) -lt $startDeadline) {
    Start-Sleep -Milliseconds $PollIntervalMs
    try {
        $probe = Invoke-JsonScript -ScriptPath $statusProbeScript -Arguments @(
            "-WindowHandle", $WindowHandle,
            "-PromptContains", $probeNeedle
        )
    }
    catch {
        $statusProbeFallbackNeeded = $true
        $statusProbeFailure = $_.Exception.Message
        break
    }

    $targetRegion = Select-TargetRegion -Probe $probe -BaselineRegionKeys $baselineRegionKeys -LockedRegionKey $lockedRegionKey
    if ($null -ne $targetRegion -and [string]::IsNullOrWhiteSpace($lockedRegionKey)) {
        $lockedRegionKey = [string]$targetRegion.region_key
        $lockedRegion = $targetRegion
        $finalTargetRegion = $targetRegion
    }
    elseif ($null -ne $targetRegion) {
        $lockedRegion = $targetRegion
        $finalTargetRegion = $targetRegion
    }

    [void]$probeTimeline.Add((New-ProbeSnapshot -Probe $probe -TargetRegion $targetRegion))
    Add-StatusTransition -Transitions $statusTransitions -Status (if ($null -ne $targetRegion) { [string]$targetRegion.region_state } else { [string]$probe.status })

    if ($null -eq $targetRegion) {
        continue
    }

    if (-not $startObserved) {
        $startObserved = $true
        $newPromptSeenAt = Get-Date
        $startProbe = $probe
    }

    if ([string]$targetRegion.region_state -eq "generating") {
        $generationObserved = $true
        $completedWithoutGenerationCount = 0
        break
    }

    if (Test-TargetRegionCompleted -Region $targetRegion) {
        $completedWithoutGenerationCount += 1
        $readyToConfirm = $false
        if ($generationObserved) {
            $readyToConfirm = $true
        }
        elseif ($null -ne $newPromptSeenAt) {
            $elapsedSinceSeen = ((Get-Date) - $newPromptSeenAt).TotalSeconds
            if ($elapsedSinceSeen -ge $CompletionConfirmSec -and $completedWithoutGenerationCount -ge $CompletionConfirmPolls) {
                $readyToConfirm = $true
            }
        }

        if ($readyToConfirm) {
            $completedObserved = $true
            $completeProbe = $probe
            break
        }
    }
    else {
        $completedWithoutGenerationCount = 0
    }
}

if (($generationObserved -or $completedObserved) -and -not $DisableCalibration -and -not $submitResult.calibration_hit) {
    $saveArgs = @(
        "-WindowHandle", $WindowHandle,
        "-Prompt", $Prompt,
        "-DryRun",
        "-SaveCalibration"
    )
    [void](Invoke-JsonScript -ScriptPath $submitScript -Arguments $saveArgs)
    $calibrationSaved = $true
}

if (-not $startObserved -and -not $statusProbeFallbackNeeded) {
    $statusProbeFallbackNeeded = $true
    $statusProbeFailure = "start_timeout"
}

if ($startObserved -and -not $completedObserved) {
    $completeDeadline = (Get-Date).AddSeconds($CompleteTimeoutSec)
    while ((Get-Date) -lt $completeDeadline) {
        Start-Sleep -Milliseconds $PollIntervalMs
        try {
            $probe = Invoke-JsonScript -ScriptPath $statusProbeScript -Arguments @(
                "-WindowHandle", $WindowHandle,
                "-PromptContains", $probeNeedle
            )
        }
        catch {
            $statusProbeFallbackNeeded = $true
            $statusProbeFailure = $_.Exception.Message
            break
        }

        $targetRegion = Select-TargetRegion -Probe $probe -BaselineRegionKeys $baselineRegionKeys -LockedRegionKey $lockedRegionKey
        if ($null -ne $targetRegion) {
            $lockedRegion = $targetRegion
            $finalTargetRegion = $targetRegion
            if ([string]::IsNullOrWhiteSpace($lockedRegionKey)) {
                $lockedRegionKey = [string]$targetRegion.region_key
            }
        }

        [void]$probeTimeline.Add((New-ProbeSnapshot -Probe $probe -TargetRegion $targetRegion))
        Add-StatusTransition -Transitions $statusTransitions -Status (if ($null -ne $targetRegion) { [string]$targetRegion.region_state } else { [string]$probe.status })

        if ($null -eq $targetRegion) {
            continue
        }

        if (-not $startObserved) {
            $startObserved = $true
            $newPromptSeenAt = Get-Date
            $startProbe = $probe
        }

        if ([string]$targetRegion.region_state -eq "generating") {
            $generationObserved = $true
            $completedWithoutGenerationCount = 0
            continue
        }

        if (Test-TargetRegionCompleted -Region $targetRegion) {
            $completedWithoutGenerationCount += 1
            $readyToConfirm = $false
            if ($generationObserved) {
                $readyToConfirm = $true
            }
            elseif ($null -ne $newPromptSeenAt) {
                $elapsedSinceSeen = ((Get-Date) - $newPromptSeenAt).TotalSeconds
                if ($elapsedSinceSeen -ge $CompletionConfirmSec -and $completedWithoutGenerationCount -ge $CompletionConfirmPolls) {
                    $readyToConfirm = $true
                }
            }

            if ($readyToConfirm) {
                $completedObserved = $true
                $completeProbe = $probe
                break
            }
        }
        else {
            $completedWithoutGenerationCount = 0
        }
    }

    if (-not $completedObserved -and -not $statusProbeFallbackNeeded) {
        $statusProbeFallbackNeeded = $true
        $statusProbeFailure = "complete_timeout"
    }
}

$captureResult = $null
if ($completedObserved) {
    if ($PostCompleteSettleMs -gt 0) {
        Start-Sleep -Milliseconds $PostCompleteSettleMs
    }

    $captureArgs = @("-WindowHandle", $WindowHandle)
    if ($null -ne $finalTargetRegion -and $null -ne $finalTargetRegion.region_bounds) {
        $captureArgs += @(
            "-CropLeft", ([string]$finalTargetRegion.region_bounds.left),
            "-CropTop", ([string]$finalTargetRegion.region_bounds.top),
            "-CropWidth", ([string]$finalTargetRegion.region_bounds.width),
            "-CropHeight", ([string]$finalTargetRegion.region_bounds.height)
        )
    }
    if (-not [string]::IsNullOrWhiteSpace($ScreenshotPath)) {
        $captureArgs += @("-OutputPath", $ScreenshotPath)
    }
    $captureResult = Invoke-JsonScript -ScriptPath $captureScript -Arguments $captureArgs
}

Write-Result -Payload @{
    ok = ($completedObserved -and -not $statusProbeFallbackNeeded)
    blocked_by_ui = (-not $completedObserved)
    blocked_reason = if ($statusProbeFallbackNeeded) { $statusProbeFailure } else { "" }
    formal_flow_version = "uia_prompt_region_v2"
    probe_needle = $probeNeedle
    result_available = $completedObserved
    should_continue = $false
    started_generating = $startObserved
    generation_observed = $generationObserved
    completed = $completedObserved
    status_probe_fallback_needed = $statusProbeFallbackNeeded
    calibration_saved = $calibrationSaved
    baseline_region_keys = $baselineRegionKeys
    target_region_key = $lockedRegionKey
    target_region = $finalTargetRegion
    preflight = $preflight
    window_state = $windowState
    gate = $gate
    baseline_probe = $baselineProbe
    submit_result = $submitResult
    start_probe = $startProbe
    complete_probe = $completeProbe
    status_transitions = @($statusTransitions)
    probe_timeline = @($probeTimeline)
    final_capture = $captureResult
}
