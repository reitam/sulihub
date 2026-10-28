<#
.SYNOPSIS
    KRETA Adatlekerő - elesito script, Windows-rol Linux-ra (HPReiTam)

.DESCRIPTION
    A RabbitApp_Svelte deploy.ps1 mintajara:
    1. Git tag ellenorzese/letrehozasa (v1.0.0 formatum) + push
    2. Adatbazis mentes a szerveren (opcionalis)
    3. Fajlok masolasa Samba share-en at (.env, config.json, adatok kizarva)
    4. Staging -> docker munkakonyvtar + docker compose up -d --build SSH-n
    5. Ellenorzes (8085-os port, /health)

    A KRETA app elso elesitesekor az egyszeri adat-migracio a -MigrateLocalData
    kapcsoloval tortenik (lokalis DB + bongeszoprofil + csatolmanyok + config.json
    a szerver data kotetere, Samba h: meghajton at).
    A mentő cron telepitese: -InstallBackup (egyszeri).

.PARAMETER Release
    KOTELEZO: Az elesitendo verzio git tag-je (pl. v1.0.0)
.PARAMETER SkipBackup
    Adatbazis mentes kihagyasa
.PARAMETER WhatIf
    Csak listazza a masolando fajlokat, nem modosit semmit
.PARAMETER MigrateLocalData
    EGYSZERI: a lokalis adatok (DB, bongeszoprofil, csatolmanyok, config.json)
    felmasolasa a szerver data kotetere (h:\app\Kreta\data). Elotte ZARD BE a
    lokalis KRETA appot! (a DB-t nem szabad futas kozben masolni)
.PARAMETER InstallBackup
    EGYSZERI: a kreta_backup.sh telepitese a szerverre (HDD + docker-backup
    peldany) es a napi 3:00-as cron bejegyzes beallitasa (a log a mentesi
    konyvtarba kerul, a RabbitApp-pal egyezo minta)
.PARAMETER LinuxHost
    A tavoli gep hosztneve vagy IP-je (alapertelmezett: HPReiTam)
.PARAMETER SambaShare
    A Samba share eleresi utja (alapertelmezett: h:\_to_Docker\Kreta)
.PARAMETER SourceDir
    A forras (alapertelmezett: c:\ReiTam\AI\Gemini\Kreta)
.PARAMETER RemoteDir
    A tavoli docker munkakonyvtar (alapertelmezett: /mnt/work/Kreta)
.PARAMETER DataDir
    A data kotet a szerveren (DB + config.json + profil + csatolmanyok)
.PARAMETER BackupDir
    A mentesi konyvtar a szerveren

.EXAMPLE
    .\deploy.ps1 -Release v1.0.0 -MigrateLocalData -InstallBackup   # elso elesites
.EXAMPLE
    .\deploy.ps1 -Release v1.0.1
.EXAMPLE
    .\deploy.ps1 -Release v1.0.0 -WhatIf
#>

param(
    [Parameter(Mandatory=$true, HelpMessage="Az elesitendo verzio (pl. v1.0.0)")]
    [string]$Release,
    [switch]$SkipBackup,
    [switch]$WhatIf,
    [switch]$MigrateLocalData,
    [switch]$InstallBackup,
    [string]$LinuxHost = "HPReiTam",
    [string]$LinuxUser = "reitam",
    [string]$SambaShare = "h:\_to_Docker\Kreta",
    [string]$SambaDataShare = "h:\app\Kreta\data",
    [string]$SourceDir = "c:\ReiTam\AI\Gemini\Kreta",
    [string]$RemoteDir = "/mnt/work/Kreta",
    [string]$StagingDir = "/mnt/Maxxel_HDD/_to_Docker/Kreta",
    [string]$DataDir = "/mnt/Maxxel_HDD/app/Kreta/data",
    [string]$BackupDir = "/mnt/Maxxel_HDD/ReiTam_BackUp/Kreta_backup",
    [int]$Port = 8085
)

$ErrorActionPreference = "Stop"

