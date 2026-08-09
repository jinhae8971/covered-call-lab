# ============================================================
#  covered-call-lab -> GitHub Pages 배포 스크립트
#  실행:  cd C:\Users\spytl\투자\covered-call-lab
#         powershell -ExecutionPolicy Bypass -File .\setup_github.ps1
#  필요:  git, 그리고 repo + workflow 권한이 있는 GitHub Personal Access Token
#  성질:  멱등(idempotent). 몇 번을 다시 돌려도 안전하다.
# ============================================================

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$GH_USER = "jinhae8971"
$GH_MAIL = "jinhae8971@gmail.com"
$GH_REPO = "covered-call-lab"
$BRANCH  = "main"
$ROOT    = $PSScriptRoot

# ------------------------------------------------------------
#  git 호출 래퍼
#  git 은 정상 동작 중에도 stderr 로 정보성 메시지를 뱉는다
#  (예: "error: No such remote: origin", "Switched to branch").
#  $ErrorActionPreference = "Stop" 상태에서는 그 한 줄만으로
#  NativeCommandError 가 터져 스크립트 전체가 죽는다.
#  그래서 모든 git 호출은 반드시 이 함수를 통한다.
#  - stderr 를 stdout 으로 합쳐 삼키고
#  - 판단은 오직 종료코드로만 한다.
# ------------------------------------------------------------
$script:GitOut = ""
function Invoke-Git {
    param([string[]]$GitArgs)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    $script:GitOut = (& git @GitArgs 2>&1 | Out-String).Trim()
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prev
    return $code
}

Write-Host "`n== covered-call-lab GitHub Pages 배포 ==`n" -ForegroundColor Cyan

# ---- 0. git 존재 확인 -------------------------------------------
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "git 을 찾을 수 없습니다. https://git-scm.com/download/win 설치 후 새 창에서 다시 실행하세요."
}

# ---- 1. 토큰 입력 (화면·파일에 남기지 않는다) --------------------
$token = $env:GH_TOKEN
if ([string]::IsNullOrWhiteSpace($token)) {
    $sec = Read-Host "GitHub Personal Access Token 입력 (repo, workflow 권한)" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    $token = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}
if ([string]::IsNullOrWhiteSpace($token)) { throw "토큰이 비어 있습니다." }

$headers = @{
    Authorization          = "token $token"
    Accept                 = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
    "User-Agent"           = "covered-call-lab-setup"
}

# ---- 2. 토큰 유효성 확인 ----------------------------------------
try {
    $me = Invoke-RestMethod -Uri "https://api.github.com/user" -Headers $headers -Method Get
    Write-Host "[OK] 인증 성공: $($me.login)" -ForegroundColor Green
} catch {
    throw "토큰 인증 실패. repo/workflow 권한을 가진 토큰인지 확인하세요."
}

# ---- 3. 레포 생성 (이미 있으면 그대로 사용) ----------------------
$repoUrl = "https://api.github.com/repos/$GH_USER/$GH_REPO"
$exists = $true
try { Invoke-RestMethod -Uri $repoUrl -Headers $headers -Method Get | Out-Null }
catch { $exists = $false }

