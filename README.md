# David's Bee Posts

Tribute page for Babylon Bee subscriber David Raphael (@TwoDegreesOff), published at
https://davidsbeepubs.netlify.app/

## How it works

| File | What it is |
|---|---|
| `site/index.html` | The page. It reads its headlines from `headlines.json`. |
| `site/headlines.json` | The list of headlines, comment counts and rankings. |
| `scripts/update.py` | Checks babylonbee.com for new articles credited to David and refreshes comment counts. |
| `.github/workflows/daily-update.yml` | Runs the script every morning and saves any changes. |

Netlify publishes the `site` folder every time this repository changes, so the daily
run updates the live page automatically.

## Adding a headline by hand

Pieces pitched through Slack have no "contributed to this report" line, so the script
can't find them. Add them to `site/headlines.json` (click the file on GitHub, then the
pencil icon) with `"manual": true`:

```json
{
  "headline": "Exact headline as published",
  "date": "2026-09-21",
  "img": "https://media.babylonbee.com/articles/XXXX.jpg",
  "url": "https://babylonbee.com/news/the-slug",
  "note": "Pitched via the Bee's Slack channel, so it carries no subscriber credit line",
  "manual": true
},
```

Optional fields: `flag` puts a gold banner on the card; `note` adds a small italic line.

## If a run fails

GitHub emails you. The usual cause is the Babylon Bee blocking the request or changing
its site. The page keeps showing the last good data, and nothing is deleted.
To retry: **Actions** tab → **Daily update** → **Run workflow**.
