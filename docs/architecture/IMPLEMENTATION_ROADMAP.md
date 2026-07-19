# Implementation Roadmap - Stock & Crypto Scanner Platform

**Date:** July 13, 2026

---

## Where We Are

Milestone 1 was scoped as the audit and the TradingView check of the indicators. That part is done and delivered.

We held back the code changes for one reason. Three of the findings needed your call before we could fix them, because two of them changed what "correct" actually means. Guessing and then reversing it later would have cost more time than asking.

You have now answered all three, so the fixing starts now. Below is what we are doing, in order.

---

## Urgent - Please Read This First

Three things we noticed while getting set up. The first one needs your attention today.

**1. Your code is public on GitHub, and a live API key is exposed in it.**

The repository `Private-Stock-Crypto-Screening-System` is set to Public. That means anyone on the internet can find it, read it and download your entire platform, front end and back end.

It is worse than just the code being visible. One of the files in the repository has an API key written directly inside it, and it is the same key your live site is using. Anyone who has found that repository can use your API key on your account.

What we recommend, in this order:

1. Change the repository from Public to Private. This takes about thirty seconds in the repository settings.
2. Cancel that API key and generate a new one. Even after the repository is made private, the old key has to be treated as compromised, because there is no way to know who has already copied it.
3. Let us clean the key out of the code properly, so it is loaded from your server settings instead of being written into a file.

We would suggest doing steps 1 and 2 yourself as soon as you read this, rather than waiting for us.

**2. Your backend on Railway is currently switched off.** Railway is showing the service as offline, which means the live site cannot fetch any data at the moment. We can look into this once we have access, but we wanted you to know in case it was not intentional.

**3. Your front end is on Netlify and we do not have access to it.** See Section 4.

---

## 1. Your Three Decisions

| Your decision | What we will do |
|---|---|
| **WaveTrend: default 35, not 60.** Users can still change it, but the default and reset value is 35. | We will make the threshold an editable setting and set the default to 35. "Reset to default" will bring it back to 35. |
| **Aroon turn signal: add the extreme-level check.** A turn only counts if it comes from the required extreme level, not from small fluctuations. | We will add the extreme-level check so ordinary small movements in the middle of the range no longer produce a turn signal. |
| **Confirmation timing: the newest fully closed candle counts right away.** No waiting for an extra candle. A live, unfinished candle is never a confirmed signal. | We will change the confirmation rule so the newest closed candle counts immediately, and make sure the unfinished candle is never used anywhere in the platform. |

One note on the Aroon change. There is a separate bug in the audit where the Aroon values are calculated over the wrong number of candles, which means the indicator can never actually reach its true extremes. We have to fix that first, otherwise the extreme-level check you asked for would be measuring against wrong numbers. Both are in the first phase, so this does not slow anything down.

---

## 2. Fixing What the Audit Found

Everything in the audit report gets fixed. We are doing it in this order, starting with what can put a wrong result on your screen, since accuracy is the priority.

### Indicator calculations

- **WaveTrend** - the signal line is smoothed the wrong way, which makes every crossover appear on the wrong candle. We will correct it, and apply your new 35 default.
- **Aroon** - wrong candle count in the calculation, plus your new extreme-level check.
- **Regression Channel (DW)** - the support and resistance lines are on the wrong sides, the channel width is calculated differently from the original, and the "Interval" setting does not do what the original does. We will correct all three against the source you sent us.
- **Trend Channel (ChartPrime)** - this one is not really a version of the original indicator, it is a different method that happens to share the name. We will rebuild it to match the source you sent. This is the largest single item in this phase.
- **Confluence timing** - some of the internal paths skip the candle window check, so a signal can be up to around 6 candles old and still be shown as fresh. We will enforce the window everywhere.
- **Candlestick patterns** - Doji and Inverted Hammer are named in your brief but are not in the platform. We will add them, and tighten up the definitions of a few of the existing patterns.

### Bugs and reliability

- One symbol with bad data can currently stop the entire scan instead of just being skipped. We will isolate it so a single bad symbol never takes down the run.
- A scan session can be used twice on a double click or retry. We will lock it to single use.
- The admin controls can be left open if a setting is missed at deployment. We will make them secure by default.
- Under load the database can lock up and slow down requests. We will fix the locking and the blocking calls behind it.
- When a data fetch fails it is silently ignored, so you get fewer results with no way to know why. We will log these and surface them.

### Filters

- The stock "category" filter is actually filtering on the exchange, not a real category. This is connected to the sector data question in Section 4.
- The API currently accepts a few indicator names it cannot actually run, and returns an empty result instead of an error. We will make it fail clearly.
- When the backend is unreachable, the site shows sample data that looks like real results, with only a small badge to indicate it. On a tool you make decisions with, that is risky. We will make it obvious, or remove it.

