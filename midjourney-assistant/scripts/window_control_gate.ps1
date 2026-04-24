param(
    [int]$ProcessId = 0,
    [string]$WindowHandle = ""
)

$ErrorActionPreference = "Stop"

Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;

public static class Win32Gate {
    [DllImport("user32.dll")]
    public static extern bool IsWindowVisible(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern bool GetWindowPlacement(IntPtr hWnd, ref WINDOWPLACEMENT lpwndpl);

    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);

    [DllImport("user32.dll")]
    public static extern int GetWindowTextLength(IntPtr hWnd);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);

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

function Get-ShowState {
    param([IntPtr]$Handle)
    $placement = New-Object Win32Gate+WINDOWPLACEMENT
    $placement.length = [System.Runtime.InteropServices.Marshal]::SizeOf($placement)
    [void][Win32Gate]::GetWindowPlacement($Handle, [ref]$placement)
    switch ($placement.showCmd) {
        2 { "minimized" }
        3 { "maximized" }
        default { "normal" }
    }
}

function Get-WindowTitle {
    param([IntPtr]$Handle)
    $length = [Win32Gate]::GetWindowTextLength($Handle)
    if ($length -le 0) {
        return ""
    }

    $builder = New-Object System.Text.StringBuilder ($length + 1)
    [void][Win32Gate]::GetWindowText($Handle, $builder, $builder.Capacity)
    return $builder.ToString()
}

function Convert-ToWindowHandle {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return [IntPtr]::Zero
    }

    if ($Value.StartsWith("0x")) {
        return [IntPtr]([Convert]::ToInt64($Value, 16))
    }

    return [IntPtr]([Convert]::ToInt64($Value))
}

$handle = [IntPtr]::Zero
$proc = $null

if (-not [string]::IsNullOrWhiteSpace($WindowHandle)) {
    $handle = Convert-ToWindowHandle -Value $WindowHandle
    $resolvedProcessId = 0
    [void][Win32Gate]::GetWindowThreadProcessId($handle, [ref]$resolvedProcessId)
    if ($resolvedProcessId -eq 0) {
        [PSCustomObject]@{
            ok = $false
            process_id = 0
            can_direct_input = $false
            can_activate_by_click = $false
            blocked_reason = "invalid_window_handle"
            requires_manual_foreground = $false
            hard_rules = @(
                "forbid_showwindow_restore",
                "forbid_window_shape_change",
                "forbid_inline_win32_focus_hack"
            )
        } | ConvertTo-Json -Depth 6
        exit 0
    }
    $proc = Get-Process -Id $resolvedProcessId -ErrorAction Stop
}
elseif ($ProcessId -ne 0) {
    $proc = Get-Process -Id $ProcessId -ErrorAction Stop
    $handle = [IntPtr]$proc.MainWindowHandle
}
else {
    throw "Either -ProcessId or -WindowHandle is required"
}

if ($handle -eq [IntPtr]::Zero) {
    [PSCustomObject]@{
        ok = $false
        process_id = if ($null -ne $proc) { $proc.Id } else { $ProcessId }
        can_direct_input = $false
        can_activate_by_click = $false
        blocked_reason = "no_window_handle"
        requires_manual_foreground = $false
        hard_rules = @(
            "forbid_showwindow_restore",
            "forbid_window_shape_change",
            "forbid_inline_win32_focus_hack"
        )
    } | ConvertTo-Json -Depth 6
    exit 0
}

$visible = [Win32Gate]::IsWindowVisible($handle)
$showState = Get-ShowState -Handle $handle
$foregroundHandle = [Win32Gate]::GetForegroundWindow()
$foregroundProcessId = 0
if ($foregroundHandle -ne [IntPtr]::Zero) {
    [void][Win32Gate]::GetWindowThreadProcessId($foregroundHandle, [ref]$foregroundProcessId)
}
$isForeground = ($handle -eq $foregroundHandle)
$windowTitle = Get-WindowTitle -Handle $handle

$blockedReason = ""
$requiresManualForeground = $false
$canDirectInput = $false
$canActivateByClick = $false
$activationMode = "blocked"

if (-not $visible) {
    $blockedReason = "window_not_visible"
    $activationMode = "blocked_not_visible"
}
elseif ($showState -eq "minimized") {
    $blockedReason = "window_minimized"
    $activationMode = "user_manual_restore"
}
elseif (-not $isForeground) {
    $blockedReason = "target_not_foreground"
    $canActivateByClick = $true
    $activationMode = "assistant_single_click_activate"
}
else {
    $canDirectInput = $true
    $activationMode = "direct_input"
}

[PSCustomObject]@{
    ok = $true
    process_id = $proc.Id
    process_name = $proc.ProcessName
    title = if ([string]::IsNullOrWhiteSpace($windowTitle)) { $proc.MainWindowTitle } else { $windowTitle }
    window_handle = ("0x{0:X}" -f $handle.ToInt64())
    main_handle = ("0x{0:X}" -f $proc.MainWindowHandle)
    is_visible = $visible
    show_state = $showState
    is_foreground = $isForeground
    foreground_process_id = $foregroundProcessId
    can_direct_input = $canDirectInput
    can_activate_by_click = $canActivateByClick
    activation_mode = $activationMode
    requires_manual_foreground = $requiresManualForeground
    blocked_reason = $blockedReason
    next_step = if ($canDirectInput) {
        "direct_input_allowed_but_shape_change_forbidden"
    }
    elseif ($canActivateByClick) {
        "single_safe_click_activation_allowed"
    }
    elseif ($blockedReason -eq "window_minimized") {
        "ask_user_to_restore_window_manually"
    }
    else {
        "fix_window_visibility_before_continue"
    }
    hard_rules = @(
        "forbid_showwindow_restore",
        "forbid_window_shape_change",
        "forbid_inline_win32_focus_hack",
        "allow_only_single_safe_click_for_visible_inactive_window"
    )
} | ConvertTo-Json -Depth 6
