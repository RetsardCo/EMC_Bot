# Automatic OpenRouter coding-model discovery

EM Bot now queries OpenRouter's public model catalog when the cached automatic
coding model is older than `OPENROUTER_AUTO_REFRESH_SECONDS`.

It filters for:
- $0 prompt pricing
- $0 completion pricing
- text input
- at least 16K context
- coding/programming/developer/agentic signals

It ranks candidates by coding relevance and context length.

The selected model is cached at:

`data/openrouter_model_cache.json`

If discovery fails, EM Bot falls back to the configured
`OPENROUTER_CODING_MODEL`.

This does not blindly select every free model. It only selects a model that
looks appropriate for coding. OpenRouter's free-model availability can still
change, so a fallback remains necessary.

The coding route can therefore survive retirement of a specific free model
without requiring a code update every time OpenRouter changes its catalog.

Never commit `.env` or your API key.