### Speed

A full scan of all 5,076 stocks currently takes around 39.5 seconds. We know the causes: the symbols are fetched in batches that wait for each other instead of running together, a concurrency limit is capped far below what is configured, and a few other bottlenecks. We will fix these and report the before and after timing so you can see the difference.

---

## 3. New Features

These are the new items from your brief. We will build them all.

**Avoid Dead Assets filter.** Normal optional filter, on or off, exactly as you described. The four dead trend types, with the defaults from your document. It will never permanently blacklist an asset, so a recovery immediately puts it back in play.

**Trendy ADX (DI+, DI-, ADX).** Built to the Bonavest document, with the four modes (Bullish, Bearish, Compression, Weak), your default values, reset to the original defaults, and the result labels from the spec.

**Variable Linear Regression (VLR).** Built to your document, with the reversal zones, the optional crossing confirmation, and the optional volume and candlestick confirmations.

**Watchlists.** Add stock, add crypto, save, edit, remove, and stay saved between sessions.

**Filters section.** All filters moved into the one Filters section on the left, running in the order you asked for: Price, then Sharia Compliance, then Asset Category, then Sector, then Dead Assets, then the rest.

**Sector filter and Asset Category filter.** Both built as described. See Section 4 for one thing we need to sort out on the data first.

**Owner Dashboard.** Indicator controls (enable, disable, edit parameters, thresholds, lookback, sensitivity, with nothing deletable), scanner controls, and the API controls from your brief (enable, disable, pause, replace, replace key, backup API, status, errors, usage, response times). The goal is that routine changes never need a developer.

All three new indicators will follow the layout you set out in the VLR document: enable and disable, full customisation, one click reset to the original defaults, and clearly presented as a scanner filter and not a buy or sell signal.

---

## 4. What We Need From You

**1. The Zoya API.** You mentioned you will be sending it. Right now the Compliance Standards buttons (AAOIFI, Dow Jones Islamic, MSCI, S&P, FTSE) are on the screen but they do not do anything, because the compliance data currently available only gives a single overall status and not the individual standards. Once we receive the Zoya API we will implement that filter properly. If it turns out the API does not carry the individual standards either, we will come back to you and confirm whether you want the buttons removed rather than left there doing nothing.

**2. Sector and index data.** For the Sector filter, and for the S&P 500, Dow Jones, Russell and ETF options under Asset Category, we need data that says which sector and which index each stock belongs to. The stock list we have today does not contain that. We will check whether the Zoya API or the Massive API provides it, and come back to you with the answer. The exchange based options (NASDAQ, NYSE, AMEX) are not affected and will work either way.

**3. GitHub access.** Could you add us to the repository as collaborators, or confirm that the code you sent us is the latest version? We want to be sure we are fixing the same code that is actually running on your live site, and that our work comes back to you properly through GitHub instead of as a zip file. This also lets us fix the exposed key issue for you.

**4. Netlify access.** Your front end is deployed on Netlify. Please add us to that account, or send us the login. Without it we can fix the front end code but we cannot actually put the fixes live for you, or check that a change works on the real site rather than only on our machines.

**5. Railway access.** Same for the back end. This also lets us find out why the service is currently offline, and it is where the API keys will need to be stored once we take them out of the code.

None of these block the rest of the work. We will keep moving on everything else while they are sorted.

---

## 5. Matching TradingView

This runs alongside the development, not after it. Every fix gets checked as it lands, so we always know whether a change actually improved the result.

For each indicator we compare our values against TradingView on the same asset, the same timeframe and the same settings, and check that the numbers line up. This is important for the kind of bug we found in WaveTrend, where the formula produces a signal one candle away from where it should be. That sort of error is invisible if you only check whether the same stock shows up in both lists, so we check the actual values, candle by candle.

Alongside that, we run a larger automated comparison across all the indicator categories over a longer period, so we also catch anything that only shows up on live data at scale.

At the end you get a testing report showing, indicator by indicator, how closely we match and anything that still differs.

---

## 6. Order of Work

1. **Your three decisions, plus the indicator calculation fixes.** These come first because everything else depends on the numbers being right.
2. **The bugs, the filter fixes and the speed work.**
3. **The new features:** Dead Assets, Trendy ADX, VLR, Watchlists, the Filters section, the Sector and Category filters, and the Owner Dashboard.
4. **TradingView checking throughout**, with the testing report at the end.

The Compliance Standards filter is scheduled for whenever the Zoya API reaches us.
