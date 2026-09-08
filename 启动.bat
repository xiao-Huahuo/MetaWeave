@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

rem 启动.bat
rem 用法:
rem   双击本文件,或在项目根目录执行: 启动.bat
rem 功能:
rem   1. 按端口关闭已经存在的 MetaWeave 后端、gRPC 和前端开发服务。
rem   2. 分别打开新的命令行窗口启动后端 main.py 和前端 Electron dev server。
rem 可选环境变量:
rem   AGENT_HTTP_PORT 覆盖后端 HTTP 端口,默认 8002。
rem   AGENT_GRPC_PORT 覆盖后端 gRPC 端口,默认 50051。
rem   FRONTEND_PORT 覆盖前端 Vite 端口,默认 5173。

set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

if not defined AGENT_HTTP_PORT set "AGENT_HTTP_PORT=8002"
if not defined AGENT_GRPC_PORT set "AGENT_GRPC_PORT=50051"
if not defined FRONTEND_PORT set "FRONTEND_PORT=5173"

echo ==========================================
echo   MetaWeave restart
echo   Project: %PROJECT_ROOT%
echo   Backend HTTP: %AGENT_HTTP_PORT%
echo   Backend gRPC: %AGENT_GRPC_PORT%
echo   Frontend: %FRONTEND_PORT%
echo ==========================================
echo.

call :kill_port "%AGENT_HTTP_PORT%" "backend-http"
if errorlevel 1 goto :startup_failed
call :kill_port "%AGENT_GRPC_PORT%" "backend-grpc"
if errorlevel 1 goto :startup_failed
call :kill_port "%FRONTEND_PORT%" "frontend-vite"
if errorlevel 1 goto :startup_failed

set "BACKEND_URL=http://127.0.0.1:%AGENT_HTTP_PORT%"
set "FRONTEND_URL=http://127.0.0.1:%FRONTEND_PORT%"
set "METAWEAVE_BACKEND_URL=%BACKEND_URL%"
set "VITE_DEV_PROXY_TARGET=%BACKEND_URL%"
set "ELECTRON_RENDERER_URL=%FRONTEND_URL%"
set "VITE_PORT=%FRONTEND_PORT%"

echo.
echo Starting backend...
start "MetaWeave Backend" cmd /k "cd /d ""%PROJECT_ROOT%"" && python main.py"

echo Waiting for backend health...
node "%PROJECT_ROOT%\editor\electron\server-readiness.cjs" "%BACKEND_URL%/health" 120000 metaweave
if errorlevel 1 (
  echo Backend failed to become healthy: %BACKEND_URL%/health
  goto :startup_failed
)

echo Starting frontend electron...
start "MetaWeave Frontend Electron" cmd /k "cd /d ""%PROJECT_ROOT%\editor"" && npm run dev:electron"

echo.
echo Restart commands have been issued.
echo Backend:  http://127.0.0.1:%AGENT_HTTP_PORT%
echo Frontend dev server: http://127.0.0.1:%FRONTEND_PORT%
echo.
pause
exit /b 0

:startup_failed
echo.
echo MetaWeave startup aborted. Review the error above and the service window output.
pause
exit /b 1

:kill_port
set "TARGET_PORT=%~1"
set "TARGET_NAME=%~2"
set "KILLED_ANY=0"
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%TARGET_PORT% .*LISTENING"') do (
  if not "%%P"=="0" (
    echo Closing %TARGET_NAME% on port %TARGET_PORT% ^(PID %%P^)...
    taskkill /F /PID %%P >nul 2>nul
    if errorlevel 1 (
      echo Failed to stop %TARGET_NAME% process PID %%P.
      exit /b 1
    )
    set "KILLED_ANY=1"
  )
)
if "%KILLED_ANY%"=="0" echo No existing %TARGET_NAME% service found on port %TARGET_PORT%.
exit /b 0
