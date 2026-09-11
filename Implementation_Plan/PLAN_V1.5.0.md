# xactions-py — Plan de Implementación v1.5.0

> **Versión:** 1.0.0  
> **Fecha:** 2026-08-17  
> **Rama:** `feature/v1.5.0`  
> **Base:** v1.4.0 (`aad0c14`)  
> **Objetivo:** Endurecer el toolkit (packaging, GraphQL, seguridad) y añadir features de alto valor sin romper la API actual.

---

## Filosofía de trabajo

- **Un bloque a la vez.** Bloque terminado → tests verdes → te aviso → autorizas → siguiente.
- Cada bloque se cierra con commit convencional en la rama feature.
- TDD cuando sea práctico (test rojo → fix → verde).
- YAGNI: no inventamos features que no pidan uso real.
- No se toca `main` ni se hace push hasta que autorices el cierre del plan.

---

## Estado de sincronización (al iniciar)

| Repo | Estado |
|------|--------|
| Local `xactions-py` | `main` = `origin/main` @ `aad0c14` v1.4.0 |
| Tests | 40 passed |
| Lint (ruff) | OK |
| Plan previo | No existía en este repo (sí en TrendScope, ya completado) |

---

## Resumen de bloques

| Bloque | Nombre | Objetivo | Impacto |
|--------|--------|----------|---------|
| 0 | Baseline / higiene | LICENSE, py.typed, tipado, baseline CI | Bajo riesgo, cimientos |
| 1 | Reempaquetado | Paquete `xactions` instalable, sin `sys.path` | **Alto** — desbloquea todo lo demás |
| 2 | Resiliencia GraphQL | Auto-refresh de query IDs + errores claros | **Alto** — supervivencia a deploys de X |
| 3 | Seguridad cookies | Warnings, redacción en logs, mejores defaults | Medio-alto |
| 4 | Rate-limit + paginación | Headers proactivos, pages de 200, menos 429 | Medio |
| 5 | Features nuevas | Search ops, threads, compare, watch | Alto valor de producto |
| 6 | Release + ecosistema | README, CHANGELOG, push GitHub, TrendScope | Cierre |

**Estimación total:** v1.5.0 sale con B0–B4 + parte de B5; B6 documenta y publica.

---

## Mapa de dependencias

```
B0 (higiene)
 └─► B1 (packaging)  ──► B2 (GraphQL)  ──► B4 (rate-limit)
                          │
                          └─► B3 (seguridad) ──► B5 (features) ──► B6 (release)
```

B1 es el cuello de botella: hasta que el paquete no esté limpio, todo lo demás se apila sobre `sys.path` frágil.

---

# BLOQUE 0 — Baseline / higiene

**Objetivo:** Dejar la base impecable sin cambiar comportamiento.

### Tareas

| # | Tarea | Detalle |
|---|-------|---------|
| 0.1 | `LICENSE` MIT | Archivo real en la raíz (README ya lo promete) |
| 0.2 | `py.typed` | Marcar paquetes como typed |
| 0.3 | Tipado limpio | `callable` → `Callable` en `actions.bulk_unfollow`; anotaciones coherentes |
| 0.4 | Baseline tests | 40 tests + ruff en verde tras cambios |
| 0.5 | Commit | `chore: v1.5.0 baseline — LICENSE, py.typed, typing` |

### Criterios de aceptación
- [x] `LICENSE` existe y dice MIT
- [x] `py.typed` presente
- [x] `pytest` 40+ passed
- [x] `ruff check` OK
- [x] Sin cambios de comportamiento en CLI/API

---

# BLOQUE 1 — Reempaquetado (crítico)

**Objetivo:** Que `pip install -e .` dé un paquete usable sin hacks de path.

### Problema actual
- `sys.path.insert` en `cli/xactions.py`, `actions/actions.py`, `mcp_tools/server.py`
- README enseña `from src.scraper...` (nombre `src` no es un paquete público)
- Entry point depende de top-level `cli`

### Diseño destino

```
xactions-py/
├── src/
│   └── xactions/           # paquete instalable
│       ├── __init__.py     # __version__, exports públicos
│       ├── py.typed
│       ├── client.py
│       ├── pool.py
│       ├── scrapers.py
│       ├── actions.py
│       ├── analyzer.py
│       ├── db.py
│       ├── gql_refresh.py  # (llega en B2)
│       ├── cli.py
│       └── mcp_server.py
├── tests/
├── pyproject.toml
└── ...
```

