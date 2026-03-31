# memoria1

## Fecha
2026-03-30

## Objetivo
Dejar un punto de memoria (changelog) con el estado del proyecto y todos los cambios realizados hasta la fecha.

## Cambios realizados (resumen)
- Se elimino el enfoque GraphQL/snscrape y se paso a un enfoque 100% Playwright headless.
- Se elimino el entorno local .venv y se agrego .venv/ y venv/ a .gitignore.
- Se creo el script principal de scraping: playwright_scrape.py.
- Se creo README.md con contexto, pasos y uso del script.
- Se creo .env y .env.example para configurar login por usuario/contrasena (sin cookies).
- Se agrego logging y debug artifacts (screenshot y html) cuando no hay resultados.
- Se agrego tests unitarios (tests/test_scraper_utils.py) y conftest.py para imports.
- Se ajusto el notebook para ejecutar el script externo y evitar el loop async en Jupyter.
- Se actualizaron dependencias en requirements.txt (playwright, python-dotenv).

## Detalle por archivo
- playwright_scrape.py
  - Login por usuario/contrasena y opcion manual headful.
  - Logs con niveles y opcion de archivo de log.
  - Debug artifacts: empty_results.png y page.html.
  - Helpers para parsear href y conteos.
- README.md
  - Contexto del cambio a Playwright.
  - Pasos de instalacion y ejecucion.
  - Instrucciones para logs y debug.
- .env / .env.example
  - Variables para X_USERNAME, X_PASSWORD, X_LOGIN_HINT, X_WAIT_FOR_LOGIN.
  - Variables de logging X_LOG_LEVEL, X_DEBUG_DIR, X_LOG_FILE.
- .gitignore
  - Ignora .env, debug_artifacts, .venv, venv y archivos de cookies.
- tests/test_scraper_utils.py y tests/conftest.py
  - Pruebas unitarias para parsing y conversion de conteos.

## Estado actual
- El script abre la ventana de X (headful) pero no consigue llenar el input de login.
- Logs recientes muestran: "Login input not found; login page may have changed".
- tweets_colombia.csv queda vacio (0 rows).
- El comando con logs genera debug_artifacts con screenshots y html para ajustar selectores.

## Errores recientes (resumen)
- Login input not found en la pagina de login.
- CSV vacio por no encontrar tweets (posible bloqueo o selectores desactualizados).

## Pruebas
- pytest -q: 3 passed

## Proximos pasos sugeridos
- Revisar debug_artifacts/login_missing.png y page.html para actualizar selectores.
- Ajustar flujo de login (labels o nuevos inputs en X).
- Validar que el usuario no tenga 2FA sin X_WAIT_FOR_LOGIN=1.
- Probar con --headful y X_WAIT_FOR_LOGIN=1 para login manual.
