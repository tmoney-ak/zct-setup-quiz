# ZCT Setup Quality Quiz

A quiz on the top 3 variables of a momentum or mean-reversion setup, built from the two
"100 High Quality ... Trade Screenshots" docs.

The student picks an exercise (Momentum or Mean reversion). Each chart is rebuilt from real
1-minute candles and stops at the moment the trade was entered. The student grades the three
variables (✅ / ⚠️ / ❌), the page marks each one against the coach's grading from the doc,
shows the coach's note and marked-up screenshot, and plays the trade out.

## Using it

Open `index.html` in a browser (double-click works; no server needed).

- **Students**: choose the exercise, enter a name, pick 10 / 25 / 50 / all charts, press Start.
  Keys: `1` `2` `3` answer the next question (✅ ⚠️ ❌), `Enter` locks in and moves on.
  Answers are saved in the browser; the summary exports CSV or JSON for the coach.
- **Coach review**: `index.html?review=momo` or `?review=mr` (links in the footer) shows every
  trade's original screenshot beside the rebuilt chart, with any notes from the matching step.

## What the page shows

- 8 hours of 1-minute candles before the entry, USD volume with a 60-candle average, and the
  30 and 120 SMMA. Times are in the screenshot's own timezone so they match the coach's notes.
- The last candle before the answer is the entry candle as it stood at the fill: from its open
  to the entry price, nothing after.
- Scoring follows the Top 3 Variables DPS template: ✅ = 2, ⚠️ = 1, ❌ = 0, total 0-6.
  6 Max Confidence and 4-5 High Confidence = Standard Risk (1%), 3 Low Confidence = Dummy
  Trade (0.1%), 0-2 Avoid = Stay Away.

## Where the data comes from

`build/` holds the pipeline. Run from the project folder with Python 3 (`pip install pymupdf pillow`):

| step | command | what it does |
| --- | --- | --- |
| 1 | `python build/extract.py <pdf> build/momo momo` (and `mr`) | answer key (`key.json`) and screenshots out of the PDF |
| 2 | `python build/crops.py build/momo` | enlarged copies used for reading the screenshots |
| 3 | reading (see `build/READING-BRIEF.md`) | coin, exchange, time, side, entry / stop / target of each screenshot into `build/<set>/meta/*.json` |
| 4 | `python build/match.py momo` (and `mr`) | matches each trade to exchange candles and writes `data/` |
| 5 | `python build/pack.py` | web-sized screenshots into `shots/` |

Step 4 checks every trade against real candles: the prices sampled across the screenshot
must sit inside the candles at those times. Screenshots scrolled back to an earlier day show
no date, so it searches the three months before the publish date for the day that fits.
What it is unsure about is listed per trade in `build/<set>/aligned.json` and in the coach
review page.

### Held-back trades

A trade is kept out of the quiz when the match is doubtful (entry candle more than 4 minutes
from the time read, result differs from the screenshot, stop or target unreadable). After
checking one in the coach review page, record the verdict in `build/decisions.json` and
re-run step 4:

```json
{"mr": {"release": [23, 51], "hold": []}, "momo": {"release": [], "hold": [40]}}
```

## Settings worth knowing

- `index.html`: the questions, hints and guide text are in `EX` near the top of the script.
- `build/match.py`: `LOOKBACK` (candles before the entry), the volume-average length
  (`sma(vols, 60)`) and the two SMMA lengths.
