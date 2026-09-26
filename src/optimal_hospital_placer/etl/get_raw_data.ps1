#requires -Version 5.1
<#
.SYNOPSIS
Downloads raw US healthcare, demographic, vulnerability, and road data.
.DESCRIPTION
Run with -ListSources for an offline summary or -PlanOnly to resolve URLs without
downloading data. Files remain in their original format; ZIPs are not extracted.
See get_raw_data.README.md for scope, examples, and source documentation.
#>
[CmdletBinding()]
param(
    [ValidateSet('All','CMSHospital','CMSFacilities','AHRF','HPSA','MUAP','PLACES','ACS','SVI','RUCA','OSM')]
    [string[]]$Sources = @('All'),
    [string]$OutputDirectory,
    [ValidatePattern('^\d{4}-\d{4}$')][string]$AhrfRelease = '2024-2025',
    [ValidateRange(2009,2100)][int]$AcsYear = 2024,
    [ValidateSet('county','tract')][string]$AcsGeography = 'county',
    [ValidatePattern('^\d{2}$')][string[]]$StateFips = @(),
    [ValidatePattern('^[A-Za-z0-9_]+$')]
    [string[]]$AcsVariables = @('B01003_001E','B01002_001E','B19013_001E','B17001_002E','B23025_005E','B08201_002E'),
    [ValidateSet('county','place','tract','zcta')]
    [string[]]$PlacesGeographies = @('county','place','tract','zcta'),
    [ValidateSet(2000,2010,2014,2016,2018,2020,2022)][int]$SviYear = 2022,
    [ValidateSet('county','tract')][string[]]$SviGeographies = @('county','tract'),
    [ValidatePattern('^[a-z]+(?:-[a-z]+)*$')][string]$OsmRegion = 'us',
    [switch]$IncludeBoundaries,
    [switch]$Force,
    [switch]$ListSources,
    [switch]$PlanOnly,
    [ValidateRange(1,10)][int]$Retries = 3,
    [ValidateRange(30,86400)][int]$TimeoutSeconds = 3600
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$sourceDescriptions = [ordered]@{
    CMSHospital = 'Hospital General Information: current full CMS CSV'
    CMSFacilities = 'Latest QIES/iQIES provider files and facility enrollment CSVs (selected catalog datasets)'
    AHRF = 'County and state/national CSV ZIPs plus technical documentation'
    HPSA = 'Primary care, dental, mental health CSVs and metadata; optional shapefiles'
    MUAP = 'Medically underserved areas/populations CSV and metadata; optional shapefiles'
    PLACES = 'Full GIS-friendly CSV exports for selected geographies plus metadata'
    ACS = 'ACS 5-year detailed-table API responses for selected variables and county/tract geography'
    SVI = 'Nationally ranked county/tract CSVs; optional geodatabase ZIPs'
    RUCA = '2020 tract and ZIP CSV/XLSX files (XLSX includes codebooks)'
    OSM = 'Geofabrik US or state .osm.pbf extract; US is a multi-gigabyte download'
}
if ($ListSources) {
    $sourceDescriptions.GetEnumerator() | ForEach-Object { [pscustomobject]@{ Source = $_.Key; Scope = $_.Value } }
    return
}
if ('All' -in $Sources) { $Sources = @($sourceDescriptions.Keys) }
$Sources = @($Sources | Select-Object -Unique)
if ('ACS' -in $Sources -and $AcsGeography -eq 'tract' -and !$StateFips.Count) {
    throw 'Tract ACS requests require -StateFips (e.g. -StateFips 17,55).'
}
$AcsVariables = @($AcsVariables | Where-Object { $_ -ne 'NAME' } | Select-Object -Unique)
if ('ACS' -in $Sources -and !$AcsVariables.Count) { throw 'Specify at least one ACS variable.' }
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    # Resolve after parameter binding. Editor selections/pasted code may not have
    # a script root; in that case locate this repository from the current folder.
    $downloadScriptRoot = $PSScriptRoot
    if (!$downloadScriptRoot -and $MyInvocation.MyCommand.Path) {
        $downloadScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
    }
    if ($downloadScriptRoot) {
        $OutputDirectory = Join-Path $downloadScriptRoot '../../../data/raw'
    } else {
        $searchDirectory = (Get-Location).ProviderPath
        while ($searchDirectory) {
            $candidate = Join-Path $searchDirectory 'src/optimal_hospital_placer/etl/get_raw_data.ps1'
            if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                $OutputDirectory = Join-Path $searchDirectory 'data/raw'
                break
            }
            $searchDirectory = Split-Path -Parent $searchDirectory
        }
        if (!$OutputDirectory) {
            throw 'Cannot locate the repository. Run the saved .ps1 file or specify -OutputDirectory explicitly.'
        }
    }
}
# Resolve explicit relative paths against PowerShell's location, not the process CWD.
$OutputDirectory = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputDirectory)
# Windows PowerShell uses .NET Framework's process-wide TLS settings.
# Add TLS 1.2 for government HTTPS endpoints without removing existing protocols.
if ($PSVersionTable.PSVersion.Major -lt 6) {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
}
$jobs = [Collections.Generic.List[object]]::new()
$results = [Collections.Generic.List[object]]::new()