if ($exists) {
    Write-Host "[SKIP] 레포가 이미 존재합니다: $GH_USER/$GH_REPO" -ForegroundColor Yellow
} else {
    $body = @{
        name        = $GH_REPO
        description = "커버드콜 ETF 49종 원지수 대비 초과수익 대시보드 (주 1회 자동 갱신)"
        private     = $false
        has_issues  = $false
        has_wiki    = $false
    } | ConvertTo-Json
    Invoke-RestMethod -Uri "https://api.github.com/user/repos" -Headers $headers `
        -Method Post -Body $body -ContentType "application/json" | Out-Null
    Write-Host "[OK] public 레포 생성 완료" -ForegroundColor Green
}

# ---- 4. 로컬 git 초기화 -----------------------------------------
Set-Location $ROOT

# 이전 실행이 중간에 죽었다면 잠금 파일이 남아 git add 가 막힌다. 먼저 치운다.
foreach ($lock in @(".git\index.lock", ".git\HEAD.lock", ".git\config.lock")) {
    $p = Join-Path $ROOT $lock
    if (Test-Path $p) {
        Remove-Item $p -Force -ErrorAction SilentlyContinue
        Write-Host "[FIX] 잔여 잠금 파일 제거: $lock" -ForegroundColor Yellow
    }
}

Invoke-Git @("config", "--global", "--add", "safe.directory", ($ROOT -replace '\\', '/')) | Out-Null

if (-not (Test-Path (Join-Path $ROOT ".git"))) {
    if ((Invoke-Git @("init", "-b", $BRANCH)) -ne 0) {
        # 구버전 git 은 init -b 를 모른다
        if ((Invoke-Git @("init")) -ne 0) { throw "git init 실패: $script:GitOut" }
        Invoke-Git @("checkout", "-B", $BRANCH) | Out-Null
    }
    Write-Host "[OK] git 저장소 초기화" -ForegroundColor Green
} else {
    Invoke-Git @("checkout", "-B", $BRANCH) | Out-Null
    Write-Host "[SKIP] 기존 git 저장소 사용 (branch: $BRANCH)" -ForegroundColor Yellow
}

Invoke-Git @("config", "user.name",  $GH_USER) | Out-Null
Invoke-Git @("config", "user.email", $GH_MAIL) | Out-Null

# ---- 5. 커밋 & push ---------------------------------------------
# 원격 주소에 토큰을 잠깐 넣었다가 push 직후 평문 URL 로 되돌린다.
# 중간에 무슨 일이 나도 finally 에서 반드시 지운다.
$plainUrl = "https://github.com/$GH_USER/$GH_REPO.git"
$authUrl  = "https://$($GH_USER):$token@github.com/$GH_USER/$GH_REPO.git"
$pushCode = 1
$pushOut  = ""

try {
    Invoke-Git @("remote", "remove", "origin") | Out-Null
    if ((Invoke-Git @("remote", "add", "origin", $authUrl)) -ne 0) {
        Invoke-Git @("remote", "set-url", "origin", $authUrl) | Out-Null
    }

    if ((Invoke-Git @("add", "-A")) -ne 0) { throw "git add 실패: $script:GitOut" }

    # 커밋 메시지는 ASCII 로 둔다. PowerShell 5.1 은 네이티브 명령에 비ASCII 인자를
    # 넘길 때 콘솔 코드페이지로 인코딩해 한글이 깨진 채 커밋에 박힌다.
    Invoke-Git @("commit", "-m", "feat: covered-call ETF dashboard + weekly auto-refresh workflow") | Out-Null
    # 변경사항이 없으면 exit 1 이지만 정상 상황이므로 통과시킨다.

    if ((Invoke-Git @("rev-parse", "HEAD")) -ne 0) { throw "커밋이 하나도 없습니다: $script:GitOut" }

    Write-Host "[..] push 중..." -ForegroundColor Gray
    $pushCode = Invoke-Git @("push", "-u", "origin", $BRANCH, "--force")
    $pushOut  = $script:GitOut
}
finally {
    Invoke-Git @("remote", "set-url", "origin", $plainUrl) | Out-Null
}

if ($pushCode -ne 0) {
    Write-Host $pushOut -ForegroundColor DarkGray
    throw "push 실패 (exit $pushCode). 토큰의 repo/workflow 권한과 네트워크를 확인하세요."
}
Write-Host "[OK] push 완료" -ForegroundColor Green

# 토큰이 정말 사라졌는지 확인
Invoke-Git @("remote", "-v") | Out-Null
if ($script:GitOut -match "@github\.com") {
    Write-Host "[WARN] .git/config 에 토큰 흔적이 남아 있습니다. git remote -v 로 확인하세요." -ForegroundColor Red
} else {
    Write-Host "[OK] 원격 URL 검증 완료 (토큰 제거됨)" -ForegroundColor Green
}

# ---- 6. GitHub Pages 활성화 (소스 = GitHub Actions) --------------
$pagesBody = @{ build_type = "workflow" } | ConvertTo-Json
try {
    Invoke-RestMethod -Uri "$repoUrl/pages" -Headers $headers -Method Post `
        -Body $pagesBody -ContentType "application/json" | Out-Null
    Write-Host "[OK] GitHub Pages 활성화 (소스: GitHub Actions)" -ForegroundColor Green
} catch {
    try {
        Invoke-RestMethod -Uri "$repoUrl/pages" -Headers $headers -Method Put `
            -Body $pagesBody -ContentType "application/json" | Out-Null
        Write-Host "[OK] GitHub Pages 설정 갱신 (소스: GitHub Actions)" -ForegroundColor Green
    } catch {
        Write-Host "[WARN] Pages 자동 설정 실패. Settings > Pages 에서 Source 를 GitHub Actions 로 직접 지정하세요." -ForegroundColor Yellow
    }
}

# ---- 7. 워크플로우 즉시 1회 실행 --------------------------------
Start-Sleep -Seconds 5
$wfBody = @{ ref = $BRANCH; inputs = @{ scope = "all" } } | ConvertTo-Json -Depth 4
$dispatched = $false
foreach ($try in 1..3) {
    try {
        Invoke-RestMethod -Uri "$repoUrl/actions/workflows/update-dashboard.yml/dispatches" `
            -Headers $headers -Method Post -Body $wfBody -ContentType "application/json" | Out-Null
        $dispatched = $true
        break
    } catch {
        Start-Sleep -Seconds 5   # 워크플로우 파일이 등록되기까지 잠깐 걸린다
    }
}
if ($dispatched) {
    Write-Host "[OK] 워크플로우 첫 실행 요청됨" -ForegroundColor Green
} else {
    Write-Host "[WARN] 자동 실행 실패. Actions 탭에서 Run workflow 를 눌러주세요." -ForegroundColor Yellow
}

# ---- 8. 안내 ----------------------------------------------------
Write-Host ""
Write-Host "레포     : https://github.com/$GH_USER/$GH_REPO" -ForegroundColor Cyan
Write-Host "Actions  : https://github.com/$GH_USER/$GH_REPO/actions" -ForegroundColor Cyan
Write-Host "대시보드 : https://$GH_USER.github.io/$GH_REPO/" -ForegroundColor Cyan
Write-Host ""
Write-Host "첫 배포까지 2~3분 걸립니다. 이후 매주 토요일 오전 8시(KST)에 자동 갱신됩니다." -ForegroundColor Gray

$token = $null
$authUrl = $null
