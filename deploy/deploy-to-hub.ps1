# ============================================
# Docker Hub Deployment Script (Windows)
# ============================================
# Bu script, Docker image'larini build edip Docker Hub'a push eder

param(
    [string]$DockerHubUsername = "mrbeko",
    [string]$ApiImageName = "blog-app",
    [string]$WebImageName = "blog-app",
    [string]$ApiTag = "api",
    [string]$WebTag = "web",
    [switch]$SkipBuild,
    [switch]$SkipPush
)

$ErrorActionPreference = "Stop"

# Colors
function Write-Success { param($Message) Write-Host $Message -ForegroundColor Green }
function Write-Info { param($Message) Write-Host $Message -ForegroundColor Cyan }
function Write-Warn { param($Message) Write-Host $Message -ForegroundColor Yellow }
function Write-Err { param($Message) Write-Host $Message -ForegroundColor Red }

# Variables
# PSScriptRoot: deploy klasörü, bir üst klasör proje kökü
$ScriptDir = $PSScriptRoot
if (-not $ScriptDir) { $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $ScriptDir) { $ScriptDir = "D:\MrBekoXBlogApp\deploy" }
$ProjectRoot = Split-Path -Parent $ScriptDir
if (-not $ProjectRoot -or $ProjectRoot -eq "D:\") { $ProjectRoot = "D:\MrBekoXBlogApp" }
$DateTag = Get-Date -Format "yyyyMMdd"
$ApiLatestTag = "${DockerHubUsername}/${ApiImageName}:${ApiTag}-latest"
$ApiDateTag = "${DockerHubUsername}/${ApiImageName}:${ApiTag}-${DateTag}"
$WebLatestTag = "${DockerHubUsername}/${WebImageName}:${WebTag}-latest"
$WebDateTag = "${DockerHubUsername}/${WebImageName}:${WebTag}-${DateTag}"

Write-Info "============================================"
Write-Info "Docker Hub Deployment Script"
Write-Info "============================================"
Write-Host ""
Write-Info "Project Root: $ProjectRoot"
Write-Info "API Image: $ApiLatestTag"
Write-Info "Web Image: $WebLatestTag"
Write-Info "Date Tag: $DateTag"
Write-Host ""

# Step 1: Check Docker
Write-Info "Step 1: Checking Docker..."
try {
    docker version | Out-Null
    Write-Success "Docker is running"
} catch {
    Write-Err "ERROR: Docker is not running!"
    exit 1
}

# Step 2: Build API Image
if (-not $SkipBuild) {
    Write-Host ""
    Write-Info "Step 2: Building API Image..."
    Write-Info "Directory: $ProjectRoot\src\BlogApp.Server"
    
    Push-Location "$ProjectRoot\src\BlogApp.Server"
    try {
        docker build -t $ApiLatestTag -t $ApiDateTag .
        if ($LASTEXITCODE -ne 0) { throw "API build failed" }
        Write-Success "API image built successfully"
    } finally {
        Pop-Location
    }

    # Step 3: Build Frontend Image
    Write-Host ""
    Write-Info "Step 3: Building Frontend Image..."
    Write-Info "Directory: $ProjectRoot\src\blogapp-web"
    
    Push-Location "$ProjectRoot\src\blogapp-web"
    try {
        docker build -t $WebLatestTag -t $WebDateTag --build-arg NEXT_PUBLIC_API_URL=https://mrbekox.dev/api/v1 .
        if ($LASTEXITCODE -ne 0) { throw "Frontend build failed" }
        Write-Success "Frontend image built successfully"
    } finally {
        Pop-Location
    }
} else {
    Write-Warn "Skipping build (--SkipBuild flag)"
}

# Step 4: Push to Docker Hub
if (-not $SkipPush) {
    Write-Host ""
    Write-Info "Step 4: Pushing images to Docker Hub..."
    
    # Check Docker Hub login
    Write-Info "Checking Docker Hub login..."
    $loginCheck = docker info 2>&1 | Select-String "Username"
    if (-not $loginCheck) {
        Write-Warn "Not logged in to Docker Hub. Please login:"
        docker login
        if ($LASTEXITCODE -ne 0) {
            Write-Err "Docker Hub login failed!"
            exit 1
        }
    }
    
    # Push API images
    Write-Info "Pushing API image (latest)..."
    docker push $ApiLatestTag
    if ($LASTEXITCODE -ne 0) { throw "API push failed" }
    
    Write-Info "Pushing API image (date tag)..."
    docker push $ApiDateTag
    if ($LASTEXITCODE -ne 0) { throw "API date tag push failed" }
    
    # Push Frontend images
    Write-Info "Pushing Frontend image (latest)..."
    docker push $WebLatestTag
    if ($LASTEXITCODE -ne 0) { throw "Frontend push failed" }
    
    Write-Info "Pushing Frontend image (date tag)..."
    docker push $WebDateTag
    if ($LASTEXITCODE -ne 0) { throw "Frontend date tag push failed" }
    
    Write-Success "All images pushed successfully!"
} else {
    Write-Warn "Skipping push (--SkipPush flag)"
}

# Summary
Write-Host ""
Write-Info "============================================"
Write-Success "Deployment to Docker Hub completed!"
Write-Info "============================================"
Write-Host ""
Write-Host "Images pushed:"
Write-Host "  - $ApiLatestTag"
Write-Host "  - $ApiDateTag"
Write-Host "  - $WebLatestTag"
Write-Host "  - $WebDateTag"
Write-Host ""
Write-Info "Next steps on production server:"
Write-Host "  1. SSH to your server"
Write-Host "  2. docker pull $ApiLatestTag"
Write-Host "  3. docker pull $WebLatestTag"
Write-Host "  4. Run database migration (SearchOptimization.sql)"
Write-Host "  5. docker-compose -f docker-compose.prod.yml up -d --no-deps api frontend"
Write-Host ""
Write-Warn "Don't forget to backup your database before deployment!"

