# Stock Intraday Session Policy — Before, Change, and Now

Date: 2026-07-21

Repository: `stock-crypto-screening-tokaplace-api`

---

## What was before

### Provider behavior

The backend fetched Massive/Polygon native intraday aggregates with:

- `adjusted=true`
- No session selector
- No post-fetch filtering

Massive returns **UTC-aligned clock-hour bars** that can include:

- Pre-market (before 09:30 ET)
- Regular session (09:30–16:00 ET)
- After-hours (from 16:00 ET through extended close)

### Backend behavior

Pipeline path:

```
Massive /v2/aggs/.../range/1/hour/...
  → normalize_polygon_rows (t ms → time sec)
  → slice_recent
  → SQLite cache (full replace)
  → indicators (Trend Channel, etc.)
```

There was **no stock session policy**. Every Massive bar was kept.

### Confirmed mismatch (ZBIO, 2026-07-20)

| UTC bar | New York | Session | Massive | TradingView 1h |
|---:|---|---|---|---|
| 19:00 | 15:00 EDT | Regular | Included | Last visible bar |
| 20:00 | 16:00 EDT | After-hours | Included | Not shown |
| 22:00 | 18:00 EDT | After-hours | Included | Not shown |

The backend used **22:00 UTC** as the latest ZBIO 1h candle. TradingView stopped at **19:00 UTC**.

The backend did **not** invent or alter the 22:00 bar. It came directly from Massive.

### Impact

Different candle sequences produced different:

- Pivot points
- Trend Channel geometry
- Touch / breach signals

Indicators were mathematically correct for the candles they received — but the candles did not match TradingView regular-session validation.

---

## What changed

### New module: `services/stock_session.py`

Introduces explicit session policies:

| Policy | Meaning |
|---|---|
| `tradingview_regular` | Keep US stock intraday bars whose **ET open** is `09:30 <= t < 16:00` on weekdays |
| `provider_default` | Legacy pass-through (no filtering) |

### New setting: `STOCK_INTRADAY_SESSION_POLICY`

In `core/config.py`:

```env
STOCK_INTRADAY_SESSION_POLICY=tradingview_regular
```

Default is **`tradingview_regular`** for TradingView parity during stock intraday screening.

Crypto symbols (`*-USD`) are **never** filtered.

Daily+ timeframes (`1day`, `1week`, etc.) are **never** filtered.

### Pipeline integration (`services/market_data.py`)

1. **After normalization, before `slice_recent`**
   - Apply `apply_stock_session_policy()` for stock intraday symbols.

2. **Over-fetch before filtering**
   - When `tradingview_regular` is active, download ~2.5× requested bars so post-filter history still satisfies indicator lookbacks.

3. **Cache metadata**
   - Payloads now include `session_policy`.
   - Cache rows without a matching policy are treated as stale/incompatible and refreshed.

4. **Snapshot fast path**
   - After-hours snapshot bars are dropped under `tradingview_regular`.

5. **No indicator changes**
   - Trend Channel, LinReg, ADX, etc. are unchanged. They now receive regular-session candles.

### Tests

- `tests/test_stock_session.py` — session filter rules, ZBIO July 20 case, cache compatibility, fetch multiplier
- Updated `tests/test_price_lag_diagnostics.py` where legacy tests assume provider-default plumbing

### Diagnostic script

- `scripts/diag_zbio_1h.py` — compares raw Massive bars vs filtered regular-session output

---

## What is now

### Target product behavior

```json
{
  "session_policy": "tradingview_regular"
}
```

This is enforced via `STOCK_INTRADAY_SESSION_POLICY=tradingview_regular` (default).

### ZBIO July 20 result after fix

From the same Massive raw window (18:00 UTC onward):

**Raw Massive (unchanged provider feed):**

| UTC | Session |
|---:|---|
| 18:00 | Regular |
| 19:00 | Regular |
| 20:00 | After-hours — **removed** |
| 22:00 | After-hours — **removed** |

**Backend after `tradingview_regular` filter:**

- Latest bar: **19:00 UTC** (matches TradingView’s last July 20 regular-session 1h bar)
- After-hours 20:00 / 22:00 bars are excluded before cache and indicators

### Filter rule (exact)

For each candle with Unix open time `time`:

1. Convert to `America/New_York`
2. Reject weekends
3. Keep iff `09:30 <= local_open_time < 16:00`

This matches Massive UTC clock-hour semantics and TradingView’s regular-session cutoff on the ZBIO case.

### Cache behavior

Cached payloads store:

```json
{
  "session_policy": "tradingview_regular",
  "candles": [ /* already filtered */ ],
  "candles_provider": "massive"
}
```

Legacy cache entries (no `session_policy`, or `provider_default`) are **not reused** while `tradingview_regular` is active. The worker/screener refetches and rewrites them.

### Reverting to legacy provider behavior

Set in `.env`:

```env
STOCK_INTRADAY_SESSION_POLICY=provider_default
```

This restores the previous pass-through of all Massive intraday bars.

---

## Files touched

| File | Role |
|---|---|
| `services/stock_session.py` | Session policy logic (new) |
| `services/market_data.py` | Filter integration, cache compatibility, fetch multiplier |
| `core/config.py` | `STOCK_INTRADAY_SESSION_POLICY` setting |
| `tests/test_stock_session.py` | Unit/integration tests (new) |
| `tests/test_price_lag_diagnostics.py` | Legacy test adjustments |
| `scripts/diag_zbio_1h.py` | Live ZBIO diagnostic with filter output |

---

## Known limits (not in scope)

- **Market holidays** — only weekends are excluded today; NYSE holiday calendar not yet applied.
- **Half-days** — early close sessions (e.g. 13:00 ET) not specially handled.
- **Session-aligned 1h bars** — TradingView’s first bar can start at 09:30 ET; Massive uses UTC clock hours. The filter approximates TV regular-session parity on provider bars; it does not re-bucket to 09:30–10:30 style session hours.
- **Extended-hours mode** — not implemented yet; would be a separate future policy (e.g. `tradingview_extended`).

---

## Verification commands

```bash
cd stock-crypto-screening-tokaplace-api
python -m pytest tests/test_stock_session.py -q
python scripts/diag_zbio_1h.py
```

Expected on ZBIO diagnostic: `latest_regular_session_bar: 1784574000` (2026-07-20 19:00 UTC).
