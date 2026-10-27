#!/usr/bin/env pwsh
<#
.SYNOPSIS
Checks the commit, builds Robin's image for amd64 and arm64, pushes it to GHCR, then pushes the
commit, and with -Release its tag and its GitHub release.

.DESCRIPTION
Every push to main goes out as :main and :<commit sha>, the sha a rollback pins. -Release also
pushes :<version> and :latest, the tag v<version>, which robin/__init__.py's __version__ must
match, and the GitHub release, titled by the commit message's first line and noted by the rest.

Needs Docker Desktop signed in to ghcr.io with a token that can write packages, and for
-Release the gh CLI signed in to GitHub.
#>
param([switch]$Release)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
Set-Location $PSScriptRoot

# The image is built from the working tree, so it has to be exactly the commit it is tagged with.
if (git status --porcelain --untracked-files=no) { throw 'Uncommitted changes' }
if ((git branch --show-current) -ne 'main') { throw 'Not on main' }

$repo = (git remote get-url origin) -replace '^.*github\.com[:/]', '' -replace '\.git$', ''
$repo = $repo.ToLower()
$sha = git rev-parse HEAD
$version = (Select-String -Path backend/robin/__init__.py -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value
$tag = "v$version"

if ($Release) {
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { throw 'gh CLI not installed' }
    if ((git tag --points-at HEAD) -notcontains $tag) { throw "HEAD is not tagged $tag" }
}

Push-Location backend
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run mypy robin tests
uv run pytest -q
Pop-Location

Push-Location frontend
corepack pnpm install --frozen-lockfile
corepack pnpm lint
corepack pnpm exec prettier --check src
# Type checks before bundling.
corepack pnpm build
Pop-Location

$image = "ghcr.io/$repo"
$tags = @("${image}:main", "${image}:$sha")
if ($Release) { $tags += "${image}:$version", "${image}:latest" }
docker buildx build --platform linux/amd64,linux/arm64 --push `
    --label "org.opencontainers.image.source=https://github.com/$repo" `
    --label "org.opencontainers.image.revision=$sha" `
    --label "org.opencontainers.image.version=$version" `
    @($tags | ForEach-Object { '--tag', $_ }) .

if (-not $Release) {
    git push origin main
    return
}

git push --atomic origin main $tag

# The commit's message is the release: its first line the codename of a major release, or the
# version of any other, which titles it alone, and the rest the notes.
$lines = (git log -1 --format=%B) -split "`n"
$first = $lines[0] -replace '^#*\s*', ''
$title = if ("v$($first.TrimStart('v'))" -eq $tag) { $tag } else { "$tag, $first" }
$notes = New-TemporaryFile
($lines | Select-Object -Skip 1) -join "`n" | Set-Content -Path $notes -Encoding utf8NoBOM
gh release create $tag --repo $repo --verify-tag --title $title --notes-file $notes
Remove-Item $notes
