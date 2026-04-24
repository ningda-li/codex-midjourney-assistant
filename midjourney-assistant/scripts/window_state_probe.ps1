param(
    [int]$ProcessId = 0,
    [string]$WindowHandle = ""
)

$ErrorActionPreference = "Stop"

Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;

public static class Win32BridgeProbe {
    [DllImport("user32.dll")]
    public static extern bool IsWindowVisible(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern bool GetWindowPlacement(IntPtr hWnd, ref WINDOWPLACEMENT lpwndpl);

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
    $placement = New-Object Win32BridgeProbe+WINDOWPLACEMENT
    $placement.length = [System.Runtime.InteropServices.Marshal]::SizeOf($placement)
    [void][Win32BridgeProbe]::GetWindowPlacement($Handle, [ref]$placement)
    switch ($placement.showCmd) {
        2 { "minimized" }
        3 { "maximized" }
        default { "normal" }
    }
}

function Get-WindowTitle {
    param([IntPtr]$Handle)
    $length = [Win32BridgeProbe]::GetWindowTextLength($Handle)
    if ($length -le 0) {
        return ""
    }

    $builder = New-Object System.Text.StringBuilder ($length + 1)
    [void][Win32BridgeProbe]::GetWindowText($Handle, $builder, $builder.Capacity)
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
    [void][Win32BridgeProbe]::GetWindowThreadProcessId($handle, [ref]$resolvedProcessId)
    if ($resolvedProcessId -eq 0) {
        throw "Cannot resolve process from -WindowHandle"
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

$visible = $false
$state = "unknown"
$title = ""

if ($handle -ne [IntPtr]::Zero) {
    $visible = [Win32BridgeProbe]::IsWindowVisible($handle)
    $state = Get-ShowState -Handle $handle
    $title = Get-WindowTitle -Handle $handle
}

[PSCustomObject]@{
    process_name  = $proc.ProcessName
    process_id    = $proc.Id
    title         = if ([string]::IsNullOrWhiteSpace($title)) { $proc.MainWindowTitle } else { $title }
    window_handle = ("0x{0:X}" -f $handle.ToInt64())
    main_handle   = ("0x{0:X}" -f $proc.MainWindowHandle)
    is_visible    = $visible
    show_state    = $state
} | ConvertTo-Json -Depth 4