# === Header =================================================================
Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "  KRETA Adatlekero Elesito Script" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "  Verzio:     $Release"
Write-Host "  Forras:     $SourceDir"
Write-Host "  Samba cel:  $SambaShare"
Write-Host "  Tavoli gep: $LinuxUser@$LinuxHost"
Write-Host "  Port:       $Port"
Write-Host "  Idopont:    $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host ""

# === Git tag ================================================================
Write-Host "[Git] Verzio tag ellenorzese/letrehozasa..." -ForegroundColor Yellow
Push-Location $SourceDir

if (-not (Test-Path ".git")) {
    Write-Host "  HIBA: A forraskonyvtar nem git repository: $SourceDir" -ForegroundColor Red
    Pop-Location
    exit 1
}

# PS 5.1-csapda: a git a normál előrehaladási kimenetét ("To https://...")
# stderr-re írja, ami a $ErrorActionPreference="Stop" + 2>&1 kombinációval
# NativeCommandError-ként ELHASÍTJA a scriptet (2026-10-28-i v1.0.1 deploy hiba).
# A git-hívások alatt ezért Continue-ra állítjuk az EAP-t, a sikert pedig a
# kilépőkódokból olvassuk.
$ErrorActionPreference = "Continue"
$gitStatus = git status --porcelain 2>&1
$gitStatusExit = $LASTEXITCODE
$existingTag = git tag -l $Release 2>&1
$ErrorActionPreference = "Stop"

if ($gitStatusExit -ne 0) {
    Write-Host "  HIBA: git status sikertelen. Biztos, hogy git van telepitve?" -ForegroundColor Red
    Pop-Location
    exit 1
}
if ($gitStatus) {
    Write-Host "  FIGYELEM: A munkakonyvtarban nem committolt valtozasok vannak!" -ForegroundColor DarkYellow
    Write-Host "  A tag a committolt allapotot jeloli, a masolas viszont a munkakonyvtar" -ForegroundColor DarkYellow
    Write-Host "  AKTUALIS tartalmat viszi. Commitold el, amit elesitesre szansz!" -ForegroundColor DarkYellow
    Write-Host $gitStatus
    Write-Host ""
}

if ($existingTag -eq $Release) {
    Write-Host "  Git tag '$Release' mar letezik, felhasznalva." -ForegroundColor Green
} else {
    if (-not $WhatIf) {
        $ErrorActionPreference = "Continue"
        $tagOut = git tag -a $Release -m "KRETA elesites: $Release - $(Get-Date -Format 'yyyy-MM-dd HH:mm')" 2>&1
        $tagExit = $LASTEXITCODE
        $ErrorActionPreference = "Stop"
        if ($tagExit -ne 0) {
            Write-Host "  HIBA: A git tag letrehozasa sikertelen!" -ForegroundColor Red
            Pop-Location
            exit 1
        }
        $ErrorActionPreference = "Continue"
        $pushOut = git push origin $Release 2>&1
        $pushExit = $LASTEXITCODE
        $ErrorActionPreference = "Stop"
        if ($pushExit -ne 0) {
            Write-Host "  FIGYELEM: A tag push-ja nem sikerult:" -ForegroundColor DarkYellow
            Write-Host ($pushOut -join "`n")
        } else {
            Write-Host "  Git tag letrehozva es push-olva: $Release" -ForegroundColor Green
        }
    } else {
        Write-Host "  WHAT-IF: git tag -a $Release letrehozas (kihagyva)" -ForegroundColor DarkCyan
    }
}
Pop-Location
Write-Host ""

# === 0. Elofeltetelek =======================================================
Write-Host "[0/6] Elofeltetelek ellenorzese..." -ForegroundColor Yellow

if (-not (Test-Path $SourceDir -PathType Container)) {
    Write-Host "  HIBA: A forras konyvtar nem talalhato: $SourceDir" -ForegroundColor Red
    exit 1
}
Write-Host "  Forras OK: $SourceDir" -ForegroundColor Green