function Get-Metadata([string]$Url) {
    for ($attempt = 1; $attempt -le $Retries; $attempt++) {
        try { return Invoke-RestMethod -Uri $Url -TimeoutSec 60 -UseBasicParsing }
        catch {
            if ($attempt -eq $Retries) { throw }
            Start-Sleep -Seconds ([Math]::Min(30, [Math]::Pow(2,$attempt)))
        }
    }
}
function Add-Download([string]$Source, [string]$Url, [string]$Name, [string]$Note = '') {
    if (([uri]$Url).Scheme -ne 'https') { throw "Expected HTTPS download URL: $Url" }
    if (!$Name -or $Name -match '[/\\]' -or $Name -in @('.','..')) { throw "Invalid filename: $Name" }
    $jobs.Add([pscustomobject]@{ Source = $Source; Url = $Url; File = "$Source/$Name"; Note = $Note })
}
function Add-Hrsa([string]$Source, [string]$Name) {
    Add-Download $Source "https://data.hrsa.gov/DataDownload/DD_Files/$Name" $Name
}
function Add-CmsDataset($Dataset, [string]$Source) {
    # Sort by coverage period first: a corrected old release must not win over a new one.
    $file = $Dataset.distribution | Where-Object { $_.downloadURL -and ($_.mediaType -eq 'text/csv' -or $_.format -eq 'CSV') } |
        Sort-Object -Property temporal, modified -Descending | Select-Object -First 1
    if (!$file) { throw "No CSV distribution found for $($Dataset.title)" }
    $name = [uri]::UnescapeDataString(([uri]$file.downloadURL).Segments[-1])
    Add-Download $Source $file.downloadURL $name "$($Dataset.title); $($file.temporal)"
}

