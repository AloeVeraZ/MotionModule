# MotionModule demo: the robot dashboard on this computer, with a simulated robot.
#
# Paste into Windows PowerShell:
#
#   irm https://raw.githubusercontent.com/AloeVeraZ/MotionModule/testing/demo.ps1 | iex
#
# It downloads MotionModule, sets up Python for it, and opens the dashboard in
# your browser. No Raspberry Pi is needed and nothing on the computer is
# changed outside its own folder. Run it again to get the latest version; if
# there is no internet, it reuses the last download.
#
# Inside a clone of the repository, run .\demo.ps1 instead. That copy is used
# as it is, so changes to the dashboard show up the next time the demo starts.
#
# Optional settings, as environment variables set before the command:
#   MOTIONMODULE_DEMO_BRANCH   branch to download (default: testing)
#   MOTIONMODULE_DEMO_PORT     first port to try (default: 8080)
#   MOTIONMODULE_DEMO_HOST     0.0.0.0 to open it from a phone on the same Wi-Fi
#   MOTIONMODULE_DEMO_HOME     folder for the download and Python environment
#                              (default: %LOCALAPPDATA%\MotionModule\demo)
#
# This file is plain ASCII so Windows PowerShell 5.1 reads it correctly.

& {
    $ErrorActionPreference = 'Stop'
    $ProgressPreference = 'SilentlyContinue'   # a progress bar makes downloads many times slower
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

    function Say([string]$Text) { Write-Host "[MotionModule demo] $Text" -ForegroundColor Cyan }

    function Find-Python {
        # A missing interpreter, or the Microsoft Store placeholder that only
        # prints advice, writes to stderr and fails; neither may stop the search.
        $ErrorActionPreference = 'Continue'
        $candidates = @(
            @{ Exe = 'py'; Args = @('-3.13') }, @{ Exe = 'py'; Args = @('-3.12') },
            @{ Exe = 'py'; Args = @('-3.11') }, @{ Exe = 'py'; Args = @('-3') },
            @{ Exe = 'python'; Args = @() }, @{ Exe = 'python3'; Args = @() }
        )
        # A Python that winget installed moments ago is not on this session's PATH yet.
        $installed = Join-Path $env:LOCALAPPDATA 'Programs\Python'
        if (Test-Path $installed) {
            Get-ChildItem -Path $installed -Filter 'Python3*' -Directory | Sort-Object Name -Descending | ForEach-Object {
                $exe = Join-Path $_.FullName 'python.exe'
                if (Test-Path $exe) { $candidates += @{ Exe = $exe; Args = @() } }
            }
        }
        foreach ($candidate in $candidates) {
            if (-not (Get-Command $candidate.Exe -ErrorAction SilentlyContinue)) { continue }
            $arguments = @($candidate.Args)
            $version = & $candidate.Exe @arguments -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($LASTEXITCODE -eq 0 -and "$version" -match '^3\.(\d+)$' -and [int]$Matches[1] -ge 11) {
                return [pscustomobject]@{ Exe = $candidate.Exe; Args = $arguments; Version = "$version" }
            }
        }
        return $null
    }

    $branch = if ($env:MOTIONMODULE_DEMO_BRANCH) { $env:MOTIONMODULE_DEMO_BRANCH } else { 'testing' }
    $port = if ($env:MOTIONMODULE_DEMO_PORT) { $env:MOTIONMODULE_DEMO_PORT } else { '8080' }
    $bindHost = if ($env:MOTIONMODULE_DEMO_HOST) { $env:MOTIONMODULE_DEMO_HOST } else { '127.0.0.1' }
    $data = if ($env:MOTIONMODULE_DEMO_HOME) { $env:MOTIONMODULE_DEMO_HOME } else { Join-Path $env:LOCALAPPDATA 'MotionModule\demo' }
    $previousPythonPath = $env:PYTHONPATH

    try {
        New-Item -ItemType Directory -Force -Path $data | Out-Null

        # ---- the MotionModule files: this clone, or a fresh download --------
        if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot 'core\motion_module\demo.py'))) {
            $source = $PSScriptRoot
            Say "Using this copy of MotionModule: $source"
        } else {
            $safeBranch = $branch -replace '[^A-Za-z0-9._-]', '-'
            $source = Join-Path $data "source-$safeBranch"
            $zip = Join-Path $data "download-$safeBranch.zip"
            $staging = Join-Path $data "staging-$safeBranch"
            Say "Downloading the $branch branch of MotionModule..."
            try {
                Invoke-WebRequest -UseBasicParsing -Uri "https://codeload.github.com/AloeVeraZ/MotionModule/zip/refs/heads/$branch" -OutFile $zip
                if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
                Expand-Archive -Path $zip -DestinationPath $staging -Force
                $inner = Get-ChildItem -Path $staging -Directory | Select-Object -First 1
                if (-not $inner -or -not (Test-Path (Join-Path $inner.FullName 'core\motion_module\demo.py'))) {
                    throw "The $branch branch does not include the demo."
                }
                if (Test-Path $source) { Remove-Item -Recurse -Force $source }
                Move-Item -Path $inner.FullName -Destination $source
            } catch {
                if (Test-Path (Join-Path $source 'core\motion_module\demo.py')) {
                    Say "Could not download $branch ($($_.Exception.Message)). Using the copy from last time."
                } else {
                    throw "Could not download the $branch branch: $($_.Exception.Message)"
                }
            } finally {
                Remove-Item -Force -ErrorAction SilentlyContinue $zip
                Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $staging
            }
        }

        # ---- Python 3.11 or newer -------------------------------------------
        $python = Find-Python
        if (-not $python -and (Get-Command winget -ErrorAction SilentlyContinue)) {
            $answer = Read-Host 'Python 3.11 or newer is needed. Install Python 3.12 for this user with winget now? [Y/n]'
            if ($answer -eq '' -or $answer -match '^[Yy]') {
                winget install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements
                $python = Find-Python
            }
        }
        if (-not $python) {
            throw "Python 3.11 or newer is needed. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then run this command again."
        }

        $venv = Join-Path $data 'venv'
        $venvPython = Join-Path $venv 'Scripts\python.exe'
        if (-not (Test-Path $venvPython)) {
            Say "Setting up Python $($python.Version) for the demo (first run only)..."
            $arguments = @($python.Args)
            & $python.Exe @arguments -m venv $venv
            if ($LASTEXITCODE -ne 0) { throw 'Could not create a Python environment for the demo.' }
        }
        Say 'Checking Flask and the other requirements...'
        & $venvPython -m pip install --disable-pip-version-check --quiet -r (Join-Path $source 'requirements.txt')
        if ($LASTEXITCODE -ne 0) { throw 'Could not install the requirements. Check the internet connection and try again.' }

        # ---- run it ----------------------------------------------------------
        $env:PYTHONPATH = Join-Path $source 'core'
        Say 'Starting the dashboard with a simulated robot. Press Ctrl+C to stop.'
        & $venvPython -m motion_module.demo --host $bindHost --port $port
    } catch {
        Write-Host "[MotionModule demo] $($_.Exception.Message)" -ForegroundColor Red
    } finally {
        $env:PYTHONPATH = $previousPythonPath
    }
}
