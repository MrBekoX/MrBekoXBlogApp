# Build all release images from the same checkout. Publishing is opt-in.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$')][string]$ReleaseTag,
    [Parameter(Mandatory = $true)][string]$SiteUrl,
    [Parameter(Mandatory = $true)][ValidateNotNullOrEmpty()][string]$AuthorName,
    [string]$ImageRepository = 'mrbeko/blog-app',
    [string]$PublicSignalRUrl = '',
    [string]$TurnstileSiteKey = '',
    [string]$GitHubUrl = '',
    [string]$TwitterUrl = '',
    [string]$LinkedInUrl = '',
    [string]$TwitterHandle = '',
    [switch]$Push,
    [switch]$SkipBuild
)
$ErrorActionPreference = 'Stop'
if ($ReleaseTag -eq 'latest') { throw 'Use a release-specific tag (for example a commit hash), not latest' }
if ($SkipBuild -and -not $Push) { throw '-SkipBuild requires -Push' }
$siteUri = $null
if (-not [Uri]::TryCreate($SiteUrl, [UriKind]::Absolute, [ref]$siteUri) -or
    $siteUri.Scheme -ne 'https' -or $siteUri.AbsolutePath -ne '/' -or
    $siteUri.Query -or $siteUri.Fragment -or $siteUri.UserInfo -or $siteUri.Port -ne 443 -or
    $siteUri.DnsSafeHost -notmatch '^(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$') {
    throw 'SiteUrl must be an HTTPS public site origin without path, credentials, query, fragment or custom port'
}
$SiteUrl = $siteUri.GetLeftPart([UriPartial]::Authority).TrimEnd('/')
$AuthorName = $AuthorName.Trim()
if (-not $AuthorName -or $AuthorName -ieq 'Sample Author' -or $AuthorName.Length -gt 200 -or $AuthorName -match '[\r\n]') {
    throw 'AuthorName must be the approved public author name; sample or multiline values are refused'
}
foreach ($publicLink in @($GitHubUrl, $TwitterUrl, $LinkedInUrl)) {
    if (-not $publicLink) { continue }
    $publicUri = $null
    if ($publicLink -match '\s' -or -not [Uri]::TryCreate($publicLink, [UriKind]::Absolute, [ref]$publicUri) -or
        $publicUri.Scheme -ne 'https' -or $publicUri.UserInfo -or $publicUri.Query -or $publicUri.Fragment -or
        $publicUri.Port -ne 443 -or $publicUri.DnsSafeHost -notmatch '^(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$') {
        throw 'Optional public social links must use HTTPS without whitespace, credentials, query, fragment or custom port'
    }
}
if ($TwitterHandle -and $TwitterHandle -notmatch '^@[A-Za-z0-9_]{1,15}$') {
    throw 'TwitterHandle must be empty or a public @handle of at most 15 characters'
}
$ProjectRoot = Split-Path -Parent $PSScriptRoot
function Invoke-Docker {
    param([string[]]$Arguments)
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Docker command failed with exit code $LASTEXITCODE" }
}
Invoke-Docker -Arguments @('info', '--format', '{{.ServerVersion}}')
$Images = @(
    @{ Name = "${ImageRepository}:api-${ReleaseTag}"; Dockerfile = "$ProjectRoot/docker/backend/Dockerfile"; Context = $ProjectRoot; Extra = @() },
    @{ Name = "${ImageRepository}:web-${ReleaseTag}"; Dockerfile = "$ProjectRoot/docker/frontend/Dockerfile"; Context = "$ProjectRoot/src/frontend/blogapp-web"; Extra = @('--build-arg', 'NEXT_PUBLIC_API_URL=/api/v1', '--build-arg', "NEXT_PUBLIC_SIGNALR_URL=$PublicSignalRUrl", '--build-arg', "NEXT_PUBLIC_TURNSTILE_SITE_KEY=$TurnstileSiteKey", '--build-arg', "NEXT_PUBLIC_SITE_URL=$SiteUrl", '--build-arg', "NEXT_PUBLIC_AUTHOR_NAME=$AuthorName", '--build-arg', "NEXT_PUBLIC_GITHUB_URL=$GitHubUrl", '--build-arg', "NEXT_PUBLIC_TWITTER_URL=$TwitterUrl", '--build-arg', "NEXT_PUBLIC_LINKEDIN_URL=$LinkedInUrl", '--build-arg', "NEXT_PUBLIC_TWITTER_HANDLE=$TwitterHandle", '--build-arg', 'API_URL=http://api:8080/api/v1', '--build-arg', 'REWRITE_URL=http://api:8080') },
    @{ Name = "${ImageRepository}:agent-${ReleaseTag}"; Dockerfile = "$ProjectRoot/docker/ai-agent-service/Dockerfile"; Context = $ProjectRoot; Extra = @() }
)
foreach ($Image in $Images) {
    if (-not $SkipBuild) {
        Invoke-Docker -Arguments (@('build', '--platform', 'linux/amd64', '--tag', $Image.Name, '--file', $Image.Dockerfile) + $Image.Extra + @($Image.Context))
    }
    if ($Push) { Invoke-Docker -Arguments @('push', $Image.Name) }
    Write-Output $Image.Name
}
if ($Push) {
    Write-Output 'Three release images published. No server deployment was performed.'
} else {
    Write-Output 'Three release images built locally. Registry publishing requires -Push.'
}
