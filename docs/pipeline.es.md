# Pipeline Alkosto–Algolia

Documento para el equipo (Alkosto · Yalo · Agent Studio). Explica cómo el catálogo de Alkosto llega, dos veces al día y sin intervención manual, a los índices de Algolia que usan el bot de Yalo y los agentes de Agent Studio; qué hay en cada pieza, cómo se monitorea, cómo se extiende y qué hacer cuando algo falla.

Este archivo es la versión canónica. Existe una copia con formato en [claude.ai](https://claude.ai/code/artifact/ee158764-72ef-4810-810d-1d3369374056) (privada). La referencia técnica para desarrolladores es el [README](../README.md), en inglés.

- **Repositorio:** <https://github.com/Wunderbot-Git/alkosto-yalo-feed>
- **Aplicación Algolia:** `QX5IPS1B1Q` (región US)
- **Responsable:** Philipp Hasskamp
- **Última revisión:** 2 de septiembre de 2026

**¿Nuevo aquí?** Empieza por [§12 Cómo empezar](#12-cómo-empezar).

---

## 1. Resumen

Alkosto publica un CSV con todo su catálogo (~11.800 productos, ~920 columnas). Un workflow de GitHub Actions lo descarga, se queda con las categorías relevantes, limpia y enriquece cada producto, y publica varios archivos JSON en el repositorio. Algolia lee esos JSON por HTTP con *connectors* y reconstruye cada índice. Nadie ejecuta nada a mano.

```
Alkosto (CSV, Basic Auth)
   │  06:45 · 12:45 Bogotá
   ▼
GitHub Actions ── descarga, filtra, limpia, deriva campos, imágenes al CDN, un JSON por índice
   │  commit automático solo si cambió
   ▼
Repositorio (main) ── raw.githubusercontent.com, público, caché 5 min
   │  08:00 · 14:00 Bogotá
   ▼
Connectors de Algolia ── full reindexing: borran y recargan cada índice
   │
   ├─► Índice principal ─► bot de Yalo (WhatsApp)
   └─► agent_studio_* ─► agentes de Agent Studio
```

**Automatizado:** descarga y filtrado; limpieza (NaN, columnas vacías, ceros iniciales en EAN); campos derivados (tipo de producto, % descuento, precios por medio de pago, pulgadas de pantalla); URLs de imagen al CDN; un JSON por índice; recarga de todos los índices.

**Manual:** crear un connector cuando se agrega un índice; cambiar reglas o sinónimos (por script o dashboard, siempre con commit); renovar credenciales si Alkosto las cambia.

## 2. Componentes

### 2.1 La fuente: datafeed de Alkosto

| | |
|---|---|
| URL | `https://www.alkosto.com/alkostows/integration/datafeedfull/productFeed.csv` |
| Acceso | Basic Auth. Usuario y contraseña viven como *secrets* en GitHub (§9). |
| Tamaño | ~32 MB, ~11.800 filas, ~920 columnas; la mayoría vacías para un producto dado. |
| Identificador | Columna `Identificador del producto` = EAN. Algunos empiezan por cero (`010343945418`); se conservan como texto. |
| Categoría | Columna `Categoría`, ruta jerárquica con `>`: `Electrodomésticos>Refrigeración>Neveras`. |

### 2.2 El repositorio y sus archivos

| Archivo | Qué hace |
|---|---|
| `.github/workflows/feed.yml` | El workflow: cron, pasos y commit automático. |
| `process_alkosto_products.py` | Pipeline principal. Descarga, filtra por `CATEGORY_PREFIXES`, limpia, deriva campos y escribe `filtered_products.json`. Aquí vive el mapa categoría → `tipo_producto`. |
| `replace_image_urls.py` | Reescribe los enlaces de imagen al CDN: `cdn.dam.alkosto.com/products/<EAN>/<EAN>-001.webp`. |
| `agent_indices.json` | Configuración de los índices de Agent Studio: qué tipos entran en cada uno y qué atributos ve el agente. |
| `build_agent_indices.py` | Genera un `agent_studio_*.json` por entrada del archivo anterior. |
| `transform_to_schema.py` | Convierte computadores al *schema limpio* (campos en inglés, numérico + etiqueta). Alimenta `agent_studio_computadores` y el sandbox. |
| `filter_subset.py` | Recorte genérico por `tipo_producto`. Genera `filtered_computadores_tablets.json`. |
| `algolia/<índice>/` | Configuración de Algolia versionada: `settings.json`, `synonyms.json`, `rules.json` por índice. |
| `scripts/export_algolia_config.py` | Baja la configuración viva de todos los índices a `algolia/`. Correr después de tocar algo en el dashboard. |
| `scripts/apply_algolia_config.py` | Sube `algolia/<índice>/` al índice; con `--load archivo.json` hace la primera carga de un índice nuevo. |
| `.env.example` | Variables de los scripts locales. Se copia a `.env` (ignorado por git). |
| `requirements.txt` | `requests`, `pandas`, `python-dotenv`. Python 3.12 en el runner. |

### 2.3 Los archivos publicados

Cada JSON es un array de objetos, público en `https://raw.githubusercontent.com/Wunderbot-Git/alkosto-yalo-feed/main/<archivo>`. GitHub los sirve por CDN con caché de 5 minutos.

| Archivo | Records | Lo consume |
|---|---|---|
| `filtered_products.json` | ~4.980 | Índice principal de Yalo |
| `agent_studio_celulares.json` | ~440 | `agent_studio_celulares` |
| `agent_studio_computadores.json` | ~460 | `agent_studio_computadores` |
| `agent_studio_tv.json` | ~250 | `agent_studio_tv` |
| `agent_studio_electrodomesticos.json` | ~940 | `agent_studio_electrodomesticos` |
| `filtered_computadores_tablets.json` | ~350 | Nadie por ahora (subset laptop + desktop + tablet) |
| `filtered_agente_computadores.json` | ~460 | `Philipp_Alkosto_AI`, sandbox de prototipos (§4) |

### 2.4 Los connectors de Algolia

Un connector es la pareja *source* (URL del JSON) + *destination* (índice) + *task* (cuándo y cómo). Todos usan el conector **JSON**, autenticación *None*, sin transformación, y la estrategia **Full reindexing**: cada corrida reconstruye el índice completo, así los productos que desaparecen del feed desaparecen también del índice. Se administran en Algolia → *Connectors*; el historial de corridas está en *Connector Debugger*.

## 3. El ciclo diario

Dos ciclos idénticos. Los horarios están escalonados a propósito: GitHub Actions no arranca puntual (su cola retrasa los jobs programados entre 30 y 50 minutos) y el JSON tarda hasta 5 minutos en refrescarse en el CDN. El connector se programa 75 minutos después para leer siempre datos frescos.

| Hora Bogotá | UTC | Qué pasa |
|---|---|---|
| 06:45 | 11:45 | Se programa el workflow. Alkosto ya publicó el CSV de la mañana. |
| ≈ 07:00–07:35 | | El job arranca de verdad (delay de GitHub). Tarda ~30 s. |
| 08:00 | 13:00 | Los connectors leen los JSON y reconstruyen los índices. |
| 12:45 | 17:45 | Segundo workflow. |
| 14:00 | 19:00 | Segunda recarga. Precios de la tarde en producción. |

> **Por qué importa el escalonamiento.** En agosto de 2026 el connector estaba 20 minutos después del workflow; como GitHub arrancaba 40 minutos tarde, leía el JSON del día anterior y el bot mostró precios viejos hasta la tarde. El síntoma, si vuelve: índice al día por la tarde, desactualizado por la mañana.

```
# GitHub Actions — .github/workflows/feed.yml   (UTC)
45 11 * * *     # 06:45 Bogotá
45 17 * * *     # 12:45 Bogotá

# Todos los connectors de Algolia
0 13,19 * * *   # 08:00 y 14:00 Bogotá
```

## 4. Los índices

| Índice | Contenido | Records | Formato | Uso |
|---|---|---|---|---|
| `Yalo_computadores_tables_monitores_impresores_pantallas` | 14 árboles de categoría, 106 tipos de producto | ~4.980 | Crudo enriquecido | Bot de Yalo |
| `agent_studio_celulares` | Smartphones | ~440 | Crudo enriquecido | Agente |
| `agent_studio_computadores` | Laptops, desktops, all-in-one, tablets, monitores, impresoras, tintas, papel, proyectores | ~460 | **Schema limpio** | Agente |
| `agent_studio_tv` | Televisores, barras de sonido, proyectores | ~250 | Crudo enriquecido | Agente |
| `agent_studio_electrodomesticos` | Refrigeración, lavado, cocina (piso y empotre), climatización | ~940 | Crudo enriquecido | Agente |
| `Philipp_Alkosto_AI` (con espacio final) | Sandbox de prototipos | ~460 | Schema limpio | Pruebas, fuera de producción |

El nombre del índice principal es histórico (empezó solo con computadores) y se mantiene para no romper la integración de Yalo. Un producto puede estar en varios índices de agente (las barras de sonido en TV y, cuando exista, en Audio); es intencional.

**El sandbox.** `Philipp_Alkosto_AI` recibe los mismos datos que `agent_studio_computadores` (a través de `filtered_agente_computadores.json`), pero su configuración de relevancia es deliberadamente independiente: no está en `algolia/`, los scripts no lo tocan y lo que se cambie ahí nunca llega a Yalo ni a Agent Studio. Sirve para probar ajustes sin riesgo. No borrarlo.

### 4.1 Los dos formatos de registro

**Crudo enriquecido** — columnas originales de Alkosto en español más los campos derivados del §5. Identificador único: `Identificador del producto`.

```json
{ "Identificador del producto": "8806097665427",
  "Título": "Celular SAMSUNG S25 256GB 5G…",
  "Memoria RAM": "12 GB",
  "tipo_producto": "celular",
  "descuento_porcentaje": 56 }
```

**Schema limpio** (solo computadores) — campos en inglés, cada spec dos veces: valor numérico para filtrar y etiqueta para mostrar. Sin campos interpretativos. Identificador único: `objectID`.

```json
{ "objectID": "195950715095",
  "name": "MacBook Pro 16\" …",
  "category": "laptop",
  "ram_gb": 48, "ram_label": "48 GB",
  "screen_inches": 16.2 }
```

> Al crear un connector, *Unique property identifier* debe ser `Identificador del producto` para los índices crudos y `objectID` para `agent_studio_computadores`. Con el equivocado, Algolia rechaza la fuente.

## 5. Qué trae cada registro

| Campo | Tipo | Cómo se calcula | Para qué sirve |
|---|---|---|---|
| `tipo_producto` | texto | Por prefijo de la ruta de categoría (mapa en `process_alkosto_products.py`). `TV>Smart TV>` → `televisor`. Una marca nueva entra sola. | Filtro por tipo; destino de las reglas; recortes por índice. |
| `descuento_porcentaje` | entero | `(lista − venta) / lista × 100`, **truncado** (56,52 → 56), igual que alkosto.com. | Filtros «más del 30 %», ranking de ofertas. |
| `precio_<medio>` | entero | De `Precio por método de pago` (`codensa:2518070;tarjeta_alkosto:2498070`): un campo por medio. Medios nuevos aparecen solos. | Precio con tarjeta específica. |
| `metodos_pago` | lista | Los medios detectados. | Facet. |
| `screen_size_inches` | número | «Pulgadas» en `Tamaño Pantalla_2` (monitores, TV) y luego en `_1`; si solo hay centímetros, convierte. | `screen_size_inches >= 27`. |
| `Enlace link1 / link2` | URL | Reescritas al CDN. | Imagen estable. |

Limpieza aplicada a todos: se eliminan columnas totalmente vacías (~920 → ~110) y, por producto, los atributos vacíos o `NaN` (quedan 27–57). El EAN se lee como texto para conservar ceros iniciales. `EXCLUDED_SUBCATEGORIES` está vacía. `Smartwatch>` está mapeada pero Alkosto no la incluye hoy en el feed.

## 6. Configuración en Algolia

La configuración de cada índice está versionada en `algolia/<índice>/` y se aplica con scripts, no a mano (§6.4).

**Común a todos:** español (`queryLanguages`, `removeStopWords`, `ignorePlurals` = `["es"]`); 44 grupos de sinónimos compartidos (portátil↔laptop↔notebook, nevera↔refrigerador, airfryer↔freidora de aire, mouse↔ratón, powerbank↔batería externa…); cualquier campo numérico es filtrable sin configuración.

**Índice principal:** 21 atributos buscables en orden de prioridad (`Título`, `Marca`, `Categoría`, características clave, procesador, RAM…); facets `Categoría`, `Marca`, `Memoria RAM`, `metodos_pago`, `tipo_producto`; ~47 reglas que convierten una palabra en filtro de tipo («portátil» → `laptop`, «refrigerador» → `nevera OR nevecon`); ranking `desc(Disponibilidad)`.

**Índices de Agent Studio:** los agentes reciben cada producto completo en su contexto, así que *menos es más*. `attributesToRetrieve` recortado a lo relevante de la vertical (RAM, cámaras y batería en celulares; pulgadas, resolución y HDMI en TV; litros, kilos, BTU y eficiencia en electrodomésticos) — la lista está en `agent_indices.json`; facets por vertical; **solo las reglas de su vertical** (una regla ajena en un índice pequeño devuelve cero resultados); ranking `desc(Disponibilidad)`, `desc(descuento_porcentaje)`.

> Comportamiento esperado, no error: buscar «celular» en electrodomésticos devuelve neveras Samsung cuya descripción dice «contrólala desde tu celular». Los agentes deben filtrar por `tipo_producto`.

### 6.4 Configuración como código

```bash
cp .env.example .env                                   # llenar las llaves
python scripts/export_algolia_config.py                # dashboard → repo, todos los índices
python scripts/apply_algolia_config.py agent_studio_tv # repo → índice
python scripts/apply_algolia_config.py agent_studio_audio --load agent_studio_audio.json   # índice nuevo
```

Regla: un cambio se hace en el repo y se aplica, o se hace en el dashboard y se exporta — pero siempre termina en un commit. Así nunca hay dos versiones de la verdad.

## 7. Cómo extender

**Agregar una categoría al índice principal.** Ubicar la ruta exacta (el log del workflow lista todas las subcategorías detectadas). En `process_alkosto_products.py`, agregar el prefijo a `CATEGORY_PREFIXES` y una línea por subcategoría a `TIPO_PRODUCTO_PREFIXES` (rutas específicas antes que genéricas). Push. Verificar en el JSON publicado el nuevo `tipo_producto` y que no queden productos sin tipo. Agregar regla y sinónimos en `algolia/…` y aplicar.

**Agregar un índice de Agent Studio.** Entrada en `agent_indices.json` (nombre con prefijo `agent_studio_`, tipos, atributos). Push. Crear la carpeta `algolia/<índice>/` copiando la de un índice hermano y ajustar; `apply --load` con el JSON generado. Connector en Algolia → Connectors → JSON: URL del archivo, identificador según §4.1, *Create one for me*, cron `0 13,19 * * *`, full reindexing. Candidatos ya definidos: audio, pequeños electrodomésticos, videojuegos, casa inteligente + cámaras, accesorios.

**Agregar un campo derivado.** En `convert_to_json` de `process_alkosto_products.py`, dentro del bucle por registro, antes de la limpieza de vacíos. **El índice guarda hechos, no interpretaciones**: sí pulgadas, litros, porcentaje; no «ideal para gaming». Eso lo decide el agente.

## 8. Monitoreo y runbook

**Comprobar un día:** <https://github.com/Wunderbot-Git/alkosto-yalo-feed/actions> muestra dos corridas verdes; `main` tiene commits «feed: refresh …» recientes; Algolia → Connectors → *Connector Debugger* muestra cada ingestión con su cantidad. GitHub avisa por correo al dueño del repositorio si una corrida falla.

```bash
gh run list --workflow=feed.yml --repo Wunderbot-Git/alkosto-yalo-feed --limit 6
gh workflow run feed.yml --repo Wunderbot-Git/alkosto-yalo-feed     # corrida manual
```

**Forzar una actualización:** Actions → *Run workflow*; esperar el commit (~1 min); **esperar 5 minutos más** (caché del CDN); Connectors → tarea → *Run*. Si se corre el connector antes, lee la versión anterior.

| Síntoma | Causa | Qué hacer |
|---|---|---|
| Precios de ayer por la mañana, correctos por la tarde | Connector leyó antes de que GitHub terminara o dentro del caché del CDN | Comparar horas en Actions y Connector Debugger; ampliar el margen |
| Connector «success» pero el índice no cambia; tareas `notPublished` | Límite de registros del plan de Algolia; escrituras descartadas en silencio | Settings → Usage; liberar registros o ampliar plan (abril 2026) |
| Un producto «no está» en el índice | Se buscó el EAN como texto; no es atributo buscable | Consultar por `objectID`; si falta de verdad, revisar `CATEGORY_PREFIXES` |
| Imagen rota en EAN que empieza por cero | Se quitó `dtype=str` del lector de CSV | Restaurarlo |
| 403 en un índice nuevo aunque el key lo incluye | Espacio al final del nombre (pasó dos veces) | Escribir el nombre y pulsar Enter; verificar con la API de keys |
| Cero resultados para una palabra de otra vertical en un índice de agente | Se copió una regla ajena | Dejar solo reglas de tipos presentes en ese índice |
| Workflow en rojo: «job was not acquired by Runner» | Infraestructura de GitHub | Relanzar |

## 9. Accesos y llaves

| Credencial | Dónde vive | Alcance |
|---|---|---|
| `ALKOSTO_USERNAME` / `ALKOSTO_PASSWORD` | GitHub → Settings → Secrets → Actions | Solo lectura del datafeed. Lo único que necesita el workflow. |
| Key «principal» | `.env` local (`ALGOLIA_ADMIN_API_KEY`) | Índice principal de Yalo. |
| Key «agent studio» | `.env` local (`ALGOLIA_AGENT_KEY`) | Comodín `agent_studio_*`, incluye `deleteIndex`. |
| Keys de los connectors | Generadas por Algolia (*Create one for me*) | Una por connector, invisibles. |

Cada colaborador crea **sus propias** llaves restringidas siguiendo `.env.example`; no se comparten. Nunca pegar keys en chat, commits ni JSON: el repositorio es público. Ninguna llave de este sistema alcanza `alkostoIndexAlgoliaPRD` (índice de la web).

## 10. Decisiones de diseño

- **GitHub Actions en lugar de servidor propio.** Gratis para repos públicos, sin infraestructura, cada corrida versionada, el repo sirve de hosting. El cron en un Mac dependía de que estuviera encendido.
- **Transformar en Python, no en Algolia.** La lógica ya existía, es testeable en local y queda versionada; repartirla en dos sistemas la haría inmantenible.
- **Prefijo de categoría, no lista de rutas.** Las marcas nuevas entran solas. Lo mismo para medios de pago.
- **`tipo_producto` como pieza central.** Convierte cada regla en una línea y desacopla al bot de la taxonomía de Alkosto.
- **Un índice por agente, derivado del feed principal.** Índices pequeños con pocos atributos dan mejores respuestas; los pipelines paralelos se desvían (el de celulares perdió una marca antes de retirarse).
- **Hechos, no interpretaciones.** El agente juzga con su prompt sobre datos objetivos.

## 11. Glosario

- **Connector** — integración de Algolia que trae datos de una fuente externa a un índice según un cron.
- **Full reindexing** — reconstruye el índice completo en cada corrida; elimina lo que ya no está en la fuente.
- **objectID** — identificador único en Algolia. Aquí siempre el EAN.
- **Facet** — atributo declarado para filtrar. Un filtro sobre un atributo no declarado se ignora en silencio.
- **Rule** — si la consulta contiene X, aplica el filtro Y. Aquí: palabra → `tipo_producto`.
- **attributesToRetrieve** — atributos que Algolia devuelve por resultado; controla cuánto recibe un agente.
- **Raw URL** — URL pública de un archivo en GitHub; caché de 5 minutos.
- **Agent Studio** — producto de Algolia para agentes conversacionales que consultan índices.

## 12. Cómo empezar

Lista para el primer día de un colaborador nuevo.

1. **Accesos que pedir**
   - Colaborador en el repositorio `Wunderbot-Git/alkosto-yalo-feed` (lo otorga Philipp). Sin esto se puede leer todo, pero no hacer push ni lanzar el workflow.
   - Miembro de la aplicación Algolia `QX5IPS1B1Q` con permiso para crear API keys y connectors.
   - Opcional: `gh` (GitHub CLI) autenticado, para los comandos del §8.
2. **Entorno local**

   ```bash
   git clone https://github.com/Wunderbot-Git/alkosto-yalo-feed && cd alkosto-yalo-feed
   python3.12 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env        # crear llaves propias en Algolia y pegarlas aquí; nunca se commitea
   ```

3. **Correr el pipeline en local** (útil para probar un cambio de categorías antes de hacer push)

   ```bash
   ALKOSTO_USERNAME=… ALKOSTO_PASSWORD=… python process_alkosto_products.py   # descarga productFeed.csv
   python process_alkosto_products.py --skip-download                          # reutiliza el CSV ya descargado
   python replace_image_urls.py filtered_products.json
   python build_agent_indices.py --input filtered_products.json --config agent_indices.json
   ```

   El CSV (~32 MB) y los `filtered_*.csv` están ignorados por git; solo los JSON se commitean, y eso lo hace el workflow.
4. **Leer en este orden:** §1 (qué es), §3 (cuándo pasa), §4–5 (qué hay en los índices), §8 (qué mirar cuando algo falla). El README tiene el detalle técnico.
5. **Antes del primer cambio:** todo cambio de relevancia en Algolia termina en un commit (§6.4); todo cambio de categorías se verifica en el JSON publicado antes de tocar Algolia (§7).

## 13. Cronología

Fechas aproximadas; el historial de git tiene el detalle.

| Cuándo | Qué |
|---|---|
| Nov 2025 | Script local en un Mac con cron. Solo computadores y tablets. CSV → JSON. |
| Abr 2026 | Filtro por prefijo de categoría. Primer índice en Algolia; se descubre el límite de registros del plan (`notPublished`). Migración a GitHub Actions + connector. Ajustes pedidos por Yalo: español, facets, sinónimos, reglas. Nace `tipo_producto`. Entran TVs. Precios por medio de pago. |
| May 2026 | `descuento_porcentaje`. Subset computadores + tablets. Entran celulares, tintas y papel. |
| Jun 2026 | Ceros iniciales en EAN (imágenes rotas). Schema limpio para computadores → `Philipp_Alkosto_AI`. Entran refrigeración, lavado y proyectores. |
| Ago 2026 | `screen_size_inches`. Descuento truncado para coincidir con la web. Desfase connector/workflow → crons 6:45/12:45 y 8:00/14:00. Entran 11 categorías (audio, videojuegos, cámaras, casa inteligente, accesorios, pequeños electro, climatización, cocina…): el índice pasa de 1.500 a ~5.000. |
| Sep 2026 | Cuatro índices de Agent Studio derivados del feed principal, configuración como código (`algolia/`, `scripts/`), retiro del pipeline paralelo de celulares. `Philipp_Alkosto_AI` queda como sandbox. |
