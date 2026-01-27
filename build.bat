@echo off
echo ================================================
echo  Vortex CLI Build Script (NASM + MinGW-w64)
echo ================================================
echo.

REM Set NASM path (adjust if different)
set NASM_PATH="C:\Program Files\NASM\nasm.exe"

echo [1/2] Assembling with NASM...
%NASM_PATH% -f win64 main.asm -o main.obj
if %errorlevel% neq 0 (
    echo NASM assembly failed!
    goto :error
)

echo [2/2] Linking with GCC...
gcc -o main.exe main.obj -lkernel32 -mconsole -no-pie
if %errorlevel% neq 0 (
    echo GCC linking failed!
    goto :error
)

echo.
echo ================================================
echo  BUILD SUCCESSFUL!
echo  Run: main.exe
echo ================================================
goto :end

:error
echo.
echo BUILD FAILED!
pause
exit /b 1

:end
pause
