# Documentación detallada de `playwright_scrape.py`

Este documento contiene explicaciones detalladas en español de cada función
presente en `playwright_scrape.py`, cómo interactúan entre sí, consideraciones
sobre deduplicación (si los tuits capturados son iguales o distintos entre
iteraciones), y un diagrama en Mermaid que resume el flujo completo del
scraper.

---

## Resumen del módulo

`playwright_scrape.py` realiza scraping de resultados de búsqueda en X/Twitter
usando Playwright con un perfil real de Microsoft Edge. El objetivo es leer
los `article[role="article"]` en la página de búsqueda, extraer metadatos
y persistirlos en un CSV por chunks para tolerancia a fallos y re-ejecuciones.

Puntos clave:
- Se utiliza `launch_persistent_context` con el perfil real de Edge para
  reutilizar una sesión con login ya hecho (evita gestionar el login por
  automatización).
- Mantiene una deduplicación en memoria (`seen_ids`) y carga IDs históricos
  desde el CSV de salida si existe.
- Persiste datos por bloques (`chunk_size`) para minimizar pérdida de datos.
- Implementa una maniobra de rescate si el scroll se estanca (PageUp/PageDown).

---

## Funciones y explicaciones

A continuación se documenta cada función con su propósito, parámetros,
retornos, efectos secundarios y notas de funcionamiento.

### `_configure_logging(level: str, log_file: str | None) -> None`

- Propósito: Configurar el logging del script.
- Parámetros:
  - `level`: Nivel de logging como string (`DEBUG`, `INFO`, ...).
  - `log_file`: Ruta opcional al fichero donde también escribir los logs.
- Efectos secundarios: configura handlers globales de `logging` y puede
  crear el directorio del fichero de log.
- Notas:
  - Afecta al logger raíz; debe llamarse antes de ejecutar la mayor parte del
    código para capturar todos los mensajes.
  - Si `log_file` apunta a un directorio no escribible lanzará excepción al
    crear `FileHandler`.

---

### `_to_int_count(text: str | None) -> int | None`

- Propósito: Convertir textos como "1.2K", "3M", "5,432" o "5 likes" a
  enteros.
- Parámetros:
  - `text`: Texto de entrada posiblemente con sufijos y comas.
- Retorno: Entero o `None` si no hay número.
- Comportamiento:
  - Normaliza texto (quita comas, pasa a mayúsculas), busca patrones con sufijos
    `K`, `M`, `B` y multiplica por el factor correspondiente.
  - Si no hay sufijo intenta extraer dígitos puros.
- Notas:
  - Diseñada para parsear valores procedentes de `aria-label` o `inner_text`.
  - No soporta formatos localizados como "mil".

---

### `_save_debug(page, debug_dir: str | None, base_name: str) -> None`

- Propósito: Guardar artefactos de depuración (PNG + HTML) de `page`.
- Parámetros:
  - `page`: Objeto Playwright `Page`.
  - `debug_dir`: Directorio donde guardar los archivos. Si es `None` no hace
    nada.
  - `base_name`: Prefijo del nombre de archivo.
- Efectos secundarios: Crea archivos en disco (`{base_name}.png` y
  `{base_name}.html`) y registra fallos a nivel DEBUG si algo falla.
- Notas:
  - No propaga excepciones; solo registra errores para no interrumpir el flujo
    principal.

---

### `_extract_tweet_id_from_href(href: str) -> str | None`

- Propósito: Extraer el ID numérico del tuit desde un `href` que contenga
  `/status/<id>`.
- Parámetros:
  - `href`: URL o fragmento de enlace.
- Retorno: ID como string o `None`.
- Notas:
  - Busca el patrón con una expresión regular; es simple y eficiente.
  - No resuelve redirecciones ni URLs abreviadas; solo busca el segmento.

---

### `_extract_username_from_href(href: str) -> str | None`

- Propósito: Extraer el nombre de usuario desde un `href` con el patrón
  `/<username>/status/<id>`.
- Parámetros:
  - `href`: URL del enlace.
- Retorno: `username` o `None`.
- Notas:
  - Asume que el username no contiene '/'; para enlaces inusuales puede fallar.

---

### `_extract_tweet_id(article) -> str | None`

- Propósito: Obtener el ID del tuit a partir de un nodo `article` de la página.
- Comportamiento:
  - Localiza hasta 8 enlaces dentro del `article` que contengan
    `href*="/status/"` y aplica `_extract_tweet_id_from_href`.
  - Devuelve el primer ID válido encontrado.
- Notas:
  - Revisa múltiples enlaces porque el `article` puede contener varias rutas,
    por ejemplo el enlace del autor, el enlace del tuit y enlaces hacia
    la conversación.

---

### `_extract_username(article) -> str | None`

- Propósito: Extraer el username asociado al tuit dentro del `article`.
- Comportamiento:
  - Similar a `_extract_tweet_id`, recorre enlaces `href*="/status/"`
    y aplica `_extract_username_from_href`.
