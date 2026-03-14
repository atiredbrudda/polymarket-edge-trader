# Requirements: Polymarket Smart Money Tracker

**Defined:** 2026-02-21
**Core Value:** Surface where smart money is moving in niche prediction markets so the user can see what informed traders are doing and factor that into their own thinking.

## v1.2 Requirements

Requirements for milestone v1.2: Market Resolution & Deep Classification. Fixes the two critical gaps blocking end-to-end scoring: missing market outcomes and shallow token classification.

### GAMMA — Gamma Events Ingestion

- [ ] **GAMMA-01**: User can download and persist eSports events from Gamma API in one command (~8,500 events, ~30s)
- [ ] **GAMMA-02**: Stored events include market clobTokenIds, outcome prices, and hierarchical tags (game/tournament/team slugs)

### RESOL — Market Outcome Resolution

- [ ] **RESOL-01**: User can populate `markets.outcome` for all resolved markets using stored Gamma event data
- [ ] **RESOL-02**: Resolved outcomes correctly encode winning side (YES/NO or token ID) per market

### CLASS — Deep Classification

- [ ] **CLASS-01**: Token catalog entries receive `node_path` at game/tournament/team depth from Gamma event tags
- [ ] **CLASS-02**: Token catalog `depth` field reflects actual classification level (1=game, 2=tournament, 3=team)

### E2E — End-to-End Pipeline

- [ ] **E2E-01**: `score` command produces non-empty expertise scores on JBecker data after Gamma ingestion
- [ ] **E2E-02**: Leaderboard shows correctly scored traders with win rates calculated from resolved outcomes

### GAP — eSports Token Gap Recovery

- [ ] **GAP-01**: All 156 null-token eSports markets have `markets.tokens` populated via Gamma Events API tag-based scan, enabling Tier 1 patcher to classify them
- [ ] **GAP-02**: `ingest.py` populate-tokens block uses events endpoint (not broken `?conditionId=` param) to prevent recurrence of null-token gap
- [ ] **GAP-03**: After recovery, all 3,633 affected trades are classifiable and trader eSports scores reflect the newly attributed activity

## Future Requirements

None identified for v1.2 beyond Phase 20.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Live/real-time outcome polling | Batch one-time load sufficient; no sub-hour latency needed |
| Non-eSports category resolution | eSports first — generalize once pattern proven |
| Incremental Gamma updates | Full re-download on demand is adequate for current scale |
| Web dashboard | Premature until signal quality is proven end-to-end |
| Auto-trading / bot execution | Awareness tool, not a trading bot |
| Discord webhook alerting | Telegram sufficient; Discord deferred (ALRT-02) |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| GAMMA-01 | Phase 15 | Pending |
| GAMMA-02 | Phase 15 | Pending |
| RESOL-01 | Phase 16 | Pending |
| RESOL-02 | Phase 16 | Pending |
| CLASS-01 | Phase 17 | Pending |
| CLASS-02 | Phase 17 | Pending |
| E2E-01 | Phase 18 | Pending |
| E2E-02 | Phase 18 | Pending |
| GAP-01 | Phase 20 | Pending |
| GAP-02 | Phase 20 | Pending |
| GAP-03 | Phase 20 | Pending |

**Coverage:**
- v1.2 requirements: 8 total
- Mapped to phases: 8
- Unmapped: 0 ✓

---
*Requirements defined: 2026-02-21*
*Last updated: 2026-02-21 — traceability filled after roadmap creation*
