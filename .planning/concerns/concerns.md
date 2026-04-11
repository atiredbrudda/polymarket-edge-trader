# Concerns

## 1. Duplicate Trades

**Question:** Where are the duplicates coming from? Can they be avoided? Or should I just flow with the dedups in place?

---

## 2. Component Timing Breakdown

**Question:** The component timing breakdown displays after backfill completes. Should it be removed entirely or kept for debugging?

---

## 3. Build-Positions Performance

**Question:** Can the runtime of `build-positions` be improved? Something like vectorizing the score command?

**Note:** Consider downsides of changes vs. upsides we might miss (especially regarding results from retry completion command).

---

## 4. Score Changes (Short Calculation)

**Question:** What changes were made to the score command, specifically regarding the short calculation that was wrong?

---

## 5. Localhost Webpage Performance

**Question:** The localhost webpage loads extremely slow. Suspect it's the database. Need investigation.

---

## 6. Discovery — Market 0x8669d8...

**Question:** Game starting 9pm tomorrow (market: `0x8669d8201d25ac2506861a5bd3b98564114ade586320edd1a2f6a0b777436537`) appears in webpage.

Discovery filter is "closing-within 3hrs" — is this market supposed to show up? Logic is fuzzy, need verification.

---

## 7. Discover Cache Rule (30 minutes)

**Question:** There's a cache rule checking "last 30 minutes" attached to the discover command. Is it reasonable to keep, or will it cause missed addresses?

---
