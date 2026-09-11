# xactions-py — Implementation Plan v1.6.0

> **Branch:** `feature/v1.6.0`  
> **Base:** v1.5.0 (`71b3d34`)  
> **Mode:** Autonomous — each block advances when its tests pass (no per-block approval).

Inspired by gaps vs [XActions (JS)](https://github.com/nirholas/XActions), without cloning their platform scope. Focus: safety, DX, reliability in pure Python.

| Block | Name | Goal |
|-------|------|------|
| B0 | Doctor + daily caps | Health check CLI; on-disk write budget |
| B1 | Browser cookies | `--from-browser` import from Chrome/Firefox profiles |
| B2 | Write drafts + approval | MCP/CLI writes held as drafts until approved |
| B3 | Transaction ID | Stronger `x-client-transaction-id` (best-effort) |
| B4 | Watch + scrape checkpoints | Delta monitor; cursor resume for long scrapes |
| B5 | Media download + unfollower snapshot | Download media URLs; follower diff |

## Acceptance for auto-advance
Each block: `pytest` green + `ruff` clean + commit on `feature/v1.6.0`.
