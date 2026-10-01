# STATA Studio

Un espacio de análisis estadístico local, en español, inspirado en el flujo de trabajo de Stata. Combina una interfaz guiada con comandos, un editor de datos, gráficos e historial.

Proyecto independiente: no está afiliado a StataCorp ni incorpora su software. **Implementa un subconjunto explícito de comandos, no es un reemplazo completo ni un intérprete compatible con todos los archivos `.do`.**

## Inicio rápido

Requiere Python 3.12 o superior. En Windows, abre `iniciar.bat`: prepara un entorno virtual, instala las dependencias y abre la aplicación en el navegador.

También puedes iniciar manualmente:

```powershell
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python run.py
```

En macOS/Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python run.py
```

La interfaz está en <http://127.0.0.1:8765>. `python run.py --no-browser --port 8766` permite cambiar el puerto. Cierra el proceso con Ctrl+C.

## Funciones

- Importación XLSX con selección de hoja, CSV y TSV; separadores y decimales configurables para CSV.
- Explorador con paginación, búsqueda, tipos de variable, conteo de ausentes y edición de celdas con doble clic o Enter.
- Asistente de descriptivos, correlación, regresión OLS, comparación de dos grupos, frecuencias, histogramas y dispersión. Muestra el comando antes de ejecutar.
- Consola con historial mediante flechas arriba/abajo, errores legibles y referencia integrada.
- Transformaciones, filtros y deshacer hasta 20 cambios, incluidas importaciones y ediciones.
- Resultados con tablas, coeficientes, errores estándar, valores p, intervalos de confianza y gráficos SVG exportables.
- Exportación de datos a Excel y CSV; exportación del historial a `.do`.
- Guardado y reapertura de proyectos `.studio.json` con datos e historial.
- Datos sintéticos incluidos para practicar; no se presentan como datos reales.

## Primer análisis

Pulsa **Explorar ejemplo** y prueba:

```stata
describe
summarize salario educacion experiencia
tabulate sector
correlate salario educacion experiencia
regress salario educacion experiencia, robust
ttest salario, by(teletrabajo)
histogram salario
scatter salario experiencia
generate log_salario = log(salario)
replace salario = salario * 1.05 if sector == "Tecnología"
count if edad >= 30 & edad < 50
keep if educacion >= 12
undo
rename educacion anos_estudio
sort salario
help
```

Los nombres de columna se normalizan: `Año de estudio` pasa a `Ano_de_estudio`; los duplicados reciben sufijos. Las condiciones admiten comparaciones, `&`, `|`, `!`, paréntesis y `missing(variable)`. Las transformaciones admiten `+ - * / ** ^`, `log`, `ln`, `sqrt`, `abs` y `exp`. No se ejecuta Python ni código del sistema a través de los comandos.

Se admiten tanto `regress salario educacion if edad >= 30, robust` como `regress salario educacion, robust if edad >= 30`. No se admiten prefijos `by:`, variables factoriales, ponderaciones, macros, bucles, panel, series temporales, modelos logit/probit, paquetes de Stata ni lectura `.dta`. La consola ejecuta un comando por vez. El historial `.do` es una referencia del análisis; las importaciones y las ediciones manuales aparecen como comentarios y no se pueden reproducir automáticamente. Guarda el proyecto para conservar el estado exacto de los datos.

## Criterios estadísticos

- Descriptivos: ausentes excluidos por variable; desviación estándar muestral (`ddof=1`).
- Correlación de Pearson: casos completos sobre todas las variables elegidas.
- OLS: constante incluida, casos completos, rechazo explícito de colinealidad perfecta. `robust` emplea HC1 y distribución t para inferencia.
- Prueba t: Welch bilateral, sin asumir igualdad de varianzas, exactamente dos grupos.
- Comparaciones con valores ausentes: siempre falsas; usa `missing()` para seleccionarlos. No se replica el ordenamiento especial de los ausentes de Stata.
- Histogramas: intervalos automáticos de NumPy. Dispersión: muestra determinista de hasta 5.000 casos para mantener fluidez.

Motor basado en [pandas](https://pandas.pydata.org/docs/), [SciPy](https://docs.scipy.org/doc/scipy/) y [statsmodels](https://www.statsmodels.org/stable/regression.html).

## Datos y límites

El servidor escucha solo en `127.0.0.1`. No hay servicios externos, telemetría ni recursos de terceros necesarios para utilizar la interfaz. La instalación inicial necesita internet. Los datos se mantienen en memoria, separados por una cookie de sesión del navegador; **se pierden al detener el servidor o tras 24 horas de inactividad**. Descarga un proyecto antes de cerrar. Los proyectos descargados contienen los datos completos, sin cifrar.

Límite por importación: 20 MB, 250.000 filas y 500 columnas. Esta versión está pensada para análisis locales de tamaño moderado; conserva copias de datos para deshacer y no es un servidor multiusuario para publicar en internet. Los libros Excel se leen por valores almacenados, sin calcular fórmulas. Se admiten XLSX, no XLS antiguo. CSV debe estar codificado en UTF-8. Exportar Excel/CSV antepone una comilla a textos que podrían ejecutarse como fórmulas; el proyecto JSON conserva su valor original. El guardado JSON no garantiza conservar tipos especializados como categorías o fechas al reabrirlos.

## Desarrollo y verificación

```powershell
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -q
node --check static/app.js
```

`requirements-lock.txt` registra todas las versiones del entorno verificado (incluidas las herramientas de pruebas). Puedes instalarlo con `pip install -r requirements-lock.txt` para replicarlo. La prueba opcional `node tests/browser-export.cjs` requiere Playwright y un servidor local en marcha; comprueba una descarga real y la reapertura del proyecto en una sesión independiente.

Pruebas de resultados numéricos contra SciPy, casos ausentes, regresión singular, transformaciones, deshacer, aislamiento de sesiones, importación de varias hojas, CSV decimal europeo y exportación/reapertura de proyectos. GitHub Actions ejecuta las pruebas en cada push y pull request.

Estructura: `app/engine.py` contiene el lenguaje y los cálculos; `app/main.py` la API y las sesiones; `static/` la interfaz sin dependencias de compilación; `tests/` las pruebas. No hace falta Node para ejecutar la aplicación.
