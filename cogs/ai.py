import asyncio
import json
import logging
import os
import time
import urllib.error
import urllib.request
from collections import defaultdict, deque
from typing import Deque

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("em-bot.ai")

# --------------------------------------------------
# Primary AI: Gemini
# Fallback AI: OpenRouter
# --------------------------------------------------

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODEL = os.getenv(
    "OPENROUTER_MODEL",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
).strip()

# Optional URLs/headers used by OpenRouter.
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "").strip()
OPENROUTER_SITE_NAME = os.getenv("OPENROUTER_SITE_NAME", "EM Bot").strip()

AI_CHANNEL_ID = int(os.getenv("AI_CHANNEL_ID", "0"))
AI_COOLDOWN_SECONDS = int(os.getenv("AI_COOLDOWN_SECONDS", "10"))
AI_MAX_HISTORY_TURNS = int(os.getenv("AI_MAX_HISTORY_TURNS", "6"))
AI_MAX_OUTPUT_TOKENS = int(os.getenv("AI_MAX_OUTPUT_TOKENS", "1200"))

AI_SOURCE_CHANNEL_IDS = {
    int(value.strip())
    for value in os.getenv("AI_SOURCE_CHANNEL_IDS", "").split(",")
    if value.strip().isdigit()
}

AI_SOURCE_LOOKBACK_MESSAGES = int(
    os.getenv("AI_SOURCE_LOOKBACK_MESSAGES", "50")
)

SYSTEM_PROMPT = """
You are EM Bot, the BSEMC community assistant.

GENERAL ANSWER STYLE:
1. Always answer using numbered points.
2. Use simple language suitable for students.
3. Normally use 3 to 5 numbered points.
4. Keep each point short, normally 1 to 3 sentences.
5. Do not use bullet points.
6. Do not use tables unless the user explicitly asks for a table.
7. Do not repeat the user's question.
8. Do not add unnecessary introductions or conclusions.
9. Give a complete answer, but keep it concise.
10. Never intentionally stop in the middle of a sentence.
11. If you are uncertain about something, say so.

OFFICIAL BSEMC INFORMATION:
1. Information from the configured official Discord source channels is authoritative
   for current BSEMC announcements, events, workshops, schedules, rules, policies,
   activities, and other time-sensitive information.
2. Never invent official BSEMC dates, names, locations, schedules, requirements,
   announcements, or policies.
3. If the supplied official source messages do not contain enough information to
   answer a current BSEMC question, explicitly say verified information is unavailable.
4. Do not present general model knowledge as current official BSEMC information.
5. When using official source information, identify the source channel.
6. If official information is unavailable, tell the user to check the appropriate
   official BSEMC Discord channel.
7. General educational questions may be answered using general knowledge.

SOURCE RULE:
Treat the source messages supplied by EM Bot as evidence.
Do not add facts that are not supported by those sources.
""".strip()

history: dict[int, Deque[tuple[str, str]]] = defaultdict(
    lambda: deque(maxlen=AI_MAX_HISTORY_TURNS * 2)
)
last_request: dict[int, float] = {}


def tokenize(text: str) -> set[str]:
    stop_words = {
        "the", "and", "for", "what", "when", "where", "who", "how",
        "why", "does", "this", "that", "with", "about", "from", "are",
        "is", "was", "were", "can", "could", "would", "should", "will",
        "please", "tell", "me",
    }

    import re
    words = re.findall(r"[a-zA-Z0-9']+", text.casefold())

    return {
        word
        for word in words
        if len(word) >= 3 and word not in stop_words
    }


def split_for_discord(text: str, limit: int = 1900) -> list[str]:
    text = text.strip()
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text

    while len(remaining) > limit:
        split_at = remaining.rfind("\n\n", 0, limit)

        if split_at < 300:
            split_at = remaining.rfind("\n", 0, limit)

        if split_at < 300:
            split_at = remaining.rfind(". ", 0, limit)

        if split_at < 300:
            split_at = remaining.rfind(" ", 0, limit)

        if split_at < 1:
            split_at = limit

        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()

    if remaining:
        chunks.append(remaining)

    return chunks


