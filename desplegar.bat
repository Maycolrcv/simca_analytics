@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title SIMCA Analytics - Despliegue
set "VENV=.venv\Scripts\python.exe"
set "STREAMLIT_BROWSER_GATHER_USAGE_STATS=false"

:menu
cls
echo ==============================================================
echo   SIMCA Analytics - Despliegue
echo ==============================================================
echo   [1] Instalar y ejecutar en LOCAL  (primera vez)
echo   [2] Ejecutar en LOCAL             (ya instalado)
echo   [3] Preparar y publicar en GITHUB (para share.streamlit.io)
echo   [4] Ejecutar pruebas
echo   [5] Salir
echo.
choice /c 12345 /n /m "Elige una opcion: "
if errorlevel 5 goto :fin
if errorlevel 4 goto :pruebas
if errorlevel 3 goto :publicar
if errorlevel 2 goto :ejecutar
if errorlevel 1 goto :instalar
goto :menu

:: ------------------------------------------------------------------
:instalar
echo.
echo [1/5] Buscando Python 3.10 o superior...
set "PY="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    python --version >nul 2>&1
    if not errorlevel 1 set "PY=python"
)
if not defined PY goto :sin_python
%PY% -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)"
if errorlevel 1 goto :sin_python

echo [2/5] Creando entorno virtual .venv ...
if not exist "%VENV%" %PY% -m venv .venv
if errorlevel 1 goto :error

echo [3/5] Instalando dependencias (puede tardar unos minutos)...
"%VENV%" -m pip install --upgrade pip
if errorlevel 1 goto :error
"%VENV%" -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo [4/5] Instalando el navegador Chromium para Playwright...
"%VENV%" -m playwright install chromium
if errorlevel 1 goto :error

echo [5/5] Configurando credenciales...
if exist ".env" goto :env_ok
copy ".env.example" ".env" >nul
echo.
echo Se creo el archivo .env. Escribe tu SIMCA_USER y SIMCA_PASSWORD,
echo guarda y cierra el Bloc de notas para continuar.
echo (Tambien puedes dejarlos vacios y digitarlos en la barra lateral de la app.)
start /wait notepad ".env"
:env_ok
goto :ejecutar

:sin_python
echo.
echo [ERROR] No se encontro Python 3.10 o superior.
echo Instalalo desde https://www.python.org/downloads/ y marca la casilla
echo "Add python.exe to PATH". Luego vuelve a ejecutar este archivo.
goto :pausa

:: ------------------------------------------------------------------
:ejecutar
echo.
if exist "%VENV%" goto :lanzar
echo [AVISO] Aun no esta instalado. Elige la opcion 1 primero.
goto :pausa
:lanzar
echo Abriendo http://localhost:8501  (Ctrl+C para detener)
start "" /min cmd /c "ping -n 6 127.0.0.1 >nul & start http://localhost:8501"
"%VENV%" -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
goto :pausa

:: ------------------------------------------------------------------
:pruebas
echo.
if not exist "%VENV%" goto :ejecutar
"%VENV%" -m pip install -q -r requirements-dev.txt
if errorlevel 1 goto :error
"%VENV%" -m pytest -q tests
goto :pausa

:: ------------------------------------------------------------------
:publicar
echo.
echo === Publicacion en GitHub para share.streamlit.io ===
where git >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Git no esta instalado: https://git-scm.com/download/win
    goto :pausa
)
for %%F in (app.py requirements.txt packages.txt .gitignore .streamlit\config.toml) do (
    if not exist "%%F" (
        echo [ERROR] Falta el archivo %%F
        goto :pausa
    )
)
if not exist ".git" (
    git init
    git branch -M main
)
git add -A
echo.
echo Verificando que no se suban datos personales ni credenciales...
git ls-files | findstr /i /r "^\.env$ ^data/ config_materias snapshot_academico \.csv$ ^SIMCA_ NOTAS\.txt PENSUM\.txt MATERIAS_MATRICULADAS secrets\.toml$ \.html$" >nul
if not errorlevel 1 (
    echo.
    echo [ALTO] Hay archivos sensibles en el commit. NO se publica. Se detectaron:
    git ls-files | findstr /i /r "^\.env$ ^data/ config_materias snapshot_academico \.csv$ ^SIMCA_ NOTAS\.txt PENSUM\.txt MATERIAS_MATRICULADAS secrets\.toml$ \.html$"
    git reset >nul 2>&1
    echo Revisa .gitignore y mueve esos archivos fuera del proyecto.
    goto :pausa
)
echo OK: nada sensible en el commit.
echo Verificando que el codigo de la aplicacion quedo incluido...
for %%F in (app.py simca/__init__.py simca/auth.py simca/state.py simca/settings.py views/matriz.py views/configuracion.py) do (
    git ls-files --error-unmatch "%%F" >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] %%F NO esta en el repositorio. Revisa .gitignore y la carpeta del proyecto.
        goto :pausa
    )
)
echo OK: el codigo esta completo.
git commit -m "SIMCA Analytics" >nul 2>&1
git remote get-url origin >nul 2>&1
if not errorlevel 1 goto :push
echo.
echo Crea un repositorio PRIVADO vacio en https://github.com/new y pega su URL.
set "REMOTE="
set /p "REMOTE=URL (https://github.com/usuario/repo.git): "
if not defined REMOTE goto :pausa
git remote add origin "%REMOTE%"
:push
git push -u origin main
if errorlevel 1 goto :error
echo.
echo ==============================================================
echo  Listo. Ahora en https://share.streamlit.io :
echo   1. New app - elige el repositorio y la rama main
echo   2. Main file path: app.py
echo   3. Advanced settings - Python 3.11 o 3.12
echo   4. Secrets: pega el contenido de .streamlit\secrets.toml.example
echo      con tus valores. SIMCA_APP_ACCESS_CODE es OBLIGATORIO.
echo   5. Deploy. Luego, en Settings - Sharing, deja la app como
echo      privada y restringe los visores por correo.
echo ==============================================================
goto :pausa

:: ------------------------------------------------------------------
:error
echo.
echo [ERROR] El paso anterior fallo (codigo %errorlevel%). Revisa los mensajes de arriba.
:pausa
echo.
pause
goto :menu

:fin
endlocal
