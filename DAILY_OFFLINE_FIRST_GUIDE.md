# Daily Knowledge — offline-first

Replace:

```text
cogs/community.py
```

Add these settings to `.env`:

```env
DAILY_WEBSITE_SOURCE_WEIGHT=10
DAILY_OFFLINE_POOL_WEIGHT=20
DAILY_WEB_POOL_WEIGHT=10
DAILY_MAX_DYNAMIC_ATTEMPTS=2
DAILY_AI_DUPLICATE_CHECK_ENABLED=false
```

## Puter
This release does not change `ai.py`; keep your existing Puter configuration.

## Modes

Use:

```text
/daily_knowledge
```

The buttons are:

- **Offline Only** — default. Uses `knowledge/daily_items.json` and consumes
  no AI generation quota.
- **Mixed** — weighted-random online/offline selection. If online generation
  fails, an offline item takes over.
- **Web for Today** — allows online/AI content for today's scheduled post only.
  It automatically returns to Offline Only on the next Manila date.

## Offline data

Copy:

```text
knowledge/daily_items.example.json
```

to:

```text
knowledge/daily_items.json
```

Then replace the example with your pre-generated factual items and real source
references.

Each item needs:

```text
id
topic
fact
explanation
source
```

The bot remembers used IDs so it does not repeat items until the available
pool has completed a cycle.

## Wikipedia

There is no Wikipedia fallback in this version. The daily online source list is
only what you explicitly configure in `daily_topics.json`.

## API usage

Offline scheduled posts use zero AI generation calls.

The `/daily_chat_now` command follows the selected mode so it is safe for testing.

## Important

Pre-generated items should be checked against their cited source before you
place them in the offline corpus. An AI-generated statement is not itself proof
of the fact.