if (-not (Test-Path $SambaShare -PathType Container)) {
    $sambaParent = Split-Path $SambaShare -Parent
    if (-not (Test-Path $sambaParent -PathType Container)) {
        Write-Host "  Samba share nem elerheto." -ForegroundColor Red
        Write-Host "  Eloszor mappeld (ha meg nincs):" -ForegroundColor DarkYellow
        Write-Host "    net use h: \\HPReiTam\HP_Share /user:$LinuxUser" -ForegroundColor White
        Write-Host "  (a h: meghajto a HP_Share-re mutat, abban a _to_Docker mappa)" -ForegroundColor DarkYellow
        exit 1
    }
    if (-not $WhatIf) {
        New-Item -ItemType Directory -Path $SambaShare -Force | Out-Null
        Write-Host "  Staging almappa letrehozva: $SambaShare" -ForegroundColor Green
    } else {
        Write-Host "  WHAT-IF: a staging almappa letrejon majd: $SambaShare" -ForegroundColor DarkCyan
    }
}
Write-Host "  Samba OK: $SambaShare" -ForegroundColor Green

if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
    Write-Host "  HIBA: Az OpenSSH kliens nincs telepitve." -ForegroundColor Red
    exit 1
}
Write-Host "  SSH kliens OK" -ForegroundColor Green
Write-Host ""

# === 0b. Egyszeri adat-migracio (-MigrateLocalData) =========================
if ($MigrateLocalData) {
    Write-Host "[Migracio] Lokalis adatok -> szerver data kotet (EGYSZERI)..." -ForegroundColor Yellow
    Write-Host "  Cel: $SambaDataShare  (= $DataDir a szerveren)" -ForegroundColor DarkGray
    Write-Host "  FIGYELEM: a lokalis KRETA app NEM futhat a masolas alatt!" -ForegroundColor DarkYellow

    # A share GYÖKERÉT ellenőrizzük (a h:\app\Kreta almappa lehet, hogy meg
    # nem letezik — a data konyvtarlancot alabb a New-Item -Force hozza letre)
    $shareRoot = (Split-Path $SambaDataShare -Qualifier) + "\"
    if (-not (Test-Path $shareRoot -PathType Container)) {
        Write-Host "  HIBA: a Samba share ($shareRoot) nem elerheto. Mappeld:" -ForegroundColor Red
        Write-Host "    net use h: \\HPReiTam\HP_Share /user:$LinuxUser" -ForegroundColor White
        exit 1
    }

    $migrateItems = @(
        @{ Src = (Join-Path $SourceDir "config.json");               Dst = (Join-Path $SambaDataShare "config.json") },
        @{ Src = (Join-Path $SourceDir "kreta_adatok.db");           Dst = (Join-Path $SambaDataShare "kreta_adatok.db") }
    )
    $migrateDirs = @(
        @{ Src = (Join-Path $SourceDir "browser_user_data");         Dst = (Join-Path $SambaDataShare "browser_user_data") },
        @{ Src = (Join-Path $SourceDir "static\csatolmanyok");       Dst = (Join-Path $SambaDataShare "csatolmanyok") }
    )

    if (-not (Test-Path $SambaDataShare)) {
        if ($WhatIf) {
            Write-Host "  WHAT-IF: a data almappa letrejon majd: $SambaDataShare" -ForegroundColor DarkCyan
        } else {
            New-Item -ItemType Directory -Path $SambaDataShare -Force | Out-Null
            Write-Host "  Data almappa letrehozva: $SambaDataShare" -ForegroundColor Green
        }
    }

    if ($WhatIf) {
        Write-Host "  WHAT-IF: fajlok es mappak masolasa kihagyva" -ForegroundColor DarkCyan
    } else {
        foreach ($item in $migrateItems) {
            if (Test-Path $item.Src) {
                Copy-Item -Path $item.Src -Destination $item.Dst -Force
                Write-Host "  Atmasolva: $($item.Src)" -ForegroundColor Green
            } else {
                Write-Host "  NEM talalhato (kihagyva): $($item.Src)" -ForegroundColor DarkYellow
            }
        }
        foreach ($dir in $migrateDirs) {
            if (Test-Path $dir.Src) {
                & robocopy $dir.Src $dir.Dst /E /NP /NDL /NJH /NJS /R:2 /W:3 | Out-Null
                if ($LASTEXITCODE -ge 8) {
                    Write-Host "  HIBA a masolasnal: $($dir.Src)" -ForegroundColor Red
                    exit 1
                }
                Write-Host "  Atmasolva: $($dir.Src)" -ForegroundColor Green
            } else {
                Write-Host "  NEM talalhato (kihagyva): $($dir.Src)" -ForegroundColor DarkYellow
            }
        }
        Write-Host "  Migracio kesz." -ForegroundColor Green
    }
    Write-Host ""
}

