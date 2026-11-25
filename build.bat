@echo off
setlocal enabledelayedexpansion
chcp 65001 > nul

cd /d "%~dp0"
set "LOG_FILE=%~dp0build_log.txt"

echo =================================================== > "%LOG_FILE%"
echo   SimpleTimer ビルドログ (%date% %time%) >> "%LOG_FILE%"
echo =================================================== >> "%LOG_FILE%"

echo ===================================================
echo   SimpleTimer ビルド処理（詳細ログ出力モード）
echo   ※画面をクリックして選択状態になると一時停止します。
echo    停止した場合は「Enter」または「Space」を押してください。
echo ===================================================
echo.

:: --- ログ記録用サブルーチン呼び出し ---
call :WRITE_LOG "[1/6] Python本体の検出を開始します..."
where python >> "%LOG_FILE%" 2>&1
python --version >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    call :WRITE_LOG "[エラー] Pythonが見つかりません。環境変数PATHを確認してください。"
    goto FAILED
)
call :WRITE_LOG "[1/6 完了] Python本体を確認しました。"

:: --- 仮想環境チェック ---
call :WRITE_LOG "[2/6] 仮想環境 (.venv) を確認しています..."
if not exist ".venv\Scripts\python.exe" (
    call :WRITE_LOG ".venv が存在しないため、新規作成を実行します..."
    python -m venv .venv >> "%LOG_FILE%" 2>&1
    if errorlevel 1 (
        call :WRITE_LOG "[エラー] 仮想環境の作成に失敗しました。"
        goto FAILED
    )
    call :WRITE_LOG ".venv の作成が完了しました。"
) else (
    call :WRITE_LOG "既存の .venv を検出しました。"
)
call :WRITE_LOG "[2/6 完了] 仮想環境の準備が整いました。"

:: --- インストール済みライブラリの事前検証 ---
call :WRITE_LOG "[3/6] 必要なライブラリの導入状況を検証します..."
".venv\Scripts\python.exe" -c "import pystray; import PIL; import PyInstaller; print('ALL_OK')" >> "%LOG_FILE%" 2>&1
if "%errorlevel%"=="0" (
    call :WRITE_LOG "[3/6 完了] 必要なライブラリはすべて導入済みです。外部通信(pip)をスキップします。"
    goto BUILD_STEP
)

:: --- pip インストール（15秒タイムアウト設定） ---
call :WRITE_LOG "[3/6 実行中] 不足ライブラリをインストールします（タイムアウト15秒制限）..."
echo ネットワーク接続中... (ログは build_log.txt にリアルタイム追記されます)
".venv\Scripts\python.exe" -m pip install --timeout 15 pystray Pillow pyinstaller >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    call :WRITE_LOG "[エラー] パッケージのインストールに失敗しました。"
    call :WRITE_LOG "庁内LAN/プロキシによる遮断、または通信タイムアウトの可能性があります。"
    goto FAILED
)
call :WRITE_LOG "[3/6 完了] ライブラリのインストールが完了しました。"

:BUILD_STEP
:: --- PyInstaller ビルド ---
call :WRITE_LOG "[4/6] PyInstaller によるコンパイルを開始します..."

if exist "timer.ico" (
    call :WRITE_LOG "timer.ico を同梱してビルドします。"
    ".venv\Scripts\pyinstaller.exe" --noconsole --onefile --clean ^
      --icon="timer.ico" ^
      --add-data "timer.ico;." ^
      --name "SimpleTimer" timer.py >> "%LOG_FILE%" 2>&1
) else (
    call :WRITE_LOG "timer.ico なし（標準アイコン）でビルドします。"
    ".venv\Scripts\pyinstaller.exe" --noconsole --onefile --clean ^
      --name "SimpleTimer" timer.py >> "%LOG_FILE%" 2>&1
)

if errorlevel 1 (
    call :WRITE_LOG "[エラー] PyInstaller のビルド処理で失敗しました。"
    goto FAILED
)
call :WRITE_LOG "[4/6 完了] 実行ファイルの生成に成功しました。"

:: --- 完了処理 ---
call :WRITE_LOG "[5/6] 生成ファイルの存在を確認します..."
if exist "dist\SimpleTimer.exe" (
    call :WRITE_LOG "[成功] dist\SimpleTimer.exe が正常に作成されました。"
) else (
    call :WRITE_LOG "[警告] ビルドコマンドは通過しましたが、dist\SimpleTimer.exe が見当たりません。"
)

echo.
echo ===================================================
echo   ビルドが完了しました！
echo   出力先: %~dp0dist\SimpleTimer.exe
echo   詳細ログ: %LOG_FILE%
echo ===================================================
goto END

:FAILED
echo.
echo ===================================================
echo   処理が中断しました。
echo   詳細な原因は build_log.txt の末尾を確認してください。
echo ===================================================

:END
echo.
pause
exit /b

:: --- ログ出力共通関数 ---
:WRITE_LOG
echo [%time%] %~1
echo [%time%] %~1 >> "%LOG_FILE%"
exit /b