async def fetch_official_sources(
    guild: discord.Guild,
    question: str,
) -> list[str]:
    if not AI_SOURCE_CHANNEL_IDS:
        return []

    question_words = tokenize(question)
    candidates: list[tuple[float, discord.Message]] = []

    for channel_id in AI_SOURCE_CHANNEL_IDS:
        channel = guild.get_channel(channel_id)

        if not isinstance(channel, discord.TextChannel):
            logger.warning(
                "AI source channel %s was not found or is not a text channel.",
                channel_id,
            )
            continue

        try:
            async for message in channel.history(
                limit=AI_SOURCE_LOOKBACK_MESSAGES,
                oldest_first=False,
            ):
                if message.author.bot and not message.embeds and not message.content:
                    continue

                content = message.content.strip()
                embed_text_parts: list[str] = []

                for embed in message.embeds:
                    if embed.title:
                        embed_text_parts.append(embed.title)
                    if embed.description:
                        embed_text_parts.append(embed.description)
                    for field in embed.fields:
                        if field.name:
                            embed_text_parts.append(field.name)
                        if field.value:
                            embed_text_parts.append(field.value)

                combined_text = "\n".join(
                    part for part in [content, *embed_text_parts] if part
                ).strip()

                if not combined_text:
                    continue

                message_words = tokenize(combined_text)
                keyword_matches = len(question_words & message_words)

                age_hours = max(
                    0,
                    (discord.utils.utcnow() - message.created_at).total_seconds() / 3600,
                )
                recency_bonus = max(0, 10 - (age_hours / 24))
                score = keyword_matches * 10 + recency_bonus
                candidates.append((score, message))

        except discord.Forbidden:
            logger.warning(
                "Cannot read AI source channel %s. Check View Channel and Read Message History.",
                channel_id,
            )
        except discord.HTTPException:
            logger.exception(
                "Discord error while reading AI source channel %s.",
                channel_id,
            )

    candidates.sort(key=lambda item: item[0], reverse=True)
    selected = candidates[:12]

    sources: list[str] = []

    for _, message in selected:
        channel_name = getattr(message.channel, "name", "unknown-channel")
        content = message.content.strip()
        embed_text_parts: list[str] = []

        for embed in message.embeds:
            if embed.title:
                embed_text_parts.append(embed.title)
            if embed.description:
                embed_text_parts.append(embed.description)
            for field in embed.fields:
                if field.name:
                    embed_text_parts.append(field.name)
                if field.value:
                    embed_text_parts.append(field.value)

        combined_text = "\n".join(
            part for part in [content, *embed_text_parts] if part
        ).strip()

        if not combined_text:
            continue

        sources.append(
            "\n".join(
                [
                    f"SOURCE CHANNEL: #{channel_name}",
                    f"SOURCE DATE: {message.created_at.isoformat()}",
                    f"SOURCE MESSAGE: {combined_text}",
                ]
            )
        )

    return sources


def build_contents(
    user_id: int,
    question: str,
    official_sources: list[str],
) -> list[dict]:
    contents: list[dict] = []

    for role, text in history[user_id]:
        contents.append(
            {
                "role": role,
                "parts": [{"text": text}],
            }
        )

    if official_sources:
        source_context = (
            "\n\nOFFICIAL DISCORD SOURCE MATERIAL\n"
            "Use this information for current/official BSEMC questions.\n"
            "Do not add facts that are not supported by these sources.\n\n"
            + "\n\n---\n\n".join(official_sources)
        )
    else:
        source_context = (
            "\n\nOFFICIAL DISCORD SOURCE MATERIAL\n"
            "No verified official source information was found for this request.\n"
            "Do not invent current BSEMC information.\n"
        )

    contents.append(
        {
            "role": "user",
            "parts": [
                {
                    "text": f"{source_context}\n\nUSER QUESTION:\n{question}"
                }
            ],
        }
    )

    return contents


