"""
XActions-PY — GraphQL query ID refresh.

X rota los queryId al desplegar bundles JS. Este módulo:
  1. Parsea el HTML de x.com (responsive-web y x-web) y localiza los bundles.
  2. Extrae pares queryId/operationName (formato clásico y Relay `id`/`name`).
  3. Fallback remoto: parsea el gql.py de twikit (misma fuente que usábamos a mano).
  4. Cachea el resultado en ~/.xactions/gql_endpoints.json.
  5. Mezcla los IDs nuevos sobre los defaults (conserva method/REST).

Todo offline-friendly: los parsers se testean con fixtures sin red.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

_log = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path(os.getenv("XACTIONS_HOME", str(Path.home() / ".xactions")))
DEFAULT_CACHE_PATH = DEFAULT_CACHE_DIR / "gql_endpoints.json"

TWIKIT_GQL_URL = (
    "https://raw.githubusercontent.com/d60/twikit/main/twikit/client/gql.py"
)

# queryId:"...",operationName:"..." (orden puede invertirse; comillas dobles o backticks)
_PAIR_RES = (
    re.compile(
        r'queryId\s*:\s*["`](?P<queryId>[A-Za-z0-9_-]{10,})["`]\s*,\s*'
        r'operationName\s*:\s*["`](?P<operationName>[A-Za-z0-9_]+)["`]'
    ),
    re.compile(
        r'operationName\s*:\s*["`](?P<operationName>[A-Za-z0-9_]+)["`]\s*,\s*'
        r'queryId\s*:\s*["`](?P<queryId>[A-Za-z0-9_-]{10,})["`]'
    ),
)

# Relay moderno: id:`...`,metadata:{},name:`...`,operationKind:`query`
_RELAY_RES = (
    re.compile(
        r"id\s*:\s*[\"`](?P<queryId>[A-Za-z0-9_-]{10,})[\"`]\s*,\s*"
        r"metadata\s*:\s*(?:\{\}|null)\s*,\s*"
        r"name\s*:\s*[\"`](?P<operationName>[A-Za-z0-9_]+)[\"`]"
    ),
    re.compile(
        r"id\s*:\s*[\"`](?P<queryId>[A-Za-z0-9_-]{10,})[\"`][^;]{0,120}?"
        r"name\s*:\s*[\"`](?P<operationName>[A-Za-z0-9_]+)[\"`]"
    ),
)

# twikit: USER_BY_SCREEN_NAME = url('NimuplG1OB7Fd2btCLdBOw/UserByScreenName')
_TIKWIT_URL_RE = re.compile(
    r"""url\(\s*[\"'](?P<queryId>[A-Za-z0-9_-]{10,})/(?P<operationName>[A-Za-z0-9_]+)[\"']\s*\)"""
)

# Bundles del cliente web clásico
_BUNDLE_RE = re.compile(
    r"""https://abs\.twimg\.com/responsive-web/client-web(?:-legacy)?/[A-Za-z0-9._-]+\.js"""
)
# Nuevo x-web entry
_XWEB_ENTRY_RE = re.compile(
    r"""https://abs\.twimg\.com/x-web/[^\"']+\.js"""
)
_SCRIPT_SRC_RE = re.compile(
    r"""<script[^>]+src=["']([^"']+\.js)["']""",
    re.IGNORECASE,
)
_ASSET_REL_RE = re.compile(r"""["'](\./assets/[^"']+\.js)["']""")


def extract_operations(js_text: str) -> dict[str, dict[str, str]]:
    """
    Extrae {operationName: {"queryId": ..., "operationName": ...}} de un bundle JS.
    Soporta formato clásico y Relay. Si un operation aparece varias veces,
    se queda con la última (más reciente en el bundle).
    """
    found: dict[str, dict[str, str]] = {}
    for patterns in (_PAIR_RES, _RELAY_RES):
        for pattern in patterns:
            for m in pattern.finditer(js_text):
                op = m.group("operationName")
                qid = m.group("queryId")
                if op and qid:
                    found[op] = {"queryId": qid, "operationName": op}
    return found


def extract_operations_from_twikit(source: str) -> dict[str, dict[str, str]]:
    """Parsea gql.py de twikit: url('queryId/OperationName')."""
    found: dict[str, dict[str, str]] = {}
    for m in _TIKWIT_URL_RE.finditer(source):
        op = m.group("operationName")
        qid = m.group("queryId")
        found[op] = {"queryId": qid, "operationName": op}
    return found


def load_cache(path: Path | str | None = None) -> dict[str, Any] | None:
    """Lee el cache en disco. Devuelve None si no existe o es inválido."""
    p = Path(path) if path else DEFAULT_CACHE_PATH
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        _log.warning("Cache GraphQL ilegible (%s): %s", p, e)
        return None
    if not isinstance(data, dict) or "endpoints" not in data:
        return None
    return data


def save_cache(
    endpoints: dict[str, dict[str, Any]],
    path: Path | str | None = None,
    source: str = "bundle",
) -> Path:
    """Persiste endpoints en disco. Devuelve la ruta escrita."""
    p = Path(path) if path else DEFAULT_CACHE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": source,
        "endpoints": endpoints,
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _log.debug("Cache GraphQL guardado en %s (%d endpoints)", p, len(endpoints))
    return p


def merge_endpoints(
    base: dict[str, dict[str, Any]],
    discovered: dict[str, dict[str, str]],
) -> dict[str, dict[str, Any]]:
    """
    Actualiza los queryId de `base` con los de `discovered`.
    Conserva method/REST (queryId None) y solo toca operaciones ya conocidas
    o que aparezcan en discovered con queryId válido.
    """
    merged: dict[str, dict[str, Any]] = {k: dict(v) for k, v in base.items()}

    # Mapear por operationName real (puede diferir del key de GRAPHQL_ENDPOINTS,
    # ej. UserLikes -> operationName "Likes")
    by_op: dict[str, str] = {}
    for key, ep in merged.items():
        op = ep.get("operationName")
        if op:
            by_op[op] = key

    updated = 0
    for op, info in discovered.items():
        key = by_op.get(op, op)
        if key in merged:
            old = merged[key].get("queryId")
            if old != info["queryId"]:
                updated += 1
            merged[key]["queryId"] = info["queryId"]
            merged[key]["operationName"] = info["operationName"]
        else:
            # Operación nueva descubierta — se añade sin method especial
            merged[key] = {
                "queryId": info["queryId"],
                "operationName": info["operationName"],
            }
            updated += 1

    _log.info("GraphQL merge: %d queryIds actualizados/añadidos", updated)
    return merged


def _bundle_urls_from_html(html: str) -> list[str]:
    """URLs de JS candidatos desde el HTML de x.com (prioriza main*/entry)."""
    urls: list[str] = []
    for pattern in (_BUNDLE_RE, _XWEB_ENTRY_RE):
        for m in pattern.finditer(html):
            urls.append(m.group(0))
    for m in _SCRIPT_SRC_RE.finditer(html):
        src = m.group(1)
        if src.startswith("//"):
            src = "https:" + src
        if src.startswith("https://") and src.endswith(".js"):
            urls.append(src)
    # únicos preservando orden
    seen: set[str] = set()
    ordered: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            ordered.append(u)
    # preferir main*.js / entry-client* primero
    def _prio(u: str) -> tuple[int, str]:
        name = u.rsplit("/", 1)[-1]
        if name.startswith("main") or name.startswith("entry"):
            return (0, u)
        return (1, u)

    ordered.sort(key=_prio)
    return ordered


async def discover_from_bundles(
    http: httpx.AsyncClient,
    headers: dict[str, str] | None = None,
    max_bundles: int = 12,
    max_assets: int = 40,
) -> dict[str, dict[str, str]]:
    """
    Descarga HTML de x.com y parsea los bundles JS buscando queryIds.
    Sigue imports relativos de x-web (./assets/*.js).
    """
    hdrs = headers or {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
    }
    resp = await http.get("https://x.com", headers=hdrs, follow_redirects=True)
    resp.raise_for_status()
    bundles = _bundle_urls_from_html(resp.text)
    _log.info("Bundles JS candidatos: %d", len(bundles))

    discovered: dict[str, dict[str, str]] = {}
    queue = list(bundles)
    seen: set[str] = set()
    downloaded = 0

    while queue and downloaded < max_assets:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            js = await http.get(url, headers=hdrs, follow_redirects=True)
            js.raise_for_status()
        except httpx.HTTPError as e:
            _log.debug("No se pudo bajar %s: %s", url, e)
            continue
        downloaded += 1
        ops = extract_operations(js.text)
        if ops:
            _log.debug("%s → %d operaciones", url.rsplit("/", 1)[-1], len(ops))
            discovered.update(ops)
        # x-web: seguir assets relativos
        for rel in _ASSET_REL_RE.findall(js.text):
            abs_url = urljoin(url, rel)
            if abs_url not in seen:
                queue.append(abs_url)

        critical = {"UserByScreenName", "UserTweets", "SearchTimeline", "CreateTweet"}
        if critical.issubset(discovered):
            break

    return discovered


async def discover_from_twikit(
    http: httpx.AsyncClient,
    headers: dict[str, str] | None = None,
) -> dict[str, dict[str, str]]:
    """Descarga gql.py de twikit y extrae los queryId actuales."""
    hdrs = headers or {"User-Agent": "xactions-py/1.5", "Accept": "text/plain"}
    resp = await http.get(TWIKIT_GQL_URL, headers=hdrs, follow_redirects=True)
    resp.raise_for_status()
    return extract_operations_from_twikit(resp.text)


async def refresh_endpoints(
    base: dict[str, dict[str, Any]],
    http: httpx.AsyncClient | None = None,
    cache_path: Path | str | None = None,
    persist: bool = True,
    headers: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """
    Descubre queryIds nuevos y devuelve los endpoints mezclados.
    Orden: bundle de x.com → fallback twikit. Si nada funciona, devuelve `base`.
    """
    owns_client = http is None
    if owns_client:
        http = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
    try:
        source = "bundle"
        discovered: dict[str, dict[str, str]] = {}
        try:
            discovered = await discover_from_bundles(http, headers=headers)
        except (httpx.HTTPError, OSError, ValueError) as e:
            _log.warning("Bundle x.com no disponible: %s", e)

        if len(discovered) < 3:
            try:
                remote = await discover_from_twikit(http)
                if len(remote) > len(discovered):
                    _log.info("Fallback twikit: %d operaciones", len(remote))
                    discovered = remote
                    source = "twikit"
            except (httpx.HTTPError, OSError, ValueError) as e:
                _log.warning("Fallback twikit no disponible: %s", e)

        if not discovered:
            _log.warning("Refresh GraphQL: no se extrajeron queryIds (bundle ni twikit)")
            return {k: dict(v) for k, v in base.items()}

        merged = merge_endpoints(base, discovered)
        if persist:
            try:
                save_cache(merged, path=cache_path, source=source)
            except OSError as e:
                _log.warning("No se pudo guardar cache GraphQL: %s", e)
        return merged
    finally:
        if owns_client:
            await http.aclose()


def endpoints_with_cache(
    base: dict[str, dict[str, Any]],
    cache_path: Path | str | None = None,
) -> dict[str, dict[str, Any]]:
    """Devuelve base mezclada con el cache en disco (si existe)."""
    cached = load_cache(cache_path)
    if not cached:
        return {k: dict(v) for k, v in base.items()}
    return merge_endpoints(base, cached.get("endpoints") or {})


def cache_status(cache_path: Path | str | None = None) -> dict[str, Any]:
    """Resumen del cache para CLI `gql-status`."""
    p = Path(cache_path) if cache_path else DEFAULT_CACHE_PATH
    cached = load_cache(p)
    if not cached:
        return {"path": str(p), "exists": False, "updated_at": None, "count": 0}
    eps = cached.get("endpoints") or {}
    return {
        "path": str(p),
        "exists": True,
        "updated_at": cached.get("updated_at"),
        "source": cached.get("source"),
        "count": len(eps),
    }
