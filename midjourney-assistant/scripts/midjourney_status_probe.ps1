param(
    [string]$WindowHandle,
    [string]$PromptContains,
    [string]$ProgressPattern = "^(Submitting\\.\\.\\.|Starting\\.\\.\\.|[0-9]{1,3}% Complete)$",
    [int]$SampleLimit = 12
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($WindowHandle)) {
    throw "-WindowHandle is required"
}

if ([string]::IsNullOrWhiteSpace($PromptContains)) {
    throw "-PromptContains is required"
}

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

function Convert-ToWindowHandle {
    param([string]$Value)
    if ($Value.StartsWith("0x")) {
        return [IntPtr]([Convert]::ToInt64($Value, 16))
    }
    return [IntPtr]([Convert]::ToInt64($Value))
}

function Normalize-Text {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return ""
    }
    return ($Value -replace "\s+", " ").Trim()
}

function Get-MaxIndex {
    param($Nodes)
    if ($null -eq $Nodes -or $Nodes.Count -eq 0) {
        return -1
    }
    return [int](($Nodes | Measure-Object -Property idx -Maximum).Maximum)
}

function Get-RectData {
    param($Rect)

    if ($null -eq $Rect) {
        return $null
    }

    return [PSCustomObject]@{
        left = [double]$Rect.Left
        top = [double]$Rect.Top
        right = [double]$Rect.Right
        bottom = [double]$Rect.Bottom
        width = [double]$Rect.Width
        height = [double]$Rect.Height
    }
}

function Test-RectVisible {
    param($Rect)

    return ($null -ne $Rect -and $Rect.width -gt 1 -and $Rect.height -gt 1)
}

function Merge-Rectangles {
    param($Rects)

    if ($null -eq $Rects -or $Rects.Count -eq 0) {
        return $null
    }

    $left = ($Rects | Measure-Object -Property left -Minimum).Minimum
    $top = ($Rects | Measure-Object -Property top -Minimum).Minimum
    $right = ($Rects | Measure-Object -Property right -Maximum).Maximum
    $bottom = ($Rects | Measure-Object -Property bottom -Maximum).Maximum

    return [PSCustomObject]@{
        left = [double]$left
        top = [double]$top
        right = [double]$right
        bottom = [double]$bottom
        width = [double]($right - $left)
        height = [double]($bottom - $top)
    }
}

function Get-RegionKey {
    param(
        $PromptNode,
        [string]$PromptText
    )

    $rect = $PromptNode.rect
    return (
        "{0}:{1}:{2}:{3}:{4}" -f
        [int]([Math]::Round($rect.left / 12)),
        [int]([Math]::Round($rect.top / 12)),
        [int]([Math]::Round($rect.width / 12)),
        [int]([Math]::Round($rect.height / 12)),
        (($PromptText.ToLowerInvariant()) -replace "\s+", " ").Substring(0, [Math]::Min(80, $PromptText.Length))
    )
}

function Get-RegionStatePriority {
    param([string]$State)

    switch ($State) {
        "generating" { return 0 }
        "submitting" { return 1 }
        "completed" { return 2 }
        default { return 99 }
    }
}

$handle = Convert-ToWindowHandle -Value $WindowHandle
$root = [System.Windows.Automation.AutomationElement]::FromHandle($handle)
if ($null -eq $root) {
    [PSCustomObject]@{
        ok = $false
        uia_available = $false
        status = "window_not_found"
        prompt_query = (Normalize-Text -Value $PromptContains)
        progress_pattern = $ProgressPattern
        prompt_found = $false
        prompt_region_found = $false
        generating_signal_found = $false
        matched_prompt_count = 0
        matched_progress_count = 0
        max_prompt_index = -1
        max_progress_index = -1
        matched_prompt_nodes = @()
        matched_progress_nodes = @()
        region_keys = @()
        regions = @()
        relevant_nodes = @()
    } | ConvertTo-Json -Depth 8
    exit 0
}

$all = $root.FindAll(
    [System.Windows.Automation.TreeScope]::Descendants,
    [System.Windows.Automation.Condition]::TrueCondition
)

$needle = Normalize-Text -Value $PromptContains
$needleLower = $needle.ToLowerInvariant()
$promptNodes = @()
$progressNodes = @()
$imageNodes = @()
$relevantNodes = @()

for ($i = 0; $i -lt $all.Count; $i++) {
    $node = $all.Item($i)
    try {
        $name = Normalize-Text -Value $node.Current.Name
        $className = $node.Current.ClassName
        $typeName = $node.Current.ControlType.ProgrammaticName
        $rect = Get-RectData -Rect $node.Current.BoundingRectangle
    }
    catch {
        continue
    }

    if (-not (Test-RectVisible -Rect $rect)) {
        continue
    }

    if ($className -eq "EdgeTab") {
        continue
    }

    $isPromptNode = (-not [string]::IsNullOrWhiteSpace($needleLower) -and -not [string]::IsNullOrWhiteSpace($name) -and $name.ToLowerInvariant().Contains($needleLower))
    $isProgressNode = (-not [string]::IsNullOrWhiteSpace($name) -and $name -match $ProgressPattern)
    $isImageNode = (
        ($typeName -match "ImageControl" -or $className -match "Image") -and
        $rect.width -ge 48 -and
        $rect.height -ge 48
    )

    $record = [PSCustomObject]@{
        idx = $i
        type = $typeName
        class = $className
        name = $name
        rect = $rect
        center_x = [double]($rect.left + ($rect.width / 2))
        center_y = [double]($rect.top + ($rect.height / 2))
    }

    if ($isPromptNode) {
        $promptNodes += $record
    }

    if ($isProgressNode) {
        $progressNodes += $record
    }

    if ($isImageNode) {
        $imageNodes += $record
    }

    if ($isPromptNode -or $isProgressNode -or $isImageNode) {
        $relevantNodes += $record
    }
}

