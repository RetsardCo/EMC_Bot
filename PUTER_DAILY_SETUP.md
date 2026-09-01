# Puter + resilient Daily Knowledge

## Files to replace

```text
cogs/ai.py
cogs/community.py
```

No new Python package is required.

## Add to `.env`

```env
PUTER_AUTH_TOKEN=YOUR_PUTER_AUTH_TOKEN
PUTER_BASE_URL=https://api.puter.com/puterai/openai/v1/
PUTER_MODEL=gpt-5.4-nano
PUTER_DAILY_MODEL=gpt-5.4-nano
DAILY_WEBSITE_SOURCE_WEIGHT=10
```

Never commit the real token.

Puter documents an OpenAI-compatible endpoint and server-side authentication
with a Puter auth token.

## Daily source selection

The Daily Knowledge source pool contains:

1. successfully retrieved online sources for the selected topic
2. enabled local reference-book JSON files

Website sources use `DAILY_WEBSITE_SOURCE_WEIGHT`.
Reference-book weights are controlled through the Knowledge Manager GUI.

When both are available, the source is chosen by weighted randomization.
Therefore the daily post is not always online and not always from a book.

If all online sources fail, the enabled offline reference books remain available.
If neither is available, the existing Wikipedia fallback can be used.

## AI provider fallback

Daily Knowledge AI generation/verification uses:

```text
Gemini
  -> Puter
  -> OpenRouter Fast
  -> Mistral
```

The normal General and Fast routes also gain Puter as a fallback.

The daily system still refuses to publish an item that cannot pass its source-backed
verification step.

## Testing

1. Restart EM Bot.
2. Run `/ai_status` and confirm **Puter** appears.
3. Run `/daily_chat_now`.
4. Confirm the output is factual knowledge, not a question.
5. Confirm the source is shown.
6. To test offline source fallback, temporarily make the configured website sources
   unusable while keeping an enabled reference book. The daily engine should
   continue with the book.

## Security

A Puter auth token is tied to your Puter account. Treat it like a password and
store it only in `.env` or your host's secrets manager.
