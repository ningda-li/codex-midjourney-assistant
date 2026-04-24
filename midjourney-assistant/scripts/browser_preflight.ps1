param(
    [string[]]$ProcessNames = @("msedge", "chrome", "brave", "vivaldi", "arc"),
    [string]$TitlePattern = "Midjourney"
)

$ErrorActionPreference = "Stop"

Add-Type @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

public static class Win32Bridge {
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern bool IsWindowVisible(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern int GetWindowTextLength(IntPtr hWnd);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);

    [DllImport("user32.dll")]
    public static extern bool GetWindowPlacement(IntPtr hWnd, ref WINDOWPLACEMENT lpwndpl);

    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);

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
    $placement = New-Object Win32Bridge+WINDOWPLACEMENT
    $placement.length = [System.Runtime.InteropServices.Marshal]::SizeOf($placement)
    [void][Win32Bridge]::GetWindowPlacement($Handle, [ref]$placement)
    switch ($placement.showCmd) {
        2 { "minimized" }
        3 { "maximized" }
        default { "normal" }
    }
}

function Get-WindowTitle {
    param([IntPtr]$Handle)
    $length = [Win32Bridge]::GetWindowTextLength($Handle)
    if ($length -le 0) {
        return ""
    }

    $builder = New-Object System.Text.StringBuilder ($length + 1)
    [void][Win32Bridge]::GetWindowText($Handle, $builder, $builder.Capacity)
    return $builder.ToString()
}

function Get-SiteRoute {
    param([string]$Title)
    $lower = $Title.ToLowerInvariant()
    if ($lower -match "alpha" -or $lower -match "v8") {
        return "alpha.midjourney.com"
    }
    if ($lower -match "midjourney") {
        return "midjourney.com"
    }
    return "unknown"
}

function Get-VersionRoute {
    param([string]$Title)
    $lower = $Title.ToLowerInvariant()
    if ($lower -match "alpha" -or $lower -match "v8") {
        return "v8-1-alpha"
    }
    if ($lower -match "midjourney") {
        return "v7-main-site"
    }
    return "unknown"
}

function Test-IsIgnoredWindowTitle {
    param([string]$Title)
    return $Title -in @("Default IME", "MSCTFIME UI", "Sogou_TSF_UI", "HintWnd")
}

function Test-IsCandidateWindow {
    param([string]$Title, [string]$Pattern)
    if ($Title -match $Pattern -or $Title -match "Midjourney") {
        return $true
    }

    if ($Title -match '^(Create|Imagine|Explore)(\b|[^A-Za-z0-9_])') {
        return $true
    }

    return $false
}

$targetProcesses = @{}
foreach ($proc in Get-Process -Name $ProcessNames -ErrorAction SilentlyContinue) {
    $targetProcesses[[uint32]$proc.Id] = $proc
}

$windows = New-Object System.Collections.Generic.List[object]
$foregroundHandle = [Win32Bridge]::GetForegroundWindow()
$foregroundProcessId = 0
if ($foregroundHandle -ne [IntPtr]::Zero) {
    [void][Win32Bridge]::GetWindowThreadProcessId($foregroundHandle, [ref]$foregroundProcessId)
}

$enumCallback = [Win32Bridge+EnumWindowsProc]{
    param([IntPtr]$Handle, [IntPtr]$LParam)

    $processId = 0
    [void][Win32Bridge]::GetWindowThreadProcessId($Handle, [ref]$processId)
    if (-not $targetProcesses.ContainsKey([uint32]$processId)) {
        return $true
    }

    $title = Get-WindowTitle -Handle $Handle
    if ([string]::IsNullOrWhiteSpace($title)) {
        return $true
    }

    if (Test-IsIgnoredWindowTitle -Title $title) {
        return $true
    }

    $visible = [Win32Bridge]::IsWindowVisible($Handle)
    $state = Get-ShowState -Handle $Handle
    $isCandidate = Test-IsCandidateWindow -Title $title -Pattern $TitlePattern
    $proc = $targetProcesses[[uint32]$processId]

    $windows.Add([PSCustomObject]@{
        process_name   = $proc.ProcessName
        process_id     = $proc.Id
        title          = $title
        window_handle  = ("0x{0:X}" -f $Handle.ToInt64())
        main_handle    = ("0x{0:X}" -f $proc.MainWindowHandle)
        is_visible     = $visible
        show_state     = $state
        is_foreground  = ($Handle -eq $foregroundHandle)
        site_route     = Get-SiteRoute -Title $title
        version_route  = Get-VersionRoute -Title $title
        is_candidate   = $isCandidate
        started_at     = $proc.StartTime
    }) | Out-Null

    return $true
}

[void][Win32Bridge]::EnumWindows($enumCallback, [IntPtr]::Zero)

$windowList = $windows | Sort-Object -Property @{ Expression = "is_candidate"; Descending = $true }, @{ Expression = "is_foreground"; Descending = $true }, @{ Expression = "is_visible"; Descending = $true }, @{ Expression = "process_id"; Descending = $false }
$candidate = $windowList | Where-Object { $_.is_candidate } | Select-Object -First 1

$result = [PSCustomObject]@{
    ok                    = $true
    process_names         = $ProcessNames
    title_pattern         = $TitlePattern
    browser_found         = ($targetProcesses.Count -gt 0)
    window_found          = ($windowList.Count -gt 0)
    candidate_found       = ($null -ne $candidate)
    foreground_process_id = $foregroundProcessId
    candidate             = $candidate
    windows               = $windowList
}

$result | ConvertTo-Json -Depth 6