# === 1. Adatbazis mentes ====================================================
if (-not $SkipBackup) {
    Write-Host "[1/6] Adatbazis mentes (tavoli gepen)..." -ForegroundColor Yellow

    if ($WhatIf) {
        Write-Host "  WHAT-IF: a teljes mento szkript futtatasa a szerveren (kreta_backup.sh)" -ForegroundColor DarkCyan
    } else {
        Write-Host "  Csatlakozas: $LinuxUser@$LinuxHost (jelszo szukseges)"
        $backupCmd = "if [ -f '/home/reitam/docker-backup/kreta_backup.sh' ]; then sh '/home/reitam/docker-backup/kreta_backup.sh'; rc=`$?; elif [ -f '$BackupDir/kreta_backup.sh' ]; then sh '$BackupDir/kreta_backup.sh'; rc=`$?; elif [ -f '$DataDir/kreta_adatok.db' ]; then mkdir -p '$BackupDir' && cp '$DataDir/kreta_adatok.db' '$BackupDir/kreta_adatok_backup_`$(date +%Y-%m-%d_%H%M%S).db' 2>/dev/null; rc=`$?; else rc=0; echo '(meg nincs DB a szerveren - elso elesites)'; fi; echo DEPLOY_BACKUP_EXIT=`$rc"
        $backupOutput = cmd /c "C:\Windows\System32\OpenSSH\ssh.exe -o StrictHostKeyChecking=accept-new $LinuxUser@$LinuxHost ""$backupCmd"""
        Write-Host $backupOutput
        if ($backupOutput -match "DEPLOY_BACKUP_EXIT=0") {
            Write-Host "  Mentes kesz." -ForegroundColor Green
        } else {
            Write-Host "  FIGYELEM: a mentes nem sikerult (lasd fent)." -ForegroundColor DarkYellow
        }
    }
} else {
    Write-Host "[1/6] Adatbazis mentes KIHAGYVA (-SkipBackup)" -ForegroundColor DarkYellow
}
Write-Host ""

# === 2. Fajlok masolasa =====================================================
Write-Host "[2/6] Fajlok masolasa (data, .env, config.json kizarva)..." -ForegroundColor Yellow

$robocopyArgs = @(
    $SourceDir,
    $SambaShare,
    "/MIR",
    "/XD", ".git", "__pycache__", "browser_user_data", "static\csatolmanyok", ".claude",
    "/XF", ".env", "deploy.ps1", "config.json", "*.db", "sync.log", "KretaApp_Start.bat",
    # Csak fejlesztoi/dokumentacios fajlok — a futasidohoz nem kellenek, ezert
    # ne keruljenek at a szerver munkakonyvtaraba (a /MIR a kizart fajlokat
    # nem masolja; a korabban odakerult peldanyokat a szerveroldali tisztitas
    # torli).
    "README.md", "rendszerterv.md", "config.json.example", ".env.example",
    ".gitignore", ".gitattributes", "scheduler_state.json",
    "/NP", "/NDL", "/NJH", "/NJS",
    "/R:2", "/W:3", "/MT:4"
)

Write-Host "  robocopy $SourceDir -> $SambaShare"

# A korabbi deployokbol a stagingben maradt, futasidoben felesleges fajlok
# torlese (a /MIR a kizart neveket nem torli, ezert kulon kell).
$obsoleteNames = @("README.md", "rendszerterv.md", "config.json.example",
                   ".env.example", ".gitignore", ".gitattributes", "scheduler_state.json")
