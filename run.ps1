# run.ps1 — convenience wrapper for the MEXT outreach tool
# Usage: .\run.ps1 <script> [args...]
# Examples:
#   .\run.ps1 discoverer run
#   .\run.ps1 discoverer run --dry-run
#   .\run.ps1 mext_sender preview --all
#   .\run.ps1 mext_sender send --confirm

$python = "C:\Users\Raja\.local\bin\python3.14.exe"

if ($args.Count -eq 0) {
    Write-Host "Usage: .\run.ps1 <script> [args...]"
    Write-Host ""
    Write-Host "Discovery pipeline:"
    Write-Host "  .\run.ps1 discoverer run              # full auto pipeline"
    Write-Host "  .\run.ps1 discoverer run --dry-run    # preview without importing"
    Write-Host "  .\run.ps1 discoverer status           # cache + queue counts"
    Write-Host "  .\run.ps1 discoverer report           # show scored professors"
    Write-Host ""
    Write-Host "Sending:"
    Write-Host "  .\run.ps1 mext_sender preview --all"
    Write-Host "  .\run.ps1 mext_sender send --confirm"
    Write-Host "  .\run.ps1 mext_sender followup --confirm"
    Write-Host "  .\run.ps1 mext_sender status"
    Write-Host "  .\run.ps1 mext_sender export"
    exit 0
}

$script = $args[0] + ".py"
$rest   = $args[1..($args.Count - 1)]

& $python $script @rest
