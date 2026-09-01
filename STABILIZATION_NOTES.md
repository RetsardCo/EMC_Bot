# Daily Knowledge stabilization

Replace:
- `cogs/ai.py`
- `cogs/community.py`

Add to `.env`:

```env
PUTER_AUTH_TOKEN=YOUR_PUTER_AUTH_TOKEN
PUTER_BASE_URL=https://api.puter.com/puterai/openai/v1/
PUTER_MODEL=gpt-5.4-nano
PUTER_DAILY_MODEL=gpt-5.4-nano

OPENROUTER_DAILY_MODEL=openrouter/free

AI_RATE_LIMIT_COOLDOWN_SECONDS=60
AI_CONFIG_ERROR_COOLDOWN_SECONDS=3600
AI_TRANSIENT_ERROR_COOLDOWN_SECONDS=60

DAILY_WEBSITE_SOURCE_WEIGHT=10
DAILY_MAX_DYNAMIC_ATTEMPTS=3
DAILY_AI_DUPLICATE_CHECK_ENABLED=false
```

## Behavior

Daily source selection remains weighted-random:
- successful configured websites are in the pool
- enabled reference-book JSON files are in the same pool
- if websites fail, books automatically remain as the available sources
- there is NO Wikipedia fallback

AI fallback:
- Gemini
- Puter
- OpenRouter Daily model (`openrouter/free`)
- Mistral

Provider cooldowns prevent repeated calls after rate-limit, bad-model, or
temporary-network failures.

OpenRouter requests no longer force `reasoning.enabled=false`, allowing the
free router to select reasoning-capable models.

Puter response parsing now validates JSON types before using `.get()`, so a
malformed/unexpected response produces a useful error instead of
`'str' object has no attribute 'get'`.

The existing local duplicate check remains. AI duplicate checking is disabled
by default to reduce API usage.

Never commit the real Puter token.
