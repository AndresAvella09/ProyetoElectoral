# Electoral X Scraper (Playwright) + Sentiment Pipeline

Este repositorio implementa un flujo completo para extraer tweets de X (Twitter), calcular sentimiento y agregar variables electorales a nivel temporal. Se reemplazo el enfoque GraphQL/snscrape por un flujo Playwright para evitar bloqueos del endpoint GraphQL y inconsistencias de hash.

## Alcance y tareas (T1 / T2)

### T1. Extraccion y variables de interes 2026

**Hecho**
- Extraccion de tweets mediante Playwright (flujo real de navegador con Edge).
- Consultas de busqueda personalizadas (ej: "elecciones Colombia").
- Campos recopilados: fecha (datetime), texto del tuit, nombre de usuario, gustos, retuits.
- Construccion de variables base: sentimiento e interaccion (indicador de viralidad).
- Agregacion temporal semanal o mensual.

**Pendiente por alcance/tiempo**
- Deteccion de narrativas (temas, discurso).
- Agrupacion por municipio.
- Separacion por candidatos.

### T2. Caracteristicas para modelo electoral

**Hecho**
- Variables de salida del pipeline:
	- `puntuacion_de_sentimiento`
	- `tasa_de_interaccion`
	- `volumen_de_tuits`
	- `indice_de_polarizacion`
- Propuesta de modelo: `Voto = f(caracteristicas_electorales + caracteristicas_demograficas + caracteristicas_digitales)`.
- Implementacion de analisis de sentimiento con transformer multilenguaje entrenado en tweets.

**Pendiente por alcance/tiempo**
- Fusion real con datos demograficos/municipales.
- Segmentacion por candidato o partido.

## Contexto tecnico

- **Antes**: snscrape via GraphQL (fragil ante cambios y bloqueos de X).
- **Ahora**: Playwright headless + scroll controlado + extraccion DOM.
- **Motivo**: reducir bloqueos y tener control de la navegacion real del sitio.

> Nota: Playwright en Jupyter (Windows) puede fallar por el loop async. Para evitarlo, el notebook invoca un script externo (playwright_scrape.py).

## Requisitos

- Python 3.11+
- Dependencias en requirements.txt
- Microsoft Edge instalado en Windows

## Instalacion (venv recomendado)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install
```

## Perfil real de Edge

- El scraper usa el perfil real del usuario en Edge para reducir el bloqueo antibot.
- Cierra todas las ventanas de Edge antes de ejecutar el script.
- Opcional: `X_REAL_PROFILE_DIR` para una ruta manual y `X_PROFILE_NAME` para elegir un perfil.

## Uso desde notebook

1. Ejecuta la celda de `query` y `limit`.
2. Ejecuta la celda de scraping (Playwright), que llama el script externo.
3. Revisa `tweets_colombia.csv` o usa `df.head()`.
4. Ejecuta el pipeline de sentimiento desde el notebook para generar las salidas agregadas.

## Uso por linea de comandos

**1) Scraping**

```powershell
python playwright_scrape.py --query "elecciones Colombia since:2022-01-01 until:2022-12-31 lang:es" --limit 500 --out tweets_colombia.csv --headless
```

**2) Sentiment pipeline**

```powershell
python sentiment_pipeline.py --input tweets_colombia.csv --output tweets_colombia_sentiment.csv --agg-output tweets_colombia_agg.csv --freq W --batch-size 32
```

## Modelo de analisis de sentimiento

Se usa el modelo `cardiffnlp/twitter-xlm-roberta-base-sentiment` (XLM-RoBERTa) entrenado en textos cortos tipo tweet y multilenguaje.

**Pipeline**
- Preprocesamiento: reemplaza menciones por `@user` y URLs por `http`.
- Tokenizacion: `AutoTokenizer` con padding y truncation (max_length por defecto 128).
- Embeddings: representaciones contextuales por token en XLM-RoBERTa.
- Clasificacion: capa final genera logits para negativo/neutral/positivo; se aplica softmax para probabilidades.
- Scoring: `negative = -1`, `neutral = 0`, `positive = 1`.

**Salidas**
- `sentiment`: etiqueta final (negative, neutral, positive).
- `sentiment_score`: puntaje numerico (-1/0/1).
- `prob_negative`, `prob_neutral`, `prob_positive`.

## Variables calculadas (agregacion temporal)

El pipeline agrega por periodo (`W` semanal o `M` mensual) y calcula:

- `puntuacion_de_sentimiento`: promedio de `sentiment_score`.
- `tasa_de_interaccion`: promedio de `likes + retweets`.
- `volumen_de_tuits`: conteo de tweets por periodo.
- `indice_de_polarizacion`: desviacion estandar del sentimiento (ddof=0).

## Archivos de salida

- `tweets_colombia.csv`: dataset crudo del scraping.
- `tweets_colombia_sentiment.csv`: dataset con sentimiento y probabilidades.
- `tweets_colombia_agg.csv`: agregados por periodo con variables electorales.

## Logs y debug

Activa logs detallados y guarda artifacts cuando el CSV salga vacio:

```powershell
python playwright_scrape.py --query "..." --limit 50 --headful --log-level DEBUG --debug-dir debug_artifacts
```

Guarda logs en archivo:

```powershell
python playwright_scrape.py --query "..." --limit 50 --log-level DEBUG --log-file debug_artifacts\scrape.log
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
- `sentiment_pipeline.py`: pipeline de sentimiento y agregacion temporal
- `x_scraping_electoral_notebook (1).ipynb`: notebook con flujo de ejecucion
- `requirements.txt`: dependencias

## Consideraciones

- El HTML de X cambia con frecuencia; si falla, ajustar selectores (`article[role="article"]`, `div[data-testid="tweetText"]`).
- Los contadores (likes/retweets) pueden ocultarse; el parser intenta normalizar valores con K/M/B.
- Respeta terminos de servicio y uso etico de scraping.

## Limitaciones del estudio

- No hay geolocalizacion de municipio ni datos demograficos confiables en los tweets.
- El modelo de sentimiento no infiere decision de voto; solo mide tono del texto.
- Los agregados son nacionales/temporales y no representan resultados electorales reales.
