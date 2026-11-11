# Lädt alle Werkzeuge, die mit Ordnungsliebe ausgeliefert werden, nach .\tools
#  - llama.cpp (llama-server, Vulkan-Fassung: läuft auf NVIDIA, AMD, Intel und notfalls ohne Grafikkarte)
#  - Tesseract-Sprachdaten (Deutsch, Englisch) für die Texterkennung in PyMuPDF
#  - LibreOffice (für Vorschau und Text von Word/Excel-Dateien)
#  - WebView2-Bootstrapper (falls auf älteren Windows-10-PCs die Anzeige fehlt)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$root = Split-Path -Parent $PSScriptRoot
$tools = Join-Path $root "tools"
$deps = Join-Path $root "deps"
New-Item -ItemType Directory -Force -Path $tools, $deps | Out-Null

function Get-File($url, $out) {
    Write-Host "Lade $url"
    for ($i = 1; $i -le 4; $i++) {
        try { Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing; return }
        catch { Write-Host "  Versuch $i fehlgeschlagen: $_"; Start-Sleep -Seconds (5 * $i) }
    }
    throw "Download fehlgeschlagen: $url"
}

# --- llama.cpp ------------------------------------------------------------------------
$llamaDir = Join-Path $tools "llama"
if (-not (Test-Path (Join-Path $llamaDir "llama-server.exe"))) {
    $zip = Join-Path $deps "llama.zip"
    $tag = $env:LLAMA_TAG
    if (-not $tag) { $tag = (gh release view --repo ggml-org/llama.cpp --json tagName -q .tagName) }
    Write-Host "llama.cpp Version: $tag"
    gh release download $tag --repo ggml-org/llama.cpp --pattern "*bin-win-vulkan-x64.zip" --output $zip --clobber
    if (-not (Test-Path $zip)) { throw "llama.cpp-Paket nicht gefunden" }
    $tmp = Join-Path $deps "llama-x"
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    Expand-Archive $zip -DestinationPath $tmp
    $server = Get-ChildItem -Path $tmp -Recurse -Filter "llama-server.exe" | Select-Object -First 1
    if (-not $server) { throw "llama-server.exe fehlt im Paket" }
    New-Item -ItemType Directory -Force -Path $llamaDir | Out-Null
    Copy-Item -Path (Join-Path $server.DirectoryName "*") -Destination $llamaDir -Recurse -Force
    # Nicht benötigte Programme entfernen (spart Platz), Laufzeitbibliotheken behalten
    Get-ChildItem $llamaDir -Filter "*.exe" | Where-Object { $_.Name -ne "llama-server.exe" } | Remove-Item -Force
    foreach ($dll in "vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll") {
        $src = Join-Path $env:WINDIR "System32\$dll"
        if ((Test-Path $src) -and -not (Test-Path (Join-Path $llamaDir $dll))) { Copy-Item $src $llamaDir }
    }
    "$tag" | Out-File -Encoding ascii (Join-Path $llamaDir "VERSION.txt")
}

# --- Tesseract-Sprachdaten --------------------------------------------------------------
$td = Join-Path $tools "tessdata"
New-Item -ItemType Directory -Force -Path $td | Out-Null
foreach ($lang in "deu", "eng", "osd") {
    $f = Join-Path $td "$lang.traineddata"
    if (-not (Test-Path $f)) { Get-File "https://raw.githubusercontent.com/tesseract-ocr/tessdata/main/$lang.traineddata" $f }
}

# --- LibreOffice ---------------------------------------------------------------------------
$loDir = Join-Path $tools "libreoffice"
if (-not (Test-Path (Join-Path $loDir "program\soffice.exe"))) {
    $base = "https://download.documentfoundation.org/libreoffice/stable/"
    $ver = $env:LO_VERSION
    if (-not $ver) {
        $listing = (Invoke-WebRequest -Uri $base -UseBasicParsing).Content
        $ver = ([regex]::Matches($listing, 'href="(\d+\.\d+\.\d+)/"') | ForEach-Object { $_.Groups[1].Value } |
                Sort-Object { [version]$_ } | Select-Object -Last 1)
    }
    Write-Host "LibreOffice Version: $ver"
    $msi = Join-Path $deps "LibreOffice.msi"
    Get-File "$base$ver/win/x86_64/LibreOffice_${ver}_Win_x86-64.msi" $msi
    $admin = Join-Path $deps "lo-admin"
    Remove-Item -Recurse -Force $admin -ErrorAction SilentlyContinue
    $p = Start-Process msiexec.exe -ArgumentList "/a `"$msi`" /qn TARGETDIR=`"$admin`"" -Wait -PassThru
    if ($p.ExitCode -ne 0) { throw "LibreOffice konnte nicht entpackt werden (Code $($p.ExitCode))" }
    $soffice = Get-ChildItem -Path $admin -Recurse -Filter "soffice.exe" | Select-Object -First 1
    if (-not $soffice) { throw "soffice.exe nicht gefunden" }
    $loRoot = Split-Path -Parent $soffice.DirectoryName
    New-Item -ItemType Directory -Force -Path $loDir | Out-Null
    Copy-Item -Path (Join-Path $loRoot "*") -Destination $loDir -Recurse -Force
    # Für die reine Umwandlung nicht benötigte Teile entfernen
    foreach ($d in "help", "readmes", "share\gallery", "share\template", "share\extensions", "sdk") {
        Remove-Item -Recurse -Force (Join-Path $loDir $d) -ErrorAction SilentlyContinue
    }
}

# --- WebView2-Bootstrapper -------------------------------------------------------------
$wv = Join-Path $deps "MicrosoftEdgeWebview2Setup.exe"
if (-not (Test-Path $wv)) { Get-File "https://go.microsoft.com/fwlink/p/?LinkId=2124703" $wv }

Get-ChildItem $tools | ForEach-Object {
    $size = (Get-ChildItem $_.FullName -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB
    Write-Host ("{0,-14} {1,8:N0} MB" -f $_.Name, $size)
}
