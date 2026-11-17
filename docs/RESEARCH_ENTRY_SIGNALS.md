# Research: entry-signal variants

**Branch:** `research/entry-signals`  
**Base:** `origin/main` only. Does **not** edit frozen `docs/MEASUREMENT.md`.  
**Live:** `SPOT_ENTRIES` / live stays off. Research knobs affect **replay only**.

## Why baseline RSI / lift failed (stop-dominated)

On the unseen gate windows, pooled medians stay ≤ 0. Closed fills cluster near stop loss after 30 bps slip each way + KuCoin taker: the **median** pair loses even when a few sleeves win. RSI+BB reclaim often false-turns; lift volume+upper-close often fails continuation into the tighter 1.5% stop. Zeros appear when a half has no closed trades.

## Env

| `RESEARCH_ENTRY` | Rule |
|---|---|
| *(unset)* | Baseline RSI reclaim + candle lift |
| `breakout` | Close > max high of prior **20** bars; quote volume ≥ 2× median of prior 12 |
| `bb_mr` | Prior close ≤ lower BB(20,2σ); this close > band and > prior close (no RSI / MACD) |
| `breakout_10` | Same as breakout with lookback **10** |
| `confluence` | RSI&lt;35 + BB reclaim + volume ≥ 1.5× median; no MACD sell block |
| `vol_climax_fade` | Prior bar volume ≥ 3× median and close in lower 35% of range; this close > prior |

Both gate halves (`replay_closes` and `replay_lift_bars`) use the selected research entry when set. Exit params stay frozen (RSI path 350/700; lift path 150/250). Gate still runs `--prior-pays`.

```bash
# baseline
python3 scripts/unseen_gate.py --run

# one variant
RESEARCH_ENTRY=breakout python3 scripts/unseen_gate.py --run
```

PASS still needs all eight pooled medians strictly &gt; 0; this script never enables entries.