foreach ($source in $Sources) {
    Write-Host "Resolving $source..."
    try {
        switch ($source) {
            CMSHospital {
                $catalog = Get-Metadata 'https://data.cms.gov/provider-data/data.json'
                $dataset = $catalog.dataset | Where-Object identifier -eq 'xubh-q36u' | Select-Object -First 1
                if (!$dataset) { throw 'Hospital General Information is missing from the CMS catalog.' }
                Add-CmsDataset $dataset $source
            }
            CMSFacilities {
                $catalog = Get-Metadata 'https://data.cms.gov/data.json'
                $datasets = @($catalog.dataset | Where-Object {
                    $_.title -match '^Provider of Services File.*(Quality Improvement|Hospital.*Non-Hospital)' -or
                    $_.title -match '^(Hospital|Federally Qualified Health Center|Skilled Nursing Facility|Hospice|Rural Health Clinic|Home Health Agency) Enrollments$'
                })
                if (!$datasets.Count) { throw 'No facility datasets matched the CMS catalog.' }
                foreach ($dataset in $datasets) { Add-CmsDataset $dataset $source }
            }
            AHRF {
                foreach ($name in @("AHRF_${AhrfRelease}_CSV.zip", "AHRF_SN_${AhrfRelease}_CSV.zip", "AHRF_USER_TECH_${AhrfRelease}.zip", "AHRF_SN_USER_TECH_${AhrfRelease}.zip")) {
                    Add-Download $source "https://data.hrsa.gov/DataDownload/AHRF/$name" $name
                }
            }
            HPSA {
                Add-Hrsa $source 'HPSA_DATAMART_METADATA.XLSX'
                foreach ($discipline in @('PC','DH','MH')) {
                    Add-Hrsa $source "BCD_HPSA_FCT_DET_$discipline.csv"
                    if ($IncludeBoundaries) {
                        foreach ($shape in @('PNT','CMP','PLY')) { Add-Hrsa $source "HPSA_${shape}${discipline}_SHP.zip" }
                    }
                }
            }
            MUAP {
                Add-Hrsa $source 'MUA_DET.csv'
                Add-Hrsa $source 'MUA_DATAMART_METADATA.XLSX'
                if ($IncludeBoundaries) {
                    Add-Hrsa $source 'MUA_SHP.zip'
                    Add-Hrsa $source 'MUA_CMPPC_SHP.zip'
                }
            }
            PLACES {
                # CDC's current-release aliases; metadata records the actual release.
                $ids = @{ county = 'i46a-9kgh'; place = 'vgc8-iyc4'; tract = 'yjkw-uj5s'; zcta = 'kee5-23sr' }
                foreach ($geo in ($PlacesGeographies | Select-Object -Unique)) {
                    $id = $ids[$geo]
                    # Full export, not the resource API's default truncated page.
                    Add-Download $source "https://data.cdc.gov/api/views/$id/rows.csv?accessType=DOWNLOAD" "places_$geo.csv"
                    Add-Download $source "https://data.cdc.gov/api/views/$id.json" "places_${geo}_metadata.json"
                }
            }
            ACS {
                $base = "https://api.census.gov/data/$AcsYear/acs/acs5"
                Add-Download $source "$base/variables.json" "acs_${AcsYear}_variables.json"
                # Census data-row requests require an API key; retain only public metadata.
            }
            SVI {
                foreach ($geo in ($SviGeographies | Select-Object -Unique)) {
                    $dir = 'states'; $name = "SVI_${SviYear}_US"
                    if ($geo -eq 'county') { $dir = 'states_counties'; $name += '_county' }
                    Add-Download $source "https://svi.cdc.gov/Documents/Data/$SviYear/csv/$dir/$name.csv" "$name.csv"
                    if ($IncludeBoundaries) { Add-Download $source "https://svi.cdc.gov/Documents/Data/$SviYear/db/$dir/$name.zip" "$name.zip" }
                }
            }
            RUCA {
                $pageUrl = 'https://www.ers.usda.gov/data-products/rural-urban-commuting-area-codes'
                $html = Get-Metadata $pageUrl
                $links = @([regex]::Matches([string]$html, 'href=["'']([^"'']*2020-rural-urban-commuting-area-codes[^"'']*\.(?:csv|xlsx)(?:\?[^"'']*)?)["'']') |
                    ForEach-Object { [Net.WebUtility]::HtmlDecode($_.Groups[1].Value) } | Select-Object -Unique)
                if ($links.Count -lt 4) { throw "Expected tract and ZIP CSV/XLSX links. Check $pageUrl" }
                foreach ($link in $links) {
                    $url = [uri]::new([uri]$pageUrl, $link)
                    Add-Download $source $url.AbsoluteUri $url.Segments[-1]
                }
            }
            OSM {
                $path = 'north-america/us'
                if ($OsmRegion -ne 'us') { $path += "/$OsmRegion" }
                Add-Download $source "https://download.geofabrik.de/$path-latest.osm.pbf" "$OsmRegion-latest.osm.pbf" 'OSM contributors / ODbL; requires a routing engine to compute drive times'
            }
        }
    }
    catch {
        $results.Add([pscustomobject]@{ Source = $source; Status = 'resolution_failed'; Error = $_.Exception.Message })
        Write-Warning "$source resolution failed: $($_.Exception.Message)"
    }
}