$regionMap = @{}
$sortedPromptNodes = @($promptNodes | Sort-Object idx)
for ($promptIndex = 0; $promptIndex -lt $sortedPromptNodes.Count; $promptIndex++) {
    $promptNode = $sortedPromptNodes[$promptIndex]
    $promptRect = $promptNode.rect
    $nextPromptNode = if ($promptIndex + 1 -lt $sortedPromptNodes.Count) {
        $sortedPromptNodes[$promptIndex + 1]
    }
    else {
        $null
    }
    $maxIndex = if ($null -ne $nextPromptNode) {
        [int]$nextPromptNode.idx - 1
    }
    else {
        [int]$promptNode.idx + 320
    }
    $maxBottom = if ($null -ne $nextPromptNode) {
        [double]([Math]::Max($promptRect.bottom + 80, $nextPromptNode.rect.top - 30))
    }
    else {
        [double]($promptRect.bottom + 720)
    }
    $regionNodes = @(
        $relevantNodes | Where-Object {
            $_.idx -ge [int]$promptNode.idx -and
            $_.idx -le $maxIndex -and
            $_.rect.top -le $maxBottom -and
            $_.rect.bottom -ge ($promptRect.top - 120) -and
            $_.rect.left -le ($promptRect.right + 640) -and
            $_.rect.right -ge ($promptRect.left - 240)
        }
    )

    if ($regionNodes.Count -eq 0) {
        $regionNodes = @($promptNode)
    }

    $regionBounds = Merge-Rectangles -Rects @($regionNodes.rect)
    $regionProgressNodes = @($regionNodes | Where-Object { -not [string]::IsNullOrWhiteSpace($_.name) -and $_.name -match $ProgressPattern })
    $regionImageNodes = @($regionNodes | Where-Object {
        ($_.type -match "ImageControl" -or $_.class -match "Image") -and $_.rect.width -ge 48 -and $_.rect.height -ge 48
    })

    $progressMatches = @($regionProgressNodes | ForEach-Object { $_.name } | Select-Object -Unique)
    $imageCount = @($regionImageNodes | ForEach-Object { $_.idx } | Select-Object -Unique).Count
    $promptText = $promptNode.name
    $regionState = "submitting"
    if ($progressMatches.Count -gt 0) {
        $regionState = "generating"
    }
    elseif ($imageCount -gt 0) {
        $regionState = "completed"
    }

    $regionKey = Get-RegionKey -PromptNode $promptNode -PromptText $promptText
    $candidate = [PSCustomObject]@{
        region_key = $regionKey
        prompt_text = $promptText
        prompt_index = [int]$promptNode.idx
        region_state = $regionState
        region_progress_text = if ($progressMatches.Count -gt 0) { [string]$progressMatches[0] } else { "" }
        region_progress_matches = @($progressMatches)
        region_image_count = [int]$imageCount
        region_has_placeholder = ($imageCount -eq 0)
        region_bounds = $regionBounds
        score = [int]([Math]::Round($regionBounds.width * $regionBounds.height)) + ($imageCount * 10000) + ($progressMatches.Count * 5000)
        relevant_nodes = @(
            $regionNodes |
                Sort-Object idx |
                Select-Object -First ([Math]::Max($SampleLimit, 1)) |
                ForEach-Object {
                    [PSCustomObject]@{
                        idx = $_.idx
                        type = $_.type
                        class = $_.class
                        name = $_.name
                        rect = $_.rect
                    }
                }
        )
    }

    if (-not $regionMap.ContainsKey($regionKey) -or $candidate.score -gt $regionMap[$regionKey].score) {
        $regionMap[$regionKey] = $candidate
    }
}

$regions = @(
    $regionMap.Values |
        Sort-Object `
            @{ Expression = { Get-RegionStatePriority -State $_.region_state } }, `
            @{ Expression = { $_.region_bounds.top } }, `
            @{ Expression = { -$_.prompt_index } }
)

$bestRegion = if ($regions.Count -gt 0) { $regions[0] } else { $null }
$status = if ($null -ne $bestRegion) { [string]$bestRegion.region_state } else { "not_found" }
$allProgressMatches = @($regions | ForEach-Object { $_.region_progress_matches } | Select-Object -First 12)
$allRelevantNodes = @(
    $relevantNodes |
        Sort-Object idx |
        Select-Object -First ([Math]::Max($SampleLimit, 1)) |
        ForEach-Object {
            [PSCustomObject]@{
                idx = $_.idx
                type = $_.type
                class = $_.class
                name = $_.name
                rect = $_.rect
            }
        }
)

[PSCustomObject]@{
    ok = $true
    uia_available = $true
    status = $status
    prompt_query = $needle
    progress_pattern = $ProgressPattern
    prompt_found = ($promptNodes.Count -gt 0)
    prompt_region_found = ($regions.Count -gt 0)
    generating_signal_found = ($allProgressMatches.Count -gt 0)
    matched_prompt_count = $promptNodes.Count
    matched_progress_count = $progressNodes.Count
    max_prompt_index = (Get-MaxIndex -Nodes $promptNodes)
    max_progress_index = (Get-MaxIndex -Nodes $progressNodes)
    matched_prompt_nodes = @($promptNodes | Select-Object idx, type, class, name, rect)
    matched_progress_nodes = @($progressNodes | Select-Object idx, type, class, name, rect)
    region_keys = @($regions | ForEach-Object { $_.region_key })
    selected_region = $bestRegion
    regions = @($regions)
    progress_matches = @($allProgressMatches)
    relevant_nodes = $allRelevantNodes
} | ConvertTo-Json -Depth 8