- Notas:
  - Si falla la extracción por `href`, no se intenta extraer el username
    desde otros elementos (por ejemplo selectores de perfil). Esto puede
    dejar `username` como `None` en algunos casos.

---

### `_extract_text(article) -> str`

- Propósito: Extraer el texto del tuit.
- Estrategia:
  1. Si existe `div[data-testid="tweetText"]` devuelve su `inner_text()`.
  2. Si no, busca `div[lang]` y devuelve su `inner_text()`.
  3. Si no encuentra nada devuelve cadena vacía.
- Notas:
  - `inner_text()` devuelve el texto mostrado (renderizado), más cercano a
    lo que vería un usuario.
  - Si la estructura de DOM cambia, es probable que haya que actualizar
    estos selectores.

---

### `_extract_datetime(article) -> str | None`

- Propósito: Extraer la fecha/hora del tuit mediante el elemento `<time>`.
- Comportamiento:
  - Localiza el primer `time` dentro del `article` y devuelve el atributo
    `datetime` si existe.
- Notas:
  - El valor suele estar en formato ISO 8601; si se necesita un objeto
    `datetime` se recomienda convertirlo con `pandas.to_datetime` o
    `dateutil`.

---

### `_extract_action_count(article, action: str) -> int | None`

- Propósito: Extraer el contador numérico para acciones como `reply`,
  `retweet` o `like`.
- Estrategia:
  1. Busca el nodo `[data-testid="{action}"]` dentro del `article`.
  2. Intenta leer `aria-label` y parsearlo con `_to_int_count`.
  3. Si no, intenta `inner_text()` del nodo.
  4. Finalmente, intenta el `aria-label` del nodo padre.
  5. Retorna `None` si no se obtiene un número.
- Notas:
  - `aria-label` suele contener frases amigables como "5 likes", por lo
    que es fiable para extraer el número.
  - El método es tolerante a distintos layouts e intenta varias fuentes
    antes de rendirse.

---

### `_get_real_profile_dir() -> str`

- Propósito: Determinar la ruta del perfil real de Microsoft Edge en
  Windows para usar en `launch_persistent_context`.
- Comportamiento:
  - Usa `%LOCALAPPDATA%\Microsoft\Edge\User Data` por defecto.
  - Si existe la variable `X_REAL_PROFILE_DIR` la usa en su lugar.
  - Si `LOCALAPPDATA` no está definida lanza `RuntimeError`.
- Notas:
  - Es crítico que el perfil no esté bloqueado por otra instancia de Edge
    al intentar abrirlo desde Playwright.

---

### `scrape_x_search_playwright(...) -> pd.DataFrame`

- Propósito: Controlar todo el flujo de scraping de la búsqueda en X/Twitter
  y retornar un `DataFrame` con los resultados.

Parámetros principales (resumen):
- `query`: Consulta de búsqueda (acepta filtros de X).
- `limit`: Límite máximo de tuits a recolectar.
- `out_csv`: Ruta para guardar los resultados en CSV (append por chunks).
- `headless`: Ejecutar navegador en modo headless.
- `scroll_pause`: Pausa entre ráfagas de scroll (segundos).
- `max_scrolls`: Máximo de iteraciones de scroll.
- `chunk_size`: Número de registros tras los cuales persistir a CSV.
- `debug_dir`: Directorio para artefactos de depuración.

Flujo detallado y deduplicación:
1. Inicializa `records`, `pending_records` y `seen_ids`.
2. Si `out_csv` existe, intenta leer la columna `id` y añade esos IDs a
   `seen_ids`. Esto realiza deduplicación entre ejecuciones: si un tuit ya
   está presente en el CSV histórico, no se volverá a añadir.
3. Dentro de la ejecución actual, antes de añadir un `record`, el código
   comprueba si `tweet_id` está en `seen_ids`. Si está, salta el tuit.
   Por tanto, los tuits capturados en distintas iteraciones internas del
   bucle no se duplican.
4. Se hace append a `pending_records` y cada `chunk_size` se llama a
   `_append_chunk` que escribe en `out_csv` usando `mode='a'`.
5. Cuando se agota el bucle por `limit` o por `max_scrolls`/estancamiento,
   se vacía `pending_records` y se cierra el contexto.
6. Finalmente se crea un `DataFrame` desde `records`, se aplica
   `drop_duplicates(subset=['id'])` (por seguridad) y se devuelve la cabecera
   con `.head(limit)`.

Conclusiones sobre si los tuits son iguales o distintos entre iteraciones:
- Dentro de una misma ejecución del script: los tuits no se repiten porque
  `seen_ids` se actualiza en tiempo real y evita re-procesar un mismo ID.
- Entre ejecuciones separadas del script: si `out_csv` existe y contiene IDs
  históricos, el script cargará esos IDs en `seen_ids` y no volverá a
  insertar los mismos tuits en el CSV. Por tanto, el comportamiento evita
  duplicación cross-run.
