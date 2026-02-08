# Phase 6: Alerting System - Context

**Gathered:** 2026-02-08
**Status:** Ready for planning

<domain>
## Phase Boundary

Deliver consensus signals from Phase 5 via Telegram (primary) with retry reliability. Transform detected expert consensus into actionable push notifications containing market context, expert details, and signal metadata. Discord support deferred to future work.

</domain>

<decisions>
## Implementation Decisions

### Alert Content

- **Extended detail level**: Include first-mover identity, fast-follower count, expert addresses, and individual position sizes (not just core market info)
- **Explicit signal type differentiation**: Prefix or header indicates NEW consensus, STRENGTHENING (confidence up ≥5 points), WEAKENING (confidence down ≥5 points), or LOST consensus
- **Complete signal metadata**: All data needed for user decision-making without needing to query CLI

### Telegram Formatting

- **Rich HTML formatting**: Use Telegram HTML parse mode for bold/italic headers, monospace data, structured layout
- **Structured presentation**: Headers, bullet lists, inline links for market URLs
- **Human-readable**: Scannable at a glance, not just data dump

### Alert Triggering

- **All signal events**: Alert on NEW, STRENGTHENING (≥5 point confidence increase), WEAKENING (≥5 point confidence decrease), LOST consensus
- **No confidence filtering**: Send all consensus signals regardless of confidence score (user sees full range)
- **Signal type detection**: Compare latest SignalSnapshot to previous to determine event type

### Configuration

- **Environment variables for credentials**: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env file
- **Single destination only**: One Telegram chat for v1 (no multi-destination routing)
- **Strict validation at startup**: Fail fast with clear error messages if required env vars missing or invalid

### Error Handling

- **Log and continue on permanent failure**: Record failed deliveries in logs but don't block alert pipeline
- **No user notification on failures**: Operator checks logs if alerts stop arriving

### Claude's Discretion

- **Retry logic strategy**: Exponential backoff, fixed interval, or fail-fast approach based on best practices
- **Delivery status tracking**: Whether to persist delivery state (sent/pending/failed) in database or keep stateless
- **Rate limit handling**: Client-side rate limiter, respect server headers, or both
- **Deduplication strategy**: Snapshot comparison, time-based, hash-based, or hybrid approach
- **Alert batching**: Immediate delivery vs batching by time/count to reduce notification spam
- **Behavior configurability**: Hard-coded defaults vs config file vs env vars for thresholds and filters

</decisions>

<specifics>
## Specific Ideas

- "Extended details" means showing WHO the first mover was and WHO the fast followers are (addresses), not just counts
- Confidence change threshold of ±5 points defines STRENGTHENING/WEAKENING (below that is noise)
- HTML formatting should make alerts feel native to Telegram, not like a bot's plaintext dump

</specifics>

<deferred>
## Deferred Ideas

- **Discord integration**: User will implement Telegram first, add Discord when satisfied with Telegram alerts
- **Multi-destination support**: Single chat for v1, can extend later if needed
- **Generic webhook output** (ALRT-05): Future v2 requirement
- **Whale alerts** (ALRT-06): Future v2 requirement
- **Per-game routing**: Different channels per eSports category — out of scope for v1

</deferred>

---

*Phase: 06-alerting-system*
*Context gathered: 2026-02-08*