def extract_text_from_gemini(data: dict) -> str:
    candidates = data.get("candidates", [])

    if not candidates:
        prompt_feedback = data.get("promptFeedback", {})
        block_reason = prompt_feedback.get("blockReason")
        if block_reason:
            raise RuntimeError(f"Gemini blocked the request: {block_reason}")
        raise RuntimeError("Gemini returned no candidates.")

    parts = candidates[0].get("content", {}).get("parts", [])
    answer = "".join(
        part.get("text", "")
        for part in parts
        if isinstance(part.get("text", ""), str)
    ).strip()

    if not answer:
        finish_reason = candidates[0].get("finishReason", "unknown")
        raise RuntimeError(
            f"Gemini returned no text. Finish reason: {finish_reason}"
        )

    return answer


def call_gemini_sync(
    api_key: str,
    model: str,
    contents: list[dict],
) -> str:
    url = (
        "https://generativelanguage.googleapis.com/"
        f"v1beta/models/{model}:generateContent"
    )

    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": contents,
        "generationConfig": {
            "maxOutputTokens": AI_MAX_OUTPUT_TOKENS,
            "thinkingConfig": {"thinkingLevel": "minimal"},
        },
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        try:
            details = json.loads(body)
            message = details.get("error", {}).get("message", body)
        except json.JSONDecodeError:
            message = body
        raise RuntimeError(f"Gemini HTTP {error.code}: {message}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Gemini network error: {error}") from error

    return extract_text_from_gemini(data)


def extract_openrouter_content(data: dict) -> str:
    choices = data.get("choices", [])
    if not choices:
        error = data.get("error", {})
        raise RuntimeError(
            f"OpenRouter returned no choices: {error.get('message', 'unknown error')}"
        )

    message = choices[0].get("message", {})
    content = message.get("content", "")

    if isinstance(content, str):
        answer = content.strip()
    elif isinstance(content, list):
        answer = "".join(
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and isinstance(item.get("text", ""), str)
        ).strip()
    else:
        answer = ""

    if not answer:
        raise RuntimeError("OpenRouter returned no text.")

    return answer


def call_openrouter_sync(
    api_key: str,
    model: str,
    contents: list[dict],
) -> str:
    url = "https://openrouter.ai/api/v1/chat/completions"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
    ]

    for item in contents:
        role = item.get("role", "user")
        if role == "model":
            role = "assistant"
        text = "".join(
            part.get("text", "")
            for part in item.get("parts", [])
            if isinstance(part, dict)
        )
        messages.append({"role": role, "content": text})

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": AI_MAX_OUTPUT_TOKENS,
        "temperature": 0.2,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    if OPENROUTER_SITE_URL:
        headers["HTTP-Referer"] = OPENROUTER_SITE_URL

    if OPENROUTER_SITE_NAME:
        headers["X-Title"] = OPENROUTER_SITE_NAME

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers=headers,
    )

    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        try:
            details = json.loads(body)
            message = details.get("error", {}).get("message", body)
        except json.JSONDecodeError:
            message = body
        raise RuntimeError(
            f"OpenRouter HTTP {error.code}: {message}"
        ) from error
    except urllib.error.URLError as error:
        raise RuntimeError(
            f"OpenRouter network error: {error}"
        ) from error

    return extract_openrouter_content(data)


def normalize_numbered_answer(answer: str) -> str:
    import re

    answer = answer.strip()
    if not answer:
        return answer

    lines = answer.splitlines()
    output: list[str] = []
    next_number = 1

    for line in lines:
        stripped = line.strip()

        if not stripped:
            output.append("")
            continue

        match = re.match(r"^\s*(?:[-*•]|\d+[.)])\s+(.*)$", stripped)
        if match:
            content = match.group(1).strip()
            output.append(f"{next_number}. {content}")
            next_number += 1
        else:
            output.append(line)

    return "\n".join(output).strip()


def friendly_error(error: Exception, provider: str) -> str:
    message = str(error)
    lower = message.casefold()

    if provider == "Gemini":
        if "401" in message or "unauthenticated" in lower:
            return "1. Gemini rejected the API key.\n\n2. Please check GEMINI_API_KEY."
        if "403" in message or "forbidden" in lower:
            return "1. Gemini denied the request.\n\n2. Check the API key and project permissions."
        if "404" in message or "not found" in lower:
            return (
                f"1. The Gemini model `{GEMINI_MODEL}` is unavailable.\n\n"
                "2. Check GEMINI_MODEL in .env."
            )
        if "429" in message or "quota" in lower or "rate limit" in lower:
            return (
                "1. Gemini's current quota/rate limit was reached.\n\n"
                "2. EM Bot will try the backup AI provider automatically."
            )

    if provider == "OpenRouter":
        if "401" in message or "unauthorized" in lower:
            return "1. OpenRouter rejected the API key.\n\n2. Check OPENROUTER_API_KEY."
        if "429" in message or "rate limit" in lower or "quota" in lower:
            return (
                "1. OpenRouter's free limit was reached.\n\n"
                "2. Please try again later."
            )

    return f"1. {provider} could not answer the request right now.\n\n2. Please try again later."


