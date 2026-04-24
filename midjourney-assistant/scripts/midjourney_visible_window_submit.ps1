param(
    [string]$WindowHandle,
    [string]$Prompt,
    [double]$InputXRatio = 0.5,
    [int]$InputTopOffset = 150,
    [switch]$ClearExisting,
    [switch]$NoEnter,
    [switch]$EnterOnly,
    [switch]$SkipClick,
    [switch]$SaveCalibration,
    [switch]$DisableCalibration,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($WindowHandle)) {
    throw "-WindowHandle is required"
}

if ($EnterOnly -and $NoEnter) {
    throw "-EnterOnly and -NoEnter cannot be used together"
}

if (-not $DryRun -and -not $EnterOnly -and [string]::IsNullOrWhiteSpace($Prompt)) {
    throw "-Prompt is required unless -DryRun is used"
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;

public static class Win32Submit {
    [DllImport("user32.dll")]
    public static extern bool IsWindowVisible(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern bool GetWindowPlacement(IntPtr hWnd, ref WINDOWPLACEMENT lpwndpl);

    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);

    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);

    [DllImport("user32.dll")]
    public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);

    public const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
    public const uint MOUSEEVENTF_LEFTUP = 0x0004;

    [StructLayout(LayoutKind.Sequential)]
    public struct POINT {
        public int X;
        public int Y;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct RECT {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct WINDOWPLACEMENT {
        public int length;
        public int flags;
        public int showCmd;
        public POINT ptMinPosition;
        public POINT ptMaxPosition;
        public RECT rcNormalPosition;
    }
}
"@

function Convert-ToWindowHandle {
    param([string]$Value)
    if ($Value.StartsWith("0x")) {
        return [IntPtr]([Convert]::ToInt64($Value, 16))
    }
    return [IntPtr]([Convert]::ToInt64($Value))
}

function Get-ShowState {
    param([IntPtr]$Handle)
    $placement = New-Object Win32Submit+WINDOWPLACEMENT
    $placement.length = [System.Runtime.InteropServices.Marshal]::SizeOf($placement)
    [void][Win32Submit]::GetWindowPlacement($Handle, [ref]$placement)
    switch ($placement.showCmd) {
        2 { "minimized" }
        3 { "maximized" }
        default { "normal" }
    }
}

function Get-CodexHome {
    $skillRoot = Split-Path -Parent $PSScriptRoot
    $skillsRoot = Split-Path -Parent $skillRoot
    return Split-Path -Parent $skillsRoot
}

function Get-CalibrationPath {
    $codexHome = Get-CodexHome
    return Join-Path $codexHome "memories\midjourney-assistant\input-calibrations.json"
}

function New-CalibrationKey {
    param(
        [string]$ProcessName,
        [string]$ShowState,
        [int]$Width,
        [int]$Height
    )
    return "{0}|{1}|{2}|{3}" -f $ProcessName.ToLowerInvariant(), $ShowState, $Width, $Height
}

function Read-CalibrationEntries {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return @()
    }

    try {
        $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
        if ([string]::IsNullOrWhiteSpace($raw)) {
            return @()
        }
        $parsed = $raw | ConvertFrom-Json
        if ($null -eq $parsed) {
            return @()
        }
        if ($parsed.entries) {
            return @($parsed.entries)
        }
        return @()
    }
    catch {
        return @()
    }
}

function Write-CalibrationEntry {
    param(
        [string]$Path,
        [string]$Key,
        [string]$ProcessName,
        [string]$ShowState,
        [int]$Width,
        [int]$Height,
        [double]$XRatio,
        [int]$TopOffset
    )

    $entries = @(Read-CalibrationEntries -Path $Path | Where-Object { $_.key -ne $Key })
    $entries += [PSCustomObject]@{
        key              = $Key
        process_name     = $ProcessName
        show_state       = $ShowState
        window_width     = $Width
        window_height    = $Height
        input_x_ratio    = $XRatio
        input_top_offset = $TopOffset
        verified_at      = (Get-Date).ToString("o")
    }

    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }

    [PSCustomObject]@{
        entries = $entries
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $Path -Encoding UTF8
}

$handle = Convert-ToWindowHandle -Value $WindowHandle
$resolvedProcessId = 0
[void][Win32Submit]::GetWindowThreadProcessId($handle, [ref]$resolvedProcessId)
if ($resolvedProcessId -eq 0) {
    throw "Cannot resolve process from -WindowHandle"
}
$proc = Get-Process -Id $resolvedProcessId -ErrorAction Stop

$visible = [Win32Submit]::IsWindowVisible($handle)
$showState = Get-ShowState -Handle $handle
if (-not $visible) {
    throw "Target window is not visible"
}
if ($showState -eq "minimized") {
    throw "Target window is minimized"
}