Imports públicos:
```python
from xactions import TwitterClient, search_tweets_sync
from xactions.scrapers import scrape_profile
from xactions.cli import cli
```

### Tareas

| # | Tarea | Detalle |
|---|-------|---------|
| 1.1 | Mover módulos a `src/xactions/` | Unificar scraper/actions/analytics/storage/cli/mcp |
| 1.2 | Eliminar todos los `sys.path.insert` | |
| 1.3 | Actualizar `pyproject.toml` | packages=`xactions*`, scripts=`xactions=xactions.cli:cli` |
| 1.4 | Re-exportar API pública en `__init__.py` | Compat con wrappers sync |
| 1.5 | Actualizar tests e imports internos | |
| 1.6 | Actualizar README (imports de ejemplo) | |
| 1.7 | Verificar entry point `xactions --help` y MCP import | |
| 1.8 | Commit | `refactor!: rename package layout to src/xactions (BREAKING imports)` |

### Compatibilidad
- **BREAKING** para quien importara `from src.scraper...` — se documenta en CHANGELOG con guía de migración de 3 líneas.
- CLI (`xactions ...`) y MCP se mantienen igual en UX.

### Criterios de aceptación
- [x] `pip install -e ".[dev,mcp]"` limpia
- [x] `python -c "from xactions import TwitterClient"` funciona
- [x] `xactions --help` funciona
- [x] `python -m xactions.mcp_server` importable (requiere extra `mcp`)
- [x] Tests en verde (imports actualizados)
- [x] Cero `sys.path.insert` en el código fuente

---

# BLOQUE 2 — Resiliencia GraphQL

**Objetivo:** Que un deploy de X no mate el proyecto por completo.

### Diseño

1. **`endpoints.json`** (o `endpoints.py`) fuera del lógica de red — query IDs + features versionables.
2. **`gql_refresh.py`** — descarga el bundle JS de `https://x.com`, extrae `queryId`/`operationName` y actualiza el store local.
3. **Fallback:** si un queryId devuelve 404/GraphQL error tipo “query not found”, intenta refresh una vez y reintenta.
4. **CLI `xactions gql-status`** — muestra endpoints cargados, última actualización, y si refresh está disponible.
5. **Error claro** cuando no se puede refrescar (sin red / bundle no parseable).

### Tareas

| # | Tarea | Detalle |
|---|-------|---------|
| 2.1 | Extraer `GRAPHQL_ENDPOINTS` a store externo | Cargado por el client |
| 2.2 | Implementar parser del bundle JS de x.com | Regex/JSON sobre `queryId:"...",operationName:"..."` |
| 2.3 | Auto-refresh en cliente (una vez por endpoint roto) | Con cache en disco `~/.xactions/gql_endpoints.json` |
| 2.4 | CLI `gql-status` / `gql-refresh` | |
| 2.5 | Tests con fixtures de bundle JS fake | Sin pegar a x.com en CI |
| 2.6 | Commit | `feat: auto-refresh GraphQL query IDs from X JS bundle` |

### Criterios de aceptación
- [x] Con bundle fixture, el refresh actualiza IDs
- [x] Endpoint roto → refresh → retry una vez → error claro si falla
- [x] Cache en disco evita re-descargar en cada request
- [x] Tests offline en CI
- [x] Fallback twikit cuando el bundle de X no expone los IDs

---

# BLOQUE 3 — Seguridad de cookies

**Objetivo:** Minimizar fugas accidentales de `auth_token`/`ct0`.

### Tareas

| # | Tarea | Detalle |
|---|-------|---------|
| 3.1 | Warning si se pasan cookies por `--cookies` (CLI) | Sugerir env o `--cookies-file` |
| 3.2 | Redacción en logs | Nunca logear cookie string completa (solo `auth_token=***` / `ct0=***`) |
| 3.3 | Check de permisos en `cookies.txt` en Unix | Warn si world-readable |
| 3.4 | Documentar flujo recomendado | `.env` / keyring manual / file chmod 600 |
| 3.5 | No imprimir cookies en `validate` ni errores | |
| 3.6 | Commit | `fix(security): redact cookies, warn on CLI --cookies, file perms` |

### Criterios de aceptación
- [x] Ningún path de logging imprime el token completo
- [x] `--cookies` emite warning no bloqueante
- [x] Docs actualizadas

---

# BLOQUE 4 — Rate-limit proactivo + paginación

**Objetivo:** Menos 429, más throughput.

### Tareas

