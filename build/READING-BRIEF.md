# Reading trade details off TradingView screenshots

You are reading a batch of TradingView chart screenshots (crypto, mostly 1-minute charts) and
recording, for each one, the facts needed to rebuild the chart from exchange data. Accuracy
matters more than speed: every value you report is later cross-checked against real candles,
and a wrong value that looks confident costs more than an honest `null`.

## The images

For trade number N of a set (`momo` or `mr`), read:

    C:\Users\Camry\zct-setup-quiz\build\<set>\read\NNN.png

That image has two parts, separated by a magenta line:

- **Top strip**: an enlarged copy of the screenshot's top-left corner. It shows the publish
  line ("<user> published on TradingView.com, Aug 19, 2024 10:00 UTC+1") and the symbol line
  ("PORTAL / TetherUS PERPETUAL CONTRACT, 1, BINANCE").
- **Below**: the whole screenshot.

If something you need is too small to read there, open the original at
`C:\Users\Camry\zct-setup-quiz\build\<set>\shots\NNN.png`. Do not open any other files.

## What to record for each trade

Write one JSON object per trade with exactly these keys:

| key | meaning |
| --- | --- |
| `n` | trade number (from the file name) |
| `pair_text` | the symbol line's pair text exactly as printed, e.g. `"PORTAL / TetherUS PERPETUAL CONTRACT"` |
| `symbol` | the exchange ticker you infer, e.g. `"PORTALUSDT"`, `"1000PEPEUSDT"` |
| `exchange` | as printed, e.g. `"BINANCE"`, `"BYBIT"` |
| `timeframe` | as printed, e.g. `"1"`, `"5"`, `"15"` |
| `published` | publish time from the publish line as `"YYYY-MM-DD HH:MM"` |
| `utc_offset` | the publish line's offset in hours as a number: `UTC` -> 0, `UTC+1` -> 1, `UTC-5` -> -5, `UTC+5:30` -> 5.5 |
| `side` | `"long"` or `"short"` |
| `position_tool` | `true` if a TradingView long/short position box (a red zone and a green zone meeting at the entry) is drawn |
| `entry_price`, `stop_price`, `target_price` | numbers, or `null` |
| `entry_time` | `"YYYY-MM-DD HH:MM"` in the chart's own time axis: where the trade was entered |
| `exit_time` | `"YYYY-MM-DD HH:MM"` where the position box ends, or `null` |
| `outcome_seen` | `"target"`, `"stop"`, `"between"` (closed or still open between them) or `"unclear"`: what the candles after the entry do in the screenshot |
| `last_candle_time` | `"YYYY-MM-DD HH:MM"` of the right-most candle |
| `path` | 6 to 12 `[time, price]` pairs sampled left to right across the chart, see below |
| `confidence` | `"high"`, `"medium"` or `"low"` for the entry time and prices together |
| `note` | anything unusual, in a sentence; `""` if nothing |

### How to read each thing

- **Side and prices.** With a position box: the green zone is profit, the red zone is loss.
  Green above the entry = long; red above the entry = short. The entry is where the two zones
  meet. The box's three prices usually appear as coloured labels on the right-hand price
  scale (target, entry, stop). Other labels on that scale (last price, moving averages,
  horizontal lines) are not the trade: match labels to the box's top edge, meeting line and
  bottom edge by height. If there is no box, use arrows and text notes on the chart
  ("ENTRY", "SL", "TP", "entered here") and say so in `note`; report `null` for any price
  you cannot pin down.
- **Entry time.** The left edge of the position box (or the marked entry candle). Read it
  against the time labels on the bottom axis by measuring between the two nearest labels.
  Aim for the nearest minute or two on a 1-minute chart.
- **Dates.** The bottom axis shows clock times; a bare day number (e.g. `20`) or a month name
  marks midnight. Work out each date from the publish date and those markers. The right-most
  candle is normally at or shortly before the publish time. If the chart was clearly scrolled
  back and you cannot tell the date, use the publish date and say so in `note`.
- **Time zone.** Report times exactly as the chart's axis shows them. Do not convert.
- **`path`.** Pick 6 to 12 labelled times spread across the whole width of the bottom axis.
  For each, report the price the candles are at (roughly the close) directly above that
  label, read from the right-hand price scale. Include the lowest and highest areas of the
  chart if you can. These samples are used to check the time axis against real data, so
  spread them out and read them carefully; three decimals of precision relative to the
  chart's price range is plenty.

### Worked example

`momo\read\005.png` shows "published on TradingView.com, Aug 19, 2024 10:00 UTC+1" and
"PORTAL / TetherUS PERPETUAL CONTRACT, 1, BINANCE". A narrow position box sits just after
the 08:00 label: green from 0.2908 up to 0.2962, red from 0.2908 down to 0.2854, so a long.
Price drops into the red zone straight after. That is recorded as:

```json
{"n": 5, "pair_text": "PORTAL / TetherUS PERPETUAL CONTRACT", "symbol": "PORTALUSDT",
 "exchange": "BINANCE", "timeframe": "1", "published": "2024-08-19 10:00", "utc_offset": 1,
 "side": "long", "position_tool": true, "entry_price": 0.2908, "stop_price": 0.2854,
 "target_price": 0.2962, "entry_time": "2024-08-19 08:05", "exit_time": "2024-08-19 08:07",
 "outcome_seen": "stop", "last_candle_time": "2024-08-19 09:25",
 "path": [["2024-08-19 04:00", 0.2712], ["2024-08-19 05:00", 0.2730], ["2024-08-19 06:00", 0.2772],
          ["2024-08-19 07:00", 0.2815], ["2024-08-19 07:30", 0.2842], ["2024-08-19 08:00", 0.2893],
          ["2024-08-19 08:30", 0.2845], ["2024-08-19 09:00", 0.2832]],
 "confidence": "high", "note": ""}
```

## Output

Write a JSON array of your trades, in order, to the output file you were given, using the
Write tool. Then reply with two or three lines only: how many trades you recorded, and the
numbers of any you marked `low` confidence or left with `null` prices, with the reason.