$rect = New-Object Win32Submit+RECT
if (-not [Win32Submit]::GetWindowRect($handle, [ref]$rect)) {
    throw "Cannot read window rect"
}

$width = $rect.Right - $rect.Left
$height = $rect.Bottom - $rect.Top
if ($width -le 0 -or $height -le 0) {
    throw "Invalid window rect"
}

$calibrationPath = Get-CalibrationPath
$calibrationKey = New-CalibrationKey -ProcessName $proc.ProcessName -ShowState $showState -Width $width -Height $height
$calibrationEntry = $null
$calibrationHit = $false
$pointStrategy = "parametric_default"

if (-not $DisableCalibration) {
    $calibrationEntry = Read-CalibrationEntries -Path $calibrationPath | Where-Object { $_.key -eq $calibrationKey } | Select-Object -First 1
    if ($null -ne $calibrationEntry) {
        $InputXRatio = [double]$calibrationEntry.input_x_ratio
        $InputTopOffset = [int]$calibrationEntry.input_top_offset
        $calibrationHit = $true
        $pointStrategy = "cached_calibration"
    }
}

$targetX = [int]($rect.Left + ($width * $InputXRatio))
$resolvedTopOffset = [Math]::Min([Math]::Max($InputTopOffset, 90), [Math]::Max($height - 40, 90))
$targetY = [int]($rect.Top + $resolvedTopOffset)
$currentPosition = [System.Windows.Forms.Cursor]::Position

$result = [ordered]@{
    ok = $true
    process_id = [int]$resolvedProcessId
    process_name = $proc.ProcessName
    window_handle = ("0x{0:X}" -f $handle.ToInt64())
    is_visible = $visible
    show_state = $showState
    window_width = $width
    window_height = $height
    click_point = @{
        x = $targetX
        y = $targetY
    }
    point_strategy = $pointStrategy
    calibration_key = $calibrationKey
    calibration_hit = $calibrationHit
    calibration_path = $calibrationPath
    input_x_ratio = $InputXRatio
    input_top_offset = $resolvedTopOffset
    used_clipboard = $false
    did_click = $false
    did_paste = $false
    did_press_enter = $false
    dry_run = [bool]$DryRun
}

if ($DryRun) {
    if ($SaveCalibration) {
        Write-CalibrationEntry -Path $calibrationPath -Key $calibrationKey -ProcessName $proc.ProcessName -ShowState $showState -Width $width -Height $height -XRatio $InputXRatio -TopOffset $resolvedTopOffset
        $result["calibration_saved"] = $true
    }
    [PSCustomObject]$result | ConvertTo-Json -Depth 6
    exit 0
}

$oldClipboard = $null
$clipboardReadOk = $false
try {
    $oldClipboard = Get-Clipboard -Raw -ErrorAction Stop
    $clipboardReadOk = $true
}
catch {
    $oldClipboard = $null
}

try {
    if (-not $SkipClick) {
        [System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point($targetX, $targetY)
        Start-Sleep -Milliseconds 120
        [Win32Submit]::mouse_event([Win32Submit]::MOUSEEVENTF_LEFTDOWN, 0, 0, 0, [UIntPtr]::Zero)
        [Win32Submit]::mouse_event([Win32Submit]::MOUSEEVENTF_LEFTUP, 0, 0, 0, [UIntPtr]::Zero)
        Start-Sleep -Milliseconds 250
        $result.did_click = $true
    }

    if (-not $EnterOnly) {
        if ($ClearExisting) {
            [System.Windows.Forms.SendKeys]::SendWait("^a")
            Start-Sleep -Milliseconds 80
            [System.Windows.Forms.SendKeys]::SendWait("{BACKSPACE}")
            Start-Sleep -Milliseconds 120
        }

        Set-Clipboard -Value $Prompt
        $result.used_clipboard = $true
        Start-Sleep -Milliseconds 80
        [System.Windows.Forms.SendKeys]::SendWait("^v")
        Start-Sleep -Milliseconds 120
        $result.did_paste = $true
    }

    if (-not $NoEnter) {
        [System.Windows.Forms.SendKeys]::SendWait("{ENTER}")
        Start-Sleep -Milliseconds 120
        $result.did_press_enter = $true
    }
}
finally {
    [System.Windows.Forms.Cursor]::Position = $currentPosition
    if ($clipboardReadOk) {
        Set-Clipboard -Value $oldClipboard
    }
}

if ($SaveCalibration) {
    Write-CalibrationEntry -Path $calibrationPath -Key $calibrationKey -ProcessName $proc.ProcessName -ShowState $showState -Width $width -Height $height -XRatio $InputXRatio -TopOffset $resolvedTopOffset
    $result["calibration_saved"] = $true
}

[PSCustomObject]$result | ConvertTo-Json -Depth 6
