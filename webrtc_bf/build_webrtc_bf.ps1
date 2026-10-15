# build_webrtc_bf.ps1 — 在 bfbuild (MinGW-w64) conda 环境下编译 webrtc_bf.dll
#
# 产物: ..\lib\webrtc_bf.dll  (静态链接 libgcc/libstdc++, 不依赖 MinGW 运行时)
#
# 前置: 已创建 bfbuild 环境, 例如
#   conda create -y -n bfbuild -c msys2 -c conda-forge m2w64-toolchain m2w64-make cmake ninja
#
# 用法:
#   powershell -ExecutionPolicy Bypass -File build_webrtc_bf.ps1
#   可选: -WebRTCRoot <path>  指定 webrtc 源码根 (含 webrtc/webrtc/base/...)

param(
    [string]$EnvPrefix = "C:\Users\marky\.conda\envs\bfbuild",
    [string]$WebRTCRoot = "D:\project\prjSE\src\BF\webrtc_nbf\mic2_bf\webrtc",
    [string]$BuildDir = ""
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $BuildDir) { $BuildDir = Join-Path $here "build" }

# --- 定位工具链 ---
function Find-First($paths, $name) {
    foreach ($p in $paths) {
        $f = Join-Path $p $name
        if (Test-Path $f) { return $f }
    }
    return $null
}
$bindirs = @(
    (Join-Path $EnvPrefix "Library\mingw-w64\bin"),
    (Join-Path $EnvPrefix "Library\bin"),
    (Join-Path $EnvPrefix "Library\usr\bin"),
    (Join-Path $EnvPrefix "Scripts"),
    (Join-Path $EnvPrefix "bin")
)
$gcc   = Find-First $bindirs "gcc.exe"
$gxx   = Find-First $bindirs "g++.exe"
$cmake = Find-First $bindirs "cmake.exe"
$ninja = Find-First $bindirs "ninja.exe"
$mingwmake = Find-First $bindirs "mingw32-make.exe"

if (-not $cmake) { throw "未找到 cmake.exe (检查环境 $EnvPrefix)" }
if (-not $gcc -or -not $gxx) { throw "未找到 gcc/g++ (m2w64-toolchain)" }

# 让编译器能在 PATH 中找到 as/ld 等 binutils 与运行时头
$env:PATH = ($bindirs -join ";") + ";" + $env:PATH

Write-Host "[build] gcc   = $gcc"
Write-Host "[build] g++   = $gxx"
Write-Host "[build] cmake = $cmake"
Write-Host "[build] ninja = $ninja"
Write-Host "[build] WEBRTC_ROOT = $WebRTCRoot"
Write-Host "[build] build dir   = $BuildDir"

# --- 配置 ---
$genArgs = @()
if ($ninja) {
    $genArgs += @("-G", "Ninja", "-DCMAKE_MAKE_PROGRAM=$ninja")
} else {
    if (-not $mingwmake) { throw "未找到 ninja 或 mingw32-make" }
    $genArgs += @("-G", "MinGW Makefiles", "-DCMAKE_MAKE_PROGRAM=$mingwmake")
}

& $cmake @genArgs `
    -DCMAKE_BUILD_TYPE=Release `
    -DCMAKE_C_COMPILER="$gcc" `
    -DCMAKE_CXX_COMPILER="$gxx" `
    -DWEBRTC_ROOT="$($WebRTCRoot -replace '\\','/')" `
    -S "$here" -B "$BuildDir"
if ($LASTEXITCODE -ne 0) { throw "cmake 配置失败" }

# --- 编译 ---
& $cmake --build "$BuildDir" --config Release -j
if ($LASTEXITCODE -ne 0) { throw "编译失败" }

$dll = Join-Path $here "..\lib\webrtc_bf.dll"
Write-Host "[build] 完成: $dll  存在=$(Test-Path $dll)"
