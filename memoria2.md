# memoria2

## Fecha
2026-03-31

## Objetivo
Registrar los cambios realizados desde la `memoria1.md`, dejar un historial claro de las modificaciones y documentar el estado actual del scraper y cómo quedó funcionando.

## Cambios realizados (resumen)
- Se corrigieron varios errores que producían NameError y excepciones al ejecutar el script (`_accept_cookies_banner`, `_wait_for_login_input`, `_save_debug` y otros manejos de errores se ajustaron).
- Se reescribió y robusteció el flujo de login:
  - Detección y aceptación genérica del banner de cookies.
  - Flujo de login en pasos (usuario -> Siguiente -> hint opcional -> contraseña), usando clicks explícitos / `press("Enter")` y `type()` para que React registre entradas.
  - Guardado de artefactos de depuración (`post_fill_username.png`, `post_click_username.html`, `password_missing.png`, etc.) cuando hay fallos.
- Se implementó soporte multi-navegador para Playwright (`chromium`, `msedge`, `firefox`, `webkit`):
  - Nuevo argumento CLI `--browser` (default: `chromium`).
  - Diferenciación de `browser_type` y `launch_kwargs` por engine.
  - Evitar pasar flags incompatibles a Firefox/WebKit; `--disable-blink-features=AutomationControlled` sólo para Chromium/Edge.
  - `navigator.webdriver` override aplicado sólo para motores basados en Chromium.
- Perfiles persistentes separados por navegador:
  - `x_profile_chromium`, `x_profile_msedge`, `x_profile_firefox`, `x_profile_webkit` para evitar conflictos entre engines.
- Se añadió la opción `--use-real-profile` para usar la carpeta real del navegador del usuario (Edge/Chrome) y así reaprovechar cookies/sesión existente y evitar la detección anti-bot.
  - Implementada la función `_get_real_profile_dir(browser_name)` para resolver `%LOCALAPPDATA%` y ubicar `Microsoft\Edge\User Data` o `Google\Chrome\User Data`.
  - En este modo, el script verifica bloqueos de acceso y aborta con un mensaje claro si el navegador está abierto (sugiere cerrar Edge/Chrome antes de ejecutar).
- Ajustes en el `main()` y en `_parse_args()`:
  - Se agregó `--browser` y `--use-real-profile` a la CLI.
  - Se pasa `browser_name` y `use_real_profile` a `scrape_x_search_playwright`.
- Se mejoró el manejo de errores de lanzamiento de Playwright para dar mensajes legibles cuando la carpeta del perfil está bloqueada.

## Detalle por archivo
- `playwright_scrape.py`
  - Se corrigieron y añadieron funciones auxiliares: `_save_debug`, `_get_real_profile_dir`.
  - Se reestructuró `scrape_x_search_playwright` para seleccionar engine, `launch_persistent_context` dinámico, y manejo `use_real_profile`.
  - Se reforzó flujo de login (username -> next -> hint -> password) y guardado de artefactos.
  - Agregado `--browser` y `--use-real-profile` en `_parse_args()`.
- `.env`
  - Se actualizó con `X_WAIT_FOR_LOGIN=1` por defecto en pruebas y se añadió comentario opcional `X_PROFILE_NAME`.
- `memoria2.md` (este archivo)

## Estado actual
- El scraper ahora evita la detección antibot de X únicamente cuando se ejecuta con la bandera `--use-real-profile` y apuntando al perfil real del usuario (Edge/Chrome).
- Pruebas realizadas:
  - Ejecución con perfil real de Edge (`--browser msedge --use-real-profile --headful`) produjo extracción de datos (ejemplo de validación: guardó 1 row con `--limit 1` en `tweets_colombia.csv`).
  - Ejecuciones en otros navegadores (`firefox`, `webkit`) no sufren errores por flags incompatibles tras la refactorización.
- Comportamiento observado:
  - Sin `--use-real-profile`, Twitter bloquea o muestra el mensaje: "Could not log you in now. Please try again later." (bot detection) y no se obtienen tweets.
  - Con `--use-real-profile` *y asegurando que el navegador real esté totalmente cerrado antes de iniciar el script*, el scraper abre el navegador con la sesión real y continúa directamente a la búsqueda, encontrando tweets.
  - Si el navegador está abierto en segundo plano, Playwright no puede acceder al `User Data` y falla con mensaje claro pidiendo cerrar el navegador.

## Cómo ejecutar (recomendado)
1. Asegúrate de tener en tu navegador (Edge/Chrome) iniciada la sesión de X/Twitter con tu cuenta.
2. Cierra por completo todas las ventanas de Edge/Chrome (verifica que no queden procesos en segundo plano).
3. Ejecuta (ejemplo usando Edge y modo visual):

```bash
python playwright_scrape.py \
  --query "elecciones Colombia since:2022-01-01 until:2022-12-31 lang:es" \
  --browser msedge \
  --headful \
  --use-real-profile
```

- Para pruebas rápidas usa `--limit 1`.
- Si prefieres login manual en la primera ejecución sin usar el perfil real, puedes dejar `--use-real-profile` apagado y poner `X_WAIT_FOR_LOGIN=1` en `.env` para ingresar las credenciales manualmente.

## Errores y limitaciones actuales
- La única forma fiable de evitar la detección fue usar el perfil real del navegador. Los intentos de *stealth* parciales o flags no bastan con las defensas actuales de X.
- Requiere que Edge/Chrome esté cerrado (Playwright no puede abrir un perfil en uso). Si aparece un error de locking, cerrar procesos o ejecutar `Stop-Process -Name msedge -Force` en PowerShell suele resolverlo.
- El scraping depende de selectores CSS de la página; X puede cambiar su DOM y romper selectores (hay artefactos de debug guardados en `debug_artifacts/` para diagnosticar).

## Próximos pasos sugeridos
- Añadir un pequeño helper para detectar y matar procesos de navegador en Windows con confirmación interactiva (solo como helper, con cuidado por seguridad).
- Añadir opción `--cookies-file` para cargar cookies exportadas (otra forma de evitar login automatizado sin usar el perfil completo).
- Investigar `playwright-stealth` y probar integrarlo como opción alternativa para entornos donde no se pueda usar el perfil real.
- Crear tests integrados/CI que verifiquen la extracción mínima (mock o fixtures), y mantener los tests unitarios actuales.

## Pruebas
- `pytest -q`: 3 passed (sin cambios en tests existentes).
- Prueba manual con perfil real Edge: ejecutado y verificado (guardado en `tweets_colombia.csv`).

## Notas finales
- El proyecto ahora soporta múltiples navegadores y perfiles independientes por motor.
- La estrategia de producción ideal es: usar `--use-real-profile` en la máquina local (cuando sea aceptable por políticas), o desplegar un entorno controlado con cookies/profiles ya preparados en infra confiable.

---

Registro corto de cambios (delta respecto a `memoria1.md`):
- Se añadió soporte multi-browser y perfiles por navegador.
- Se añadió la opción y la implementación de `--use-real-profile` para evadir la detección de X.
- Se arreglaron funciones faltantes y se robusteció el flujo de login de múltiples pasos.
- Estado final: funciona únicamente usando perfil real (Edge) para evitar bloqueo antibot.

