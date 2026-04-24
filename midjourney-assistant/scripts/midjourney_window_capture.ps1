param(
    [string]$WindowHandle,
    [string]$OutputPath = "",
    [double]$CropLeft = 0,
    [double]$CropTop = 0,
    [double]$CropWidth = 0,
    [double]$CropHeight = 0
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($WindowHandle)) {
    throw "-WindowHandle is required"
}

Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;

public static class Win32Capture {
    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);

    [StructLayout(LayoutKind.Sequential)]
    public struct RECT {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
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

function New-DefaultOutputPath {
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $name = "midjourney-window-$timestamp.png"
    return Join-Path ([System.IO.Path]::GetTempPath()) $name
}

$handle = Convert-ToWindowHandle -Value $WindowHandle
$rect = New-Object Win32Capture+RECT
if (-not [Win32Capture]::GetWindowRect($handle, [ref]$rect)) {
    throw "Cannot read window rect"
}

$width = $rect.Right - $rect.Left
$height = $rect.Bottom - $rect.Top
if ($width -le 0 -or $height -le 0) {
    throw "Invalid window rect"
}

$targetPath = if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    New-DefaultOutputPath
}
else {
    $OutputPath
}

$parent = Split-Path -Parent $targetPath
if (-not [string]::IsNullOrWhiteSpace($parent) -and -not (Test-Path -LiteralPath $parent)) {
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
}

$bitmap = New-Object System.Drawing.Bitmap($width, $height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$finalBitmap = $bitmap
$cropApplied = $false
$cropBoundsRelative = $null
$cropBoundsScreen = $null
$outputWidth = $width
$outputHeight = $height
try {
    $graphics.CopyFromScreen($rect.Left, $rect.Top, 0, 0, $bitmap.Size)

    if ($CropWidth -gt 0 -and $CropHeight -gt 0) {
        $relativeLeft = [int][Math]::Round($CropLeft - $rect.Left)
        $relativeTop = [int][Math]::Round($CropTop - $rect.Top)
        $relativeRight = [int][Math]::Round(($CropLeft + $CropWidth) - $rect.Left)
        $relativeBottom = [int][Math]::Round(($CropTop + $CropHeight) - $rect.Top)

        $relativeLeft = [Math]::Max(0, [Math]::Min($relativeLeft, $width))
        $relativeTop = [Math]::Max(0, [Math]::Min($relativeTop, $height))
        $relativeRight = [Math]::Max($relativeLeft, [Math]::Min($relativeRight, $width))
        $relativeBottom = [Math]::Max($relativeTop, [Math]::Min($relativeBottom, $height))

        $clampedWidth = $relativeRight - $relativeLeft
        $clampedHeight = $relativeBottom - $relativeTop

        if ($clampedWidth -gt 0 -and $clampedHeight -gt 0) {
            $cropBitmap = New-Object System.Drawing.Bitmap($clampedWidth, $clampedHeight)
            $cropGraphics = [System.Drawing.Graphics]::FromImage($cropBitmap)
            try {
                $destinationRect = New-Object System.Drawing.Rectangle(0, 0, $clampedWidth, $clampedHeight)
                $sourceRect = New-Object System.Drawing.Rectangle($relativeLeft, $relativeTop, $clampedWidth, $clampedHeight)
                $cropGraphics.DrawImage($bitmap, $destinationRect, $sourceRect, [System.Drawing.GraphicsUnit]::Pixel)
            }
            finally {
                $cropGraphics.Dispose()
            }

            $finalBitmap = $cropBitmap
            $cropApplied = $true
            $outputWidth = $clampedWidth
            $outputHeight = $clampedHeight
            $cropBoundsRelative = [PSCustomObject]@{
                left = $relativeLeft
                top = $relativeTop
                width = $clampedWidth
                height = $clampedHeight
            }
            $cropBoundsScreen = [PSCustomObject]@{
                left = $rect.Left + $relativeLeft
                top = $rect.Top + $relativeTop
                width = $clampedWidth
                height = $clampedHeight
            }
        }
    }

    $finalBitmap.Save($targetPath, [System.Drawing.Imaging.ImageFormat]::Png)
}
finally {
    $graphics.Dispose()
    if ($finalBitmap -ne $bitmap) {
        $finalBitmap.Dispose()
    }
    $bitmap.Dispose()
}

[PSCustomObject]@{
    ok = $true
    window_handle = ("0x{0:X}" -f $handle.ToInt64())
    output_path = $targetPath
    width = $outputWidth
    height = $outputHeight
    crop_applied = $cropApplied
    crop_bounds_relative = $cropBoundsRelative
    crop_bounds_screen = $cropBoundsScreen
} | ConvertTo-Json -Depth 4