if ($PlanOnly) {
    $jobs | Select-Object Source, File, Url, Note
    if ($results.Count) { throw 'Some sources could not be resolved; see warnings above.' }
    return
}

New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$manifestPath = Join-Path $OutputDirectory ("manifest-{0}-{1}.json" -f (Get-Date -Format 'yyyyMMdd-HHmmss'), [guid]::NewGuid().ToString('N').Substring(0,8))
function Save-Manifest {
    ConvertTo-Json -InputObject @($results.ToArray()) -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding utf8
}
Save-Manifest
foreach ($job in $jobs) {
    $destination = Join-Path $OutputDirectory $job.File
    $receiptPath = "$destination.receipt.json"
    $partial = "$destination.$([guid]::NewGuid().ToString('N')).part"
    $record = [ordered]@{ Source = $job.Source; Url = $job.Url; File = $job.File; Note = $job.Note; Status = 'failed'; CheckedUtc = [DateTime]::UtcNow.ToString('o'); Bytes = $null; Sha256 = $null; Error = $null }
    try {
        New-Item -ItemType Directory -Path (Split-Path $destination) -Force | Out-Null
        $cached = $false
        if (!$Force -and (Test-Path -LiteralPath $destination) -and (Test-Path -LiteralPath $receiptPath)) {
            try {
                $receipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
                $cached = $receipt.Url -eq $job.Url -and $receipt.Sha256 -eq (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash
            } catch { $cached = $false }
        }
        if ($cached) {
            $record.Status = 'cached'
            $record.Bytes = (Get-Item -LiteralPath $destination).Length
            $record.Sha256 = $receipt.Sha256
            Write-Host "Cached: $($job.File)"
        } else {
            Write-Host "Downloading: $($job.File)"
            for ($attempt = 1; $attempt -le $Retries; $attempt++) {
                try {
                    Invoke-WebRequest -Uri $job.Url -OutFile $partial -TimeoutSec $TimeoutSeconds -UseBasicParsing
                    if ((Get-Item -LiteralPath $partial).Length -eq 0) { throw 'Empty response.' }
                    $stream = [IO.File]::OpenRead($partial)
                    try {
                        $buffer = [byte[]]::new(512)
                        $count = $stream.Read($buffer,0,$buffer.Length)
                        $prefix = [Text.Encoding]::UTF8.GetString($buffer,0,$count)
                    } finally { $stream.Dispose() }
                    if ($prefix -match '(?is)^\s*(?:\uFEFF)?\s*<(?:!doctype|html|head|body)' ) { throw 'Server returned HTML instead of data.' }
                    if ($job.File -match '\.(zip|xlsx)$' -and ($buffer[0] -ne 80 -or $buffer[1] -ne 75)) { throw 'Invalid ZIP/XLSX signature.' }
                    if ($job.File -match '\.json$') {
                        $parsed = Get-Content -LiteralPath $partial -Raw -Encoding UTF8 | ConvertFrom-Json
                        if ($job.Source -eq 'ACS' -and $job.File -notmatch 'variables' -and ($parsed.Count -lt 2 -or $parsed[0][0] -ne 'NAME')) { throw 'Census response did not contain data rows.' }
                    }
                    break
                } catch {
                    if ($attempt -eq $Retries) { throw }
                    Start-Sleep -Seconds ([Math]::Min(30,[Math]::Pow(2,$attempt)))
                }
            }
            $record.Bytes = (Get-Item -LiteralPath $partial).Length
            $record.Sha256 = (Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash
            Move-Item -LiteralPath $partial -Destination $destination -Force
            $record.Status = 'downloaded'
            $record | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receiptPath -Encoding utf8
        }
    } catch {
        $record.Status = 'failed'
        $record.Error = $_.Exception.Message
        Write-Warning "$($job.File): $($record.Error)"
    } finally {
        if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Force }
        $results.Add([pscustomobject]$record)
        Save-Manifest
    }
}
Write-Host "Manifest: $manifestPath"
$results | Group-Object Status | Select-Object Name, Count | Format-Table
if (@($results | Where-Object Status -in @('failed','resolution_failed')).Count) {
    throw 'One or more downloads failed. Successful files are retained; inspect the manifest and rerun.'
}