| # | Tarea | Detalle |
|---|-------|---------|
| 4.1 | Leer `x-rate-limit-remaining` / `x-rate-limit-reset` por endpoint | Guardar en client |
| 4.2 | Backoff pre-request si remaining=0 | En vez de esperar al 429 |
| 4.3 | `count` de página 20 → hasta 200 donde la API lo permita | Followers/Following/Search/UserTweets |
| 4.4 | Cap de espera de rate limit configurable | Default más honesto (no hard 30s si reset está lejos; opción `max_wait`) |
| 4.5 | Tests unitarios del throttle | |
| 4.6 | Commit | `perf: proactive rate-limit handling + larger page sizes` |

### Criterios de aceptación
- [ ] Con headers de rate limit, el cliente espera antes del 429
- [ ] 1000 followers ≈ ~5 requests en vez de ~50 (cuando la API lo permite)
- [ ] Tests en verde

---

# BLOQUE 5 — Features nuevas

**Objetivo:** Valor de producto sin reescribir el core.

### 5A — Search operators (rápido)
| # | Tarea |
|---|-------|
| 5A.1 | Helper `build_search_query(base, from_user=None, since=None, until=None, min_faves=None, lang=None, ...)` |
| 5A.2 | CLI flags en `search` (`--from`, `--since`, `--min-faves`, `--lang`) |
| 5A.3 | Tests del query builder |

### 5B — Thread builder
| # | Tarea |
|---|-------|
| 5B.1 | `post_thread(client, tweets: list[str], delay=1.5)` encadenando `reply_to_id` |
| 5B.2 | CLI `xactions thread "t1" "t2" ...` o `--from-file` |
| 5B.3 | MCP `x_post_thread` |

### 5C — Compare de cuentas
| # | Tarea |
|---|-------|
| 5C.1 | `compare_accounts(userA, userB)` → métricas lado a lado + engagement |
| 5C.2 | CLI `xactions compare userA userB` |
| 5C.3 | Output JSON/tabla/CSV |

### 5D — Watch / monitor delta
| # | Tarea |
|---|-------|
| 5D.1 | `watch_search(query, interval, state_file)` emite solo tweets nuevos |
| 5D.2 | CLI `xactions watch "query" --interval 60` |
| 5D.3 | State simple en SQLite o JSON en `~/.xactions/` |

> **Nota de alcance:** en v1.5.0 se priorizan **5A + 5B + 5C**. 5D puede quedar como esqueleto o moverse a v1.6 si el bloque se alarga.

### Commit del bloque
`feat: search operators, thread builder, account compare (+ optional watch)`

---

# BLOQUE 6 — Documentación, release y ecosistema

**Objetivo:** Publicar limpio y mantener TrendScope al día.

### Tareas

| # | Tarea | Detalle |
|---|-------|---------|
| 6.1 | README actualizado | Nueva estructura, imports `xactions.*`, features nuevas |
| 6.2 | CHANGELOG v1.5.0 | Added / Changed / Fixed / Breaking |
| 6.3 | Versión en `pyproject.toml` → `1.5.0` | |
| 6.4 | CI sigue verde en 3.10–3.13 + Windows | |
| 6.5 | Merge `feature/v1.5.0` → `main` | **Solo con tu autorización** |
| 6.6 | Push a GitHub | **Solo con tu autorización** |
| 6.7 | Tag `v1.5.0` | |
| 6.8 | TrendScope | Apuntar a la nueva versión / actualizar docs que referencian xactions-py |
| 6.9 | CHANGELOG de TrendScope | Nota de la dependencia actualizada |

---

## Checklist final del plan

- [x] B0 baseline limpio
- [x] B1 packaging instalable
- [ ] B2 GraphQL resiliente
- [ ] B3 cookies seguras (UX + logs)
- [ ] B4 rate-limit + paginación
- [ ] B5 features (5A–5C al menos)
- [ ] B6 docs + push + TrendScope
- [ ] `main` publicada y sincronizada
- [ ] TrendScope documentado

---

## Fuera de alcance (v1.5.x)

- Login automatizado sin cookies
- Chunked upload de video
- Proxy rotation multi-pool
- Dashboard web propio (eso es territorio TrendScope)
- Publicación a PyPI (se puede discutir en v1.6)

---

## Protocolo de avance

1. Yo implemento el bloque.
2. Ejecuto tests + lint.
3. Commit en `feature/v1.5.0`.
4. Te resumo: qué cambió, evidencia (tests), riesgos.
5. **Tú autorizas** → siguiente bloque.
6. Al final de B6, pides push/merge y lo hacemos.
