param(
    [string]$Owner = "11lisov11",
    [string]$Repo = "plotter_pdf",
    [string]$Branch = "main",
    [string]$Token = $env:GITHUB_TOKEN
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($Token)) {
    throw "GITHUB_TOKEN is not set. Export a token with repo/admin:repo_hook permissions and retry."
}

$uri = "https://api.github.com/repos/$Owner/$Repo/branches/$Branch/protection"

$payload = @{
    required_status_checks = @{
        strict   = $true
        contexts = @(
            "Lint (ruff)",
            "Tests (unittest + pytest)",
            "Coverage (pytest)",
            "Build smoke (Windows)"
        )
    }
    enforce_admins = $false
    required_pull_request_reviews = @{
        dismiss_stale_reviews           = $true
        require_code_owner_reviews      = $false
        required_approving_review_count = 1
    }
    restrictions = $null
    required_conversation_resolution = $true
}

$headers = @{
    Authorization         = "Bearer $Token"
    Accept                = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
}

Write-Host "Applying branch protection to $Owner/$Repo:$Branch ..."
$result = Invoke-RestMethod -Method Put -Uri $uri -Headers $headers -Body ($payload | ConvertTo-Json -Depth 10) -ContentType "application/json"
Write-Host "Branch protection updated."
Write-Host ("Required checks: " + (($result.required_status_checks.contexts | ForEach-Object { $_.context }) -join ", "))