if (-not $WhatIf) {
    foreach ($name in $obsoleteNames) {
        $stale = Join-Path $SambaShare $name
        if (Test-Path $stale) {
            Remove-Item $stale -Force
            Write-Host "  Torolve (staging): $name" -ForegroundColor DarkGray
        }
    }
    # A csatolmányok Dockerben a data koteten vannak (/app/data/csatolmanyok),
    # a munkakonyvtarban levo masolat 2,7 MB felesleg — a .dockerignore is
    # kizarja a kepbol.
    $staleAttachments = Join-Path $SambaShare "static\csatolmanyok"
    if (Test-Path $staleAttachments) {
        Remove-Item $staleAttachments -Recurse -Force
        Write-Host "  Torolve (staging): static\csatolmanyok" -ForegroundColor DarkGray
    }
}

if ($WhatIf) {
    $robocopyArgs += "/L"
    Write-Host "  (WHAT-IF mod: csak listazas, nem modosit)" -ForegroundColor DarkCyan
}

$robocopyResult = & robocopy @robocopyArgs
$robocopyExit = $LASTEXITCODE

if ($robocopyExit -ge 8) {
    Write-Host "  HIBA: robocopy hibaval tert vissza (exit: $robocopyExit)" -ForegroundColor Red
    exit 1
}

$changedFiles = $robocopyResult | Select-String -Pattern "^\s*(New|Newer|Extra)" | Measure-Object | Select-Object -ExpandProperty Count
Write-Host "  Valtozott fajlok szama: ~$changedFiles" -ForegroundColor Green
Write-Host "  Fajlok atmasolva." -ForegroundColor Green
Write-Host ""

