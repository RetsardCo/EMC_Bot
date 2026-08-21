# EM Bot Dual AI Fallback

This package contains the updated AI module only.

Primary provider:
- Gemini REST API
- Model: `gemini-3.6-flash`

Fallback provider:
- OpenRouter REST API
- Default model: `nvidia/nemotron-3-ultra-550b-a55b:free`

Behavior:
- Try Gemini first.
- If Gemini fails for any reason, try OpenRouter.
- Keep the same BSEMC source-channel context and strict numbered style.
- Keep only short conversation history in RAM.
- No database.
- No additional AI SDK is required.

## Environment

Add:

`OPENROUTER_API_KEY=...`

Keep:

`GEMINI_API_KEY=...`

Do not upload `.env` to GitHub.

## Test

Restart EM Bot after replacing `cogs/ai.py`:

```powershell
python bot.py
```

Then test:

`/ask What is the BSEMC Game Jam?`

The bot should use the official Discord source messages, then answer with Gemini. If Gemini is unavailable, it automatically attempts OpenRouter.

## Notes

The OpenRouter free endpoint has its own rate limits/availability. It is a fallback, not a guarantee of unlimited AI access.