class AI(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="ask",
        description="Ask EM Bot an AI question.",
    )
    async def ask(
        self,
        interaction: discord.Interaction,
        question: str,
    ) -> None:
        if not GEMINI_API_KEY and not OPENROUTER_API_KEY:
            await interaction.response.send_message(
                "1. No AI provider is configured.\n\n"
                "2. Add GEMINI_API_KEY or OPENROUTER_API_KEY to .env.",
                ephemeral=True,
            )
            return

        if AI_CHANNEL_ID and interaction.channel_id != AI_CHANNEL_ID:
            await interaction.response.send_message(
                "1. Please use the configured AI channel for AI questions.",
                ephemeral=True,
            )
            return

        if not interaction.guild:
            await interaction.response.send_message(
                "1. The AI assistant can only use official BSEMC sources inside a server.",
                ephemeral=True,
            )
            return

        now = time.monotonic()
        last = last_request.get(interaction.user.id, 0.0)

        if now - last < AI_COOLDOWN_SECONDS:
            remaining = AI_COOLDOWN_SECONDS - (now - last)
            await interaction.response.send_message(
                f"1. Please wait {remaining:.1f} seconds before asking another question.",
                ephemeral=True,
            )
            return

        last_request[interaction.user.id] = now
        await interaction.response.defer()

        try:
            sources = await fetch_official_sources(
                interaction.guild,
                question,
            )

            contents = build_contents(
                interaction.user.id,
                question.strip(),
                sources,
            )

            answer = None
            provider_used = None
            first_error = None

            # Primary: Gemini.
            if GEMINI_API_KEY:
                try:
                    answer = await asyncio.to_thread(
                        call_gemini_sync,
                        GEMINI_API_KEY,
                        GEMINI_MODEL,
                        contents,
                    )
                    provider_used = "Gemini"
                except Exception as error:
                    first_error = error
                    logger.warning(
                        "Gemini failed; trying OpenRouter fallback: %s",
                        error,
                    )

            # Fallback: OpenRouter.
            if answer is None and OPENROUTER_API_KEY:
                try:
                    answer = await asyncio.to_thread(
                        call_openrouter_sync,
                        OPENROUTER_API_KEY,
                        OPENROUTER_MODEL,
                        contents,
                    )
                    provider_used = "OpenRouter"
                except Exception as error:
                    logger.exception(
                        "OpenRouter fallback failed: %s",
                        error,
                    )

                    if first_error is not None:
                        logger.error(
                            "Primary Gemini failure: %s",
                            first_error,
                        )

                    await interaction.followup.send(
                        "1. Both AI providers were unable to answer the request.\n\n"
                        "2. Please try again later.",
                        ephemeral=True,
                    )
                    return

            if answer is None:
                await interaction.followup.send(
                    "1. No AI provider is currently available.\n\n"
                    "2. Please try again later.",
                    ephemeral=True,
                )
                return

            answer = normalize_numbered_answer(answer)

            history[interaction.user.id].append(
                ("user", question.strip())
            )
            history[interaction.user.id].append(
                ("model", answer)
            )

            chunks = split_for_discord(answer)
            await interaction.followup.send(chunks[0])

            for chunk in chunks[1:]:
                await interaction.followup.send(chunk)

            logger.info(
                "AI answered using %s for user %s.",
                provider_used,
                interaction.user.id,
            )

        except Exception as error:
            logger.exception(
                "AI request failed unexpectedly: %s",
                error,
            )
            await interaction.followup.send(
                "1. EM Bot could not complete the AI request.\n\n"
                "2. Please try again later.",
                ephemeral=True,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AI(bot))