- Sin embargo, hay escenarios en los que podrías ver registros "repetidos":
  - Si `out_csv` fue modificado manualmente o con IDs mal formateados, la
    deduplicación puede fallar.
  - Si el mismo tuit se renderiza en distintas posiciones y fue capturado
    entre la lectura del CSV y la ejecución, un re-run puede capturarlo si
    el CSV no estaba disponible o si hubo un fallo al leerlo.

Otras consideraciones importantes:
- Persistencia incremental mejora tolerancia a fallos: si el script se
  interrumpe, los datos ya escritos no se perderán.
- `seen_ids` es la fuente primaria de verdad en memoria; la escritura a
  disco se hace por chunks y puede incluir algún retraso entre la captura
  y la persistencia final.
- El script intenta ser robusto ante cambios de altura de página y hace
  una maniobra de rescate (PageUp/PageDown) antes de detenerse por
  estancamiento.
- Uso de perfil real implica que si Edge está abierto con bloqueo del
  perfil, Playwright puede fallar con errores tipo SQL/lock; el script
  detecta esto y sugiere cerrar Edge.

---

### `_append_chunk(chunk: list[dict[str, Any]]) -> None` (función interna)

- Propósito: Serializar y escribir un bloque de registros en `out_csv`.
- Comportamiento:
  - Convierte el `chunk` en `DataFrame`, elimina duplicados por `id` y
    hace `to_csv(mode='a')` con o sin cabecera según `file_exists`.
- Notas:
  - Actualiza la bandera `file_exists` a `True` después de escribir.
  - Es la forma en la que el script consigue durabilidad incremental.

---

### `_parse_args() -> argparse.Namespace`

- Propósito: Parsear los argumentos de línea de comandos.
- Parámetros/flags disponibles: `--query`, `--limit`, `--out`, `--headless`,
  `--headful`, `--max-scrolls`, `--scroll-pause`, `--chunk-size`,
  `--log-level`, `--log-file`, `--debug-dir`.
- Notas:
  - `--headless` y `--headful` se combinan más adelante para decidir el
    modo final del navegador.

---

### `main()`

- Propósito: Orquestar la ejecución desde CLI.
- Comportamiento:
  - Carga variables de entorno con `dotenv` si está disponible.
  - Parsea argumentos, configura logging y decide `headless` combinando
    `--headless` y `--headful`.
  - Llama a `scrape_x_search_playwright` con los parámetros adecuados.

---

## Diagrama de flujo (Mermaid)

El siguiente diagrama resume el proceso completo paso a paso.

```mermaid
flowchart TB
  A[Inicio] --> B{¿Existe out_csv?}
  B -- Sí --> B1[Leer columna id del CSV y poblar seen_ids]
  B -- No --> B2[seen_ids vacío]
  B1 --> C[Iniciar Playwright con perfil Edge]
  B2 --> C
  C --> D[Navegar a URL de búsqueda]
  D --> E[Esperar articles aparezcan]
  E --> F[Loop scroll (por hasta max_scrolls)]
  F --> G[Obtener lista de articles visibles]
  G --> H[Por cada article]
  H --> I[Extraer tweet_id]
  I --> J{tweet_id vacío o en seen_ids?}
  J -- Sí --> K[Ignorar]
  J -- No --> L[Extraer campos: datetime, username, text, counts]
  L --> M[Añadir a records y pending_records y seen_ids]
  M --> N{len(records) >= limit?}
  N -- Sí --> O[Salir del loop]
  N -- No --> P{len(records) % chunk_size == 0?}
  P -- Sí --> Q[Escribir pending_records en CSV via _append_chunk]
  P -- No --> R[Continuar]
  R --> S[Scroll/espera y medir scrollHeight]
  S --> T{scrollHeight cambió?}
  T -- No --> U[incrementar stagnant_rounds]
  T -- Sí --> V[reset stagnant_rounds]
  U --> W{stagnant_rounds >= 3?}
  W -- Sí --> X{rescue_used?}
  X -- No --> Y[Intentar rescue: PageUp/PageDown]
  X -- Sí --> Z[Romper loop por estancamiento]
  Y --> S
  Z --> O
  O --> AA[Flush pending_records restantes]
  AA --> AB[Cerrar contexto Playwright]
  AB --> AC[Crear DataFrame, drop_duplicates, head(limit)]
  AC --> AD[Retornar DataFrame y terminar]
```

---

## Recomendaciones y notas finales

- Para depuración: ejecutar en modo `--headful` con `--debug-dir` para
  capturar HTML y PNGs que permitan inspeccionar selectores.
- Si se observan duplicados inesperados en el CSV:
  - Comprobar el formato de la columna `id` en el CSV (no deben tener
    sufijos `.0` ni formatos flotantes); el script intenta limpiar `.0`.
  - Asegurarse de que la lectura de `out_csv` no falla (revisa los logs).
- Mantener actualizados los selectores (`data-testid`, `div[lang]`, `time`)
  si X/ Twitter actualiza su DOM.

---

Si quieres, puedo:
- Añadir ejemplos de ejecución en la cabecera del archivo.
- Renderizar y guardar el diagrama Mermaid como imagen en `docs/`.
- Generar una versión en inglés además de la versión en español.
