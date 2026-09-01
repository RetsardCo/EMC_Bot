# EM Bot AI stabilization

## Replace

```text
cogs/ai.py
cogs/community.py
```

## Add to `.env`

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
DAILY_AI_DUPLICATE_CHECK_ENABLED=false
DAILY_MAX_DYNAMIC_ATTEMPTS=3
```

## What changed

### Provider cooldowns
A provider/model that returns a rate-limit, quota, authentication/model, or
temporary network error is put into a cooldown instead of being hammered again.

### Puter
Added as a provider and Daily Knowledge fallback. Puter is configured through
its documented OpenAI-compatible endpoint.

### OpenRouter
Daily Knowledge now uses `openrouter/free` by default instead of pinning the
daily feature to one fragile free model slug. OpenRouter's free router chooses
among currently available free models.

### Daily Knowledge request reduction
Local duplicate detection remains enabled. AI duplicate checking is disabled by
default so a single daily item does not require an additional AI call before
verification.

Daily generation is capped at 3 attempts by default.

### Source selection
Successful websites and enabled reference books remain in the same weighted
random pool. If online retrieval fails completely, enabled local reference books
are still available. If neither exists, the existing Wikipedia fallback is used.

## Test order

1. Restart EM Bot.
2. Run `/ai_status`.
3. Confirm Puter appears.
4. Run `/daily_chat_now`.
5. Check the console for the provider that succeeded.
6. Confirm the Discord post is factual and includes the source.
7. Test again after disabling online sources to verify the reference-book fallback.

Never commit the real Puter token.
