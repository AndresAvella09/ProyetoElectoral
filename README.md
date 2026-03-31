# Electoral X Scraper (Playwright)

Este proyecto usa Playwright con Chromium en modo headless para extraer tweets de X (Twitter) desde la busqueda web. Se reemplazo el enfoque GraphQL/snscrape por un flujo 100% Playwright para evitar bloqueos del endpoint GraphQL y inconsistencias de hash.

## Contexto tecnico

- **Antes**: snscrape via GraphQL (fragil ante cambios y bloqueos de X).
- **Ahora**: Playwright headless + scroll controlado + extraccion DOM.
- **Motivo**: reducir bloqueos y tener control de la navegacion real del sitio.

> Nota: Playwright en Jupyter (Windows) puede fallar por el loop async. Para evitarlo, el notebook invoca un script externo (`playwright_scrape.py`).

## Requisitos

- Python 3.11+ (instalado en el sistema)
- Dependencias en `requirements.txt`
- Chromium instalado por Playwright

## Instalacion

```powershell
pip install -r requirements.txt
python -m playwright install chromium
```

## Autenticacion opcional (usuario/contrasena)

Usa el archivo `.env`:

```
X_USERNAME=tu_usuario_o_email
X_PASSWORD=tu_contrasena
X_LOGIN_HINT=tu_usuario_o_email
X_WAIT_FOR_LOGIN=0
```

- `X_LOGIN_HINT` solo se usa si X pide confirmar el usuario/email/telefono.
- Si tienes 2FA, usa `--headful` y `X_WAIT_FOR_LOGIN=1` para completar manualmente.

## Uso desde notebook

1. Ejecuta la celda de `query` y `limit`.
2. Ejecuta la celda de scraping (Playwright), que llama el script externo.
3. Revisa `tweets_colombia.csv` o usa `df.head()`.

## Uso por linea de comandos

```powershell
python playwright_scrape.py --query "elecciones Colombia since:2022-01-01 until:2022-12-31 lang:es" --limit 500 --out tweets_colombia.csv --headless
```

## Logs y debug

Activa logs detallados y guarda artifacts cuando el CSV salga vacio:

```powershell
python playwright_scrape.py --query "..." --limit 50 --headful --log-level DEBUG --debug-dir debug_artifacts
Guarda logs en archivo:

```powershell
python playwright_scrape.py --query "..." --limit 50 --log-level DEBUG --log-file debug_artifacts\scrape.log
```
```

Tambien puedes definir en `.env`:

```
X_LOG_LEVEL=DEBUG
X_DEBUG_DIR=./debug_artifacts
X_LOG_FILE=./debug_artifacts/scrape.log
```

## Parametros utiles

- `--headful` abre la ventana del navegador (depuracion).
- `--max-scrolls` controla el maximo de scrolls.
- `--scroll-pause` pausa entre scrolls.
- `--chunk-size` guarda lotes parciales a CSV.
- `--log-level` controla el nivel de log (DEBUG/INFO/WARNING/ERROR).
- `--debug-dir` guarda `empty_results.png` y `page.html` si no hay resultados.

## Pruebas unitarias

```powershell
pytest -q
```

## Estructura

- `playwright_scrape.py`: scraper principal (Playwright headless)
- `x_scraping_electoral_notebook (1).ipynb`: notebook con flujo de ejecucion
- `requirements.txt`: dependencias

## Consideraciones

- El HTML de X cambia con frecuencia; si falla, ajustar selectores (`article[role="article"]`, `div[data-testid="tweetText"]`).
- Los contadores (likes/retweets) pueden ocultarse; el parser intenta normalizar valores con K/M/B.
- Respeta terminos de servicio y uso etico de scraping.
