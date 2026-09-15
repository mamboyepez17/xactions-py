# xactions-py — Implementation Plan v1.7.0

> **Branch:** `feature/v1.7.0`  
> **Base:** v1.6.0 (`ef13d31`)  
> **Mode:** Autonomous — each block advances only when its tests pass.

Innovation without TrendScope / without cloning the JS platform.

| Block | Name | Goal |
|-------|------|------|
| B0 | Report | `xactions report` → Markdown (and HTML) from a profile or search |
| B1 | Pipeline | Declarative JSON pipeline: search → filter → actions |
| B2 | Notify | On watch/pipeline new tweets: print + optional webhook POST |
| B3 | MCP groups | Filter advertised MCP tools via env/flag |

## Gate
`pytest` green + `ruff` clean + commit on `feature/v1.7.0`.