# === 3-6. Tavoli muveletek SSH-n ============================================
if (-not $WhatIf) {
    Write-Host "[3-6/6] Tavoli muveletek SSH-n keresztul..." -ForegroundColor Yellow
    Write-Host "  Csatlakozas: $LinuxUser@$LinuxHost (jelszo szukseges)"
    Write-Host "============================================================" -ForegroundColor DarkGray

    $installBackupSh = ""
    if ($InstallBackup) {
        $installBackupSh = @'

echo "===[ MENTO SZKRIPT TELEPITESE (-InstallBackup) ]==="
mkdir -p /home/reitam/docker-backup BACKUP_DIR_PLACEHOLDER
cp -f REMOTE_DIR_PLACEHOLDER/backup/kreta_backup.sh /home/reitam/docker-backup/kreta_backup.sh
cp -f REMOTE_DIR_PLACEHOLDER/backup/kreta_backup.sh BACKUP_DIR_PLACEHOLDER/kreta_backup.sh
chmod +x /home/reitam/docker-backup/kreta_backup.sh BACKUP_DIR_PLACEHOLDER/kreta_backup.sh
( crontab -l 2>/dev/null | grep -v 'kreta_backup.sh'; \
  echo '0 3 * * * /home/reitam/docker-backup/kreta_backup.sh >> /mnt/Maxxel_HDD/ReiTam_BackUp/Kreta_backup/kretabackup.log 2>&1' ) | crontab -
echo "Cron bejegyzesek:"
crontab -l | grep -E 'kreta|rabbit' || echo "(nincs cron bejegyzes?)"

'@
    }

    $deploySh = @'
echo "===[ STAGING MASOLAS ]==="
STAGING_COUNT=$(find STAGING_DIR_PLACEHOLDER -type f 2>/dev/null | wc -l)
echo "Staging fajlok szama: $STAGING_COUNT"
if [ "$STAGING_COUNT" -gt 0 ]; then
    # A szerver .env-je szent: a stagingben levo (regi) peldany nem irhatja felul
    cp -f REMOTE_DIR_PLACEHOLDER/.env /tmp/kreta_env_backup 2>/dev/null
    mkdir -p REMOTE_DIR_PLACEHOLDER || { echo "HIBA: a munkakonyvtar nem hozhato letre: REMOTE_DIR_PLACEHOLDER"; exit 1; }
    # -r es nem -a: tulajdonos/idobelyeg orzes nelkul (NTFS mount-on ugyis hibazna)
    cp -rf STAGING_DIR_PLACEHOLDER/. REMOTE_DIR_PLACEHOLDER/ || { echo "HIBA: a masolas nem sikerult"; exit 1; }
    echo OK
    cp -f /tmp/kreta_env_backup REMOTE_DIR_PLACEHOLDER/.env 2>/dev/null
    rm -f /tmp/kreta_env_backup
    if [ ! -f REMOTE_DIR_PLACEHOLDER/.env ]; then
        echo "APP_ENVIRONMENT=PROD" > REMOTE_DIR_PLACEHOLDER/.env
        echo "A szerver .env letrehozva (APP_ENVIRONMENT=PROD)"
    fi
else
    echo "HIBA: a staging ures - nincs mit elesiteni!"
    exit 1
fi

echo ""
echo "===[ FELESLEGES FAJLOK TISZTITASA (munkakonyvtar) ]==="
# A cp -rf nem torol, ezert a korabbi deployok docs/example fajljai itt
# maradnanak — ezekre futasidoben nincs szukseg.
rm -f REMOTE_DIR_PLACEHOLDER/README.md \
      REMOTE_DIR_PLACEHOLDER/rendszerterv.md \
      REMOTE_DIR_PLACEHOLDER/config.json.example \
      REMOTE_DIR_PLACEHOLDER/.env.example \
      REMOTE_DIR_PLACEHOLDER/.gitignore \
      REMOTE_DIR_PLACEHOLDER/.gitattributes \
      REMOTE_DIR_PLACEHOLDER/scheduler_state.json
# A csatolmányok az eles kornyezetben a data koteten vannak
# (/app/data/csatolmanyok), a munkakonyvtar static/csatolmanyok masolata
# felesleges (a .dockerignore is kizarja a kepbol).
rm -rf REMOTE_DIR_PLACEHOLDER/static/csatolmanyok
echo OK

echo ""
echo "===[ DATA / BACKUP KONYVTARAK ]==="
mkdir -p DATA_DIR_PLACEHOLDER BACKUP_DIR_PLACEHOLDER
echo OK

echo ""
echo "===[ ELO ELEK ELSO ELESITESHEZ ]==="
if [ ! -f DATA_DIR_PLACEHOLDER/config.json ]; then
    echo "FIGYELEM: a szerveren NINCS config.json a data kotetben!"
    echo "  Egyszeri beallitas (lokalis gepen):"
    echo "    copy c:\\ReiTam\\AI\\Gemini\\Kreta\\config.json h:\\app\\Kreta\\data\\config.json"
    echo "  vagy a deploy.ps1 -MigrateLocalData kapcsoloja."
fi
if [ ! -f DATA_DIR_PLACEHOLDER/kreta_adatok.db ]; then
    echo "FIGYELEM: a szerveren NINCS meg DB - a kontener URES adatbazissal indul."
    echo "  A lokalis elozmenyek atvetelere (egyszeri): deploy.ps1 -MigrateLocalData"
fi

echo ""
echo "===[ DOCKER COMPOSE UP -d --build ]==="
cd REMOTE_DIR_PLACEHOLDER
docker compose up -d --build 2>&1
DOCKER_EXIT=$?

echo "RELEASE_PLACEHOLDER" > DATA_DIR_PLACEHOLDER/version.txt
echo "RELEASE_PLACEHOLDER deployed $(date '+%F %T')" >> DATA_DIR_PLACEHOLDER/deploy.log

echo ""
if grep -q 'APP_ENVIRONMENT=PROD' REMOTE_DIR_PLACEHOLDER/.env 2>/dev/null; then
    echo "APP_ENVIRONMENT=PROD OK"
else
    echo "FIGYELMEZTETES: .env-ben nincs APP_ENVIRONMENT=PROD!"
fi

echo ""
echo "===[ VARAKOZAS (15mp) ]==="
sleep 15

echo ""
echo "===[ KONTENER ALLAPOT ]==="
docker compose ps 2>&1

echo ""
echo "===[ HTTP ELLENORZES ]==="
HTTP=$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 5 http://localhost:PORT_PLACEHOLDER/health 2>&1)
echo "HTTP valasz: $HTTP"
if [ "$HTTP" = "200" ]; then
    echo "SIKERES!"
else
    echo "FIGYELEM: nem 200 OK (elso elesitesnel a kep epitese percekig tarthat)"
fi

echo ""
echo "===[ UTOLSO DEPLOY ]==="
tail -1 DATA_DIR_PLACEHOLDER/deploy.log 2>/dev/null

echo ""
echo "===[ KESZ ]==="
exit $DOCKER_EXIT
'@

    $deploySh = $deploySh.Replace('STAGING_DIR_PLACEHOLDER', $StagingDir)
    $deploySh = $deploySh.Replace('REMOTE_DIR_PLACEHOLDER', $RemoteDir)
    $deploySh = $deploySh.Replace('DATA_DIR_PLACEHOLDER', $DataDir)
    $deploySh = $deploySh.Replace('BACKUP_DIR_PLACEHOLDER', $BackupDir)
    $deploySh = $deploySh.Replace('RELEASE_PLACEHOLDER', $Release)
    $deploySh = $deploySh.Replace('PORT_PLACEHOLDER', "$Port")

    if ($InstallBackup) {
        $installBackupSh = $installBackupSh.Replace('REMOTE_DIR_PLACEHOLDER', $RemoteDir)
        $installBackupSh = $installBackupSh.Replace('BACKUP_DIR_PLACEHOLDER', $BackupDir)
        # A mento telepites a staging masolas UTAN fusson (friss szkript)
        $deploySh = $deploySh -replace 'echo "===\[ DATA / BACKUP KONYVTARAK \]==="', ($installBackupSh + 'echo "===[ DATA / BACKUP KONYVTARAK ]==="')
    }

    # LF sorelvalasztok kellenek (bash), ASCII kodolas
    $tmpSh = [System.IO.Path]::GetTempFileName() + ".sh"
    $deploySh = $deploySh -replace "`r`n", "`n"
    [System.IO.File]::WriteAllText($tmpSh, $deploySh + "`n", [System.Text.Encoding]::ASCII)

    $tmpBat = [System.IO.Path]::GetTempFileName() + ".bat"
    $batContent = "@echo off`r`nC:\Windows\System32\OpenSSH\ssh.exe -t -o StrictHostKeyChecking=accept-new $LinuxUser@$LinuxHost ""bash -s"" < ""$tmpSh""`r`n"
    $batContent | Out-File -FilePath $tmpBat -Encoding ascii

    cmd /c $tmpBat
    $sshExit = $LASTEXITCODE
    Remove-Item $tmpSh, $tmpBat -Force -ErrorAction SilentlyContinue

    Write-Host ""
    Write-Host "============================================================" -ForegroundColor DarkGray
    if ($sshExit -eq 0) {
        Write-Host "  Elesites befejezve." -ForegroundColor Green
    } else {
        Write-Host "  SSH/docker hibaval tert vissza (exit: $sshExit)" -ForegroundColor DarkYellow
        Write-Host "  Ellenorizd a fenti kimenetet!" -ForegroundColor DarkYellow
    }
    Write-Host ""
} else {
    Write-Host "[3/6] Staging masolasa... (WHAT-IF)" -ForegroundColor DarkCyan
    Write-Host "[4/6] Docker compose up -d --build... (WHAT-IF)" -ForegroundColor DarkCyan
    Write-Host "[5/6] Ellenorzes a $Port porton... (WHAT-IF)" -ForegroundColor DarkCyan
}

# === Osszegzes ==============================================================
$appUrl = "http://$LinuxHost" + ":$Port"
Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "  Elesites kesz!" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "  Alkalmazas:   $appUrl" -ForegroundColor White
Write-Host "  Verzio:       $Release" -ForegroundColor White
Write-Host "  A LOKALIS (Windows) appot ezentul csak tesztelesre hasznald," -ForegroundColor DarkGray
Write-Host "  eles kornyezet a szerveren van!" -ForegroundColor DarkGray
Write-Host ""
