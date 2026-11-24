# SIMCA Analytics

Cruza el **pensum oficial** con la **historia académica** de SIMCA (Unicauca) y muestra una matriz
de avance (aprobada / disponible / bloqueada / reprobada) con alias y prerrequisitos editables.

## Estructura
```
app.py                    entrada Streamlit (navegación + init de session_state)
views/matriz.py           página principal: matriz, métricas, exportación
views/configuracion.py    alias y prerrequisitos por materia
simca/settings.py         dotenv, rutas, directorio privado
simca/scraper.py          Playwright: login -> buscar -> Historia Académica / Pénsum (solo HTML)
simca/cli_scrape.py       subproceso que scrapea y guarda el snapshot
simca/parsers.py          BeautifulSoup: parse_pensum_html / parse_notas_html
simca/snapshot.py         unificación base pensum+notas -> JSON local
simca/matrix.py           emparejamiento, prerrequisitos efectivos, estados, métricas
simca/config_store.py     config_materias.json: lock + escritura atómica + fusión por materia
simca/render.py           HTML de la matriz (escapado)
simca/reglamento.py       Arts. 6-11 del Reglamento Estudiantil: repitencias, bajo rendimiento, matrícula condicional
des_not.py                CLI compatible: exporta aprobadas a CSV
desplegar.bat             menú de Windows: instalar/ejecutar local, publicar en GitHub, pruebas
packages.txt              librerías del sistema (apt) para Chromium en Streamlit Cloud
.streamlit/               config.toml y secrets.toml.example
tests/                    pytest (HTML sintético, sin datos personales)
```

## Puesta en marcha (Windows: doble clic en `desplegar.bat`)
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env        # completa SIMCA_USER y SIMCA_PASSWORD (comillas simples si tiene # $ o espacios)
streamlit run app.py
```
Sin conexión: en la barra lateral, "Cargar HTML guardados" acepta los `.html` de Pénsum e Historia Académica.

## Seguridad
- Credenciales solo por `.env`/entorno (python-dotenv); no existen valores en el código ni se imprimen.
- Datos locales en `data/` (o `SIMCA_DATA_DIR`, recomendado fuera del repo): permisos 0700/0600 y un
  `.gitignore` interno con `*`. El `.gitignore` raíz excluye `.env`, `data/`, `*.csv`, `SIMCA_*.html`, `NOTAS.txt`, etc.
- El snapshot guarda nombre, **cédula y código** del estudiante (se muestran en el panel); vive en el directorio privado y está ignorado por git. El interruptor «Ocultar cédula y código» enmascara la pantalla. La marca «Sancionado disciplinariamente» NO se guarda nunca (solo sesión).
- **Los archivos `NOTAS.txt`, `PENSUM.txt` y `CODIGO_DEMO.html` originales contienen usuario y contraseña en texto plano
  y cookies de sesión: no los subas; cambia esa contraseña y, si ya estuvieron en un repositorio, purga el historial.**

## Persistencia (`config_materias.json`)
```json
{"version": 1, "revision": 3, "materias": {"21505": {"aliases": ["Lecto - Escritura"], "prereqs_extra": [], "prereqs_removidos": []}}}
```
La clave es el ID interno de SIMCA. Un alias puede ser un nombre antiguo **o el ID** con que aparece en la historia.
Se lee una vez al iniciar la sesión y solo se escribe al guardar.

## Pruebas
`pip install -r requirements-dev.txt && pytest`

## Reglamento estudiantil (Acuerdo 002 de 1988, Arts. 6-11)
Se calcula del historial; es orientativo y no reemplaza la decisión del programa.
- Intento 1 = normal · 2 = repitente 1.ª vez · 3 = 2.ª vez · 4 = 3.ª vez. Solo cuentan intentos con nota definitiva
  (una habilitación no es un intento; una cancelación tampoco).
- Art. 6 bajo rendimiento · Art. 7 matrícula condicional (o pérdida del derecho con sanción) · Art. 8 pérdida al no aprobar
  como repitente 3.ª vez · Art. 9 con condicional solo se matriculan repeticiones · Arts. 10-11 máximo dos condicionales.
- Supuesto: cada periodo en que se pierde una asignatura como repitente 2.ª vez genera una matrícula condicional (el periodo siguiente).
- Para lo que se cursa hoy se muestra qué ocurriría si se pierde, y se compara la columna «Repetición» de SIMCA con el historial.

## Despliegue en Streamlit Community Cloud (share.streamlit.io)
Streamlit Cloud lee `requirements.txt` (Python) y **`packages.txt`** (librerías del sistema que necesita Chromium).
1. Ejecuta `desplegar.bat` → opción 3: verifica que no se suban datos personales, hace commit y sube a un repositorio **privado** de GitHub.
2. En share.streamlit.io: *New app* → repositorio, rama `main`, archivo `app.py`, Python 3.11/3.12.
3. *Secrets*: pega `.streamlit/secrets.toml.example` con tus valores (claves en el nivel raíz). **`SIMCA_APP_ACCESS_CODE` es obligatorio**: sin él la app no carga.
4. *Settings → Sharing*: deja la app privada y restringe los visores por correo.

**Modo nube (se activa solo):** el disco es efímero y compartido entre visitantes, así que los datos de cada consulta (notas, cédula, código) viven
solo en la sesión: no se guardan ni se leen del disco. La configuración de alias/asignaciones sí se guarda, pero se pierde en cada reinicio:
usa *Exportar / importar configuración* para conservarla.
**Riesgos conocidos:** SIMCA puede bloquear IPs de centros de datos o exigir VPN/red universitaria; Chromium consume memoria (el plan gratuito es limitado).
Si `packages.txt` falla al compilar con `libasound2`, cámbialo por `libasound2t64` (distribuciones más nuevas).
