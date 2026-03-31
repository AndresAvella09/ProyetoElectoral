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

## Autenticacion opcional (cookies)

Si X te bloquea contenido sin login, pasa cookies por variable de entorno (NO versionar archivos):

```powershell
$env:X_COOKIES_JSON = Get-Content .\cookiesx.local.json -Raw
```

El archivo `cookiesx.local.json` es un export de cookies del navegador. **No lo subas al repo.**

## Uso desde notebook

1. Ejecuta la celda de `query` y `limit`.
2. Ejecuta la celda de scraping (Playwright), que llama el script externo.
3. Revisa `tweets_colombia.csv` o usa `df.head()`.

## Uso por linea de comandos

```powershell
python playwright_scrape.py --query "elecciones Colombia since:2022-01-01 until:2022-12-31 lang:es" --limit 500 --out tweets_colombia.csv --headless
```

## Parametros utiles

- `--headful` abre la ventana del navegador (depuracion).
- `--max-scrolls` controla el maximo de scrolls.
- `--scroll-pause` pausa entre scrolls.
- `--chunk-size` guarda lotes parciales a CSV.

## Estructura

- `playwright_scrape.py`: scraper principal (Playwright headless)
- `x_scraping_electoral_notebook (1).ipynb`: notebook con flujo de ejecucion
- `requirements.txt`: dependencias

## Consideraciones

- El HTML de X cambia con frecuencia; si falla, ajustar selectores (`article[role="article"]`, `div[data-testid="tweetText"]`).
- Los contadores (likes/retweets) pueden ocultarse; el parser intenta normalizar valores con K/M/B.
- Respeta terminos de servicio y uso etico de scraping.
