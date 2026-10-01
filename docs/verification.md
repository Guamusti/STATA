# Verificación de la primera versión

Verificada en Windows con Python 3.12 y Chrome, el 1 de octubre de 2026.

## Pruebas automáticas

`python -m pytest -q`: **22 pruebas correctas**. Incluyen estadísticos descriptivos, inferencia OLS frente a SciPy, HC1, Welch, ausentes, casos completos, rechazo de modelos singulares, filtros y transformaciones, protección del intérprete, importación XLSX/CSV, edición, deshacer, aislamiento de sesiones y guardado/reapertura.

`node --check static/app.js`: correcto. `pip check`: sin conflictos de dependencias.

## Flujo comprobado en navegador

- Cargar ejemplo: 240 observaciones y 7 variables.
- Asistente de regresión: `regress salario educacion experiencia, robust`; 236 casos completos, R² = 0,8004; cuatro observaciones excluidas por ausentes.
- Consola: histograma de salario con frecuencias y etiquetas.
- Importar `Encuesta`, segunda hoja de un libro XLSX: cinco filas y dos variables.
- Editar la primera celda de ingreso de 1500 a 1550,5; cambio visible y registrado en el historial.
- Descarga real de un proyecto y reapertura en otro contexto de navegador: 240 filas y 7 variables restauradas. Prueba con Playwright y Chrome en `tests/browser-export.cjs`.
- Navegación entre datos, resultados e historial, sin errores JavaScript detectados.
- Pantalla de 390 × 844: ancho del documento de 390 píxeles, sin desbordamiento horizontal de la página. La navegación y las tablas permiten desplazamiento interno.

Se corrigió el solapamiento de la consola sobre los botones en ventanas bajas. La consola tiene ahora espacio propio en la distribución. Los valores p pequeños se muestran con notación científica en lugar de redondearse a cero.

La herramienta `agent-browser` canceló las descargas en su sesión; una prueba independiente con Chrome y Playwright confirmó que la descarga y reapertura reales funcionan.

## Límites de esta verificación

No se han contrastado resultados contra una instalación propietaria de Stata, ni realizado pruebas de carga con archivos al límite de 250.000 filas. El soporte de comandos es el documentado en README y la ayuda integrada. No se ha probado todavía el iniciador en un equipo Windows sin Python ni dependencias previas.
