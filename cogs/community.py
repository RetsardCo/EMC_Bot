from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import urllib.parse
import urllib.request
from datetime import date, datetime, time
from html import unescape
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

from .common import is_staff


logger = logging.getLogger("em-bot.community")
PROJECT_DIR = Path(__file__).resolve().parent.parent
STATE_PATH = PROJECT_DIR / "data" / "community_scheduler_state.json"
TOPICS_PATH = PROJECT_DIR / os.getenv("DAILY_CHAT_TOPICS_FILE", "knowledge/daily_topics.json")
TIMEZONE_NAME = os.getenv("COMMUNITY_TIMEZONE", "Asia/Manila")
TIMEZONE = ZoneInfo(TIMEZONE_NAME)
DAILY_CHAT_TIME = os.getenv("DAILY_CHAT_TIME", "09:00")
DAILY_AI_FALLBACK_ENABLED = os.getenv("DAILY_AI_FALLBACK_ENABLED", "true").casefold() in {"1", "true", "yes", "on"}
DAILY_DYNAMIC_ENABLED = os.getenv("DAILY_DYNAMIC_ENABLED", "true").casefold() in {"1", "true", "yes", "on"}
DAILY_MAX_DYNAMIC_ATTEMPTS = max(1, int(os.getenv("DAILY_MAX_DYNAMIC_ATTEMPTS", "5")))
DAILY_HISTORY_LIMIT = max(20, int(os.getenv("DAILY_HISTORY_LIMIT", "150")))
DAILY_RECENT_MESSAGE_LIMIT = max(20, int(os.getenv("DAILY_RECENT_MESSAGE_LIMIT", "80")))
DAILY_TRIVIA_SOURCE_URLS = [
    value.strip()
    for value in os.getenv("DAILY_TRIVIA_SOURCE_URLS", "").split(",")
    if value.strip().startswith(("https://", "http://"))
]
DAILY_TOPIC_SOURCE_URLS = [
    value.strip()
    for value in os.getenv("DAILY_TOPIC_SOURCE_URLS", "").split(",")
    if value.strip().startswith(("https://", "http://"))
]
HOLIDAY_CHECK_TIME = os.getenv("HOLIDAY_CHECK_TIME", "06:00")
NATIONWIDE_HOLIDAY_URL = os.getenv(
    "NATIONWIDE_HOLIDAY_URL",
    "https://www.officialgazette.gov.ph/nationwide-holidays/",
)
LOCAL_HOLIDAY_LOOKBACK = max(1, int(os.getenv("LOCAL_HOLIDAY_SOURCE_LOOKBACK_MESSAGES", "200")))

TRIVIA_TYPES = (
    "an interesting historical fact",
    "a science fact",
    "a technology fact",
    "a computer science fact",
    "an art fact",
    "an animation fact",
    "a game development fact",
    "an engineering fact",
    "a geography fact",
    "a language fact",
    "a mathematics fact",
    "an unusual but well-established general knowledge fact",
)

DEFAULT_TRUSTED_SOURCES = (
    "https://en.wikipedia.org/wiki/Main_Page",
    "https://www.britannica.com/",
)


def ids(name: str) -> set[int]:
    return {
        int(value.strip())
        for value in os.getenv(name, "").split(",")
        if value.strip().isdigit() and int(value.strip())
    }


DAILY_CHAT_CHANNEL_IDS = ids("DAILY_CHAT_CHANNEL_IDS")
HOLIDAY_ANNOUNCEMENT_CHANNEL_IDS = ids("HOLIDAY_ANNOUNCEMENT_CHANNEL_IDS")
LOCAL_HOLIDAY_SOURCE_CHANNEL_IDS = ids("LOCAL_HOLIDAY_SOURCE_CHANNEL_IDS")


def staff_only():
    async def predicate(interaction: discord.Interaction) -> bool:
        return isinstance(interaction.user, discord.Member) and is_staff(interaction.user)

    return app_commands.check(predicate)


def configured_time(value: str) -> time:
    try:
        hour, minute = (int(part) for part in value.split(":", 1))
        return time(hour, minute)
    except (TypeError, ValueError):
        logger.warning("Invalid scheduler time %r; falling back to 09:00.", value)
        return time(9, 0)


def default_topics() -> dict[str, Any]:
    return {
        "topics": [
            {
                "name": "Game Development",
                "prompts": [
                    "What is one small game mechanic that makes a game memorable?",
                    "If you had one week to make a game, what would the core gameplay loop be?",
                    "Which game level taught you something about good level design?",
                ],
            },
            {
                "name": "Drawing",
                "prompts": [
                    "What drawing habit has helped you improve the most?",
                    "Which part of drawing do you find most challenging: form, color, lighting, or perspective?",
                    "Share one reference or study technique that helps you draw better.",
                ],
            },
            {
                "name": "Animation",
                "prompts": [
                    "Which animation principle do you notice most in games or films?",
                    "What makes a movement feel believable in an animation?",
                    "What short animation exercise would you recommend to a beginner?",
                ],
            },
        ]
    }


def load_topics() -> list[dict[str, Any]]:
    try:
        content = json.loads(TOPICS_PATH.read_text(encoding="utf-8"))
        topics = content.get("topics", []) if isinstance(content, dict) else []
        usable = [
            topic
            for topic in topics
            if isinstance(topic, dict) and topic.get("name") and topic.get("prompts")
        ]
        if usable:
            return usable
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not load daily topics from %s; using defaults.", TOPICS_PATH)
    return default_topics()["topics"]


def build_daily_embed(title: str, prompt: str, footer: str = "EM Bot community prompt") -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=(
            f"**{prompt}**\n\n"
            "Share a short answer, sketch, reference, idea, or example below. "
            "Be constructive and give credit when sharing someone else's work."
        ),
        color=discord.Color.teal(),
        timestamp=discord.utils.utcnow(),
    )
    embed.set_footer(text=footer)
    return embed


def build_trivia_embed(topic: str, text: str, source_url: str) -> discord.Embed:
    embed = build_daily_embed(
        f"Daily {topic} Trivia",
        text,
        "Source-backed trivia | EM Bot",
    )
    if source_url:
        embed.add_field(name="Source", value=source_url[:1024], inline=False)
    return embed


def visible_text(value: str) -> str:
    value = re.sub(r"<script.*?</script>|<style.*?</style>", " ", value, flags=re.IGNORECASE | re.DOTALL)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", unescape(value)).strip()


def same_month_day(text: str, target: date) -> bool:
    month = target.strftime("%B")
    day = target.day
    patterns = (
        rf"\b{re.escape(month)}\s+0?{day}(?:\b|,)",
        rf"\b0?{day}\s+{re.escape(month)}\b",
    )
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def nationwide_holidays_from_html(page: str, target: date) -> list[str]:
    """Extract only table/list entries on the Official Gazette holiday page for today."""
    matches: list[str] = []
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", page, flags=re.IGNORECASE | re.DOTALL)
    for row in rows:
        cells = [
            visible_text(cell)
            for cell in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, flags=re.IGNORECASE | re.DOTALL)
        ]
        combined = " | ".join(cell for cell in cells if cell)
        if combined and same_month_day(combined, target):
            name = next((cell for cell in cells if not same_month_day(cell, target)), "Nationwide holiday")
            matches.append(name[:300])

    if not matches:
        items = re.findall(r"<li[^>]*>(.*?)</li>", page, flags=re.IGNORECASE | re.DOTALL)
        for item in items:
            text = visible_text(item)
            if same_month_day(text, target) and len(text) <= 350:
                matches.append(text)
    return list(dict.fromkeys(matches))[:5]


def fetch_nationwide_holidays(target: date) -> list[str]:
    request = urllib.request.Request(
        NATIONWIDE_HOLIDAY_URL,
        headers={"User-Agent": "EM-Bot/1.0 (+institutional holiday notifier)"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        page = response.read().decode("utf-8", errors="replace")
    return nationwide_holidays_from_html(page, target)


def fetch_web_excerpt(url: str, limit: int = 9000) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "EM-Bot/1.0 (+community trivia; educational bot)"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        page = response.read().decode("utf-8", errors="replace")
    return visible_text(page)[:limit]


def fetch_json(url: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "EM-Bot/1.0 (+community trivia; educational bot)"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def search_wikipedia(query: str) -> Optional[dict[str, str]]:
    """Use Wikipedia's public API as a broad fallback source for general-knowledge retrieval."""
    params = urllib.parse.urlencode(
        {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "format": "json",
            "utf8": 1,
            "srlimit": 5,
        }
    )
    api_url = f"https://en.wikipedia.org/w/api.php?{params}"
    data = fetch_json(api_url)
    results = data.get("query", {}).get("search", [])
    if not results:
        return None

    title = str(results[0].get("title", "")).strip()
    if not title:
        return None

    summary_url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(title, safe="")
    try:
        summary = fetch_json(summary_url)
    except Exception:
        return None

    extract = str(summary.get("extract", "")).strip()
    page_url = str(summary.get("content_urls", {}).get("desktop", {}).get("page", "")).strip()
    if not extract or not page_url:
        return None

    return {"text": extract[:9000], "url": page_url, "title": title}


class Community(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.state = self._load_state()

    async def cog_load(self) -> None:
        self.scheduler.start()

    def cog_unload(self) -> None:
        self.scheduler.cancel()

    def _load_state(self) -> dict[str, Any]:
        try:
            state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                raise ValueError("state must be a JSON object")
            return state
        except (OSError, json.JSONDecodeError, ValueError):
            return {"sent": {}, "used_daily_prompts": {}, "daily_history": []}

    def _save_state(self) -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = STATE_PATH.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.state, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(STATE_PATH)

    def _already_sent(self, key: str) -> bool:
        return bool(self.state.setdefault("sent", {}).get(key))

    def _daily_history(self) -> list[dict[str, Any]]:
        history = self.state.setdefault("daily_history", [])
        if not isinstance(history, list):
            history = []
            self.state["daily_history"] = history
        return history

    def _remember_daily_item(
        self,
        topic: str,
        text: str,
        kind: str,
        source_url: str = "",
    ) -> None:
        history = self._daily_history()
        history.append(
            {
                "date": datetime.now(TIMEZONE).date().isoformat(),
                "topic": topic,
                "text": text[:1200],
                "kind": kind,
                "source": source_url[:1024],
            }
        )
        self.state["daily_history"] = history[-DAILY_HISTORY_LIMIT:]
        self._save_state()

    def _topic_sources(self, topic_data: Optional[dict[str, Any]] = None) -> list[str]:
        sources: list[str] = []
        if isinstance(topic_data, dict):
            raw = topic_data.get("sources", topic_data.get("source_urls", []))
            if isinstance(raw, str):
                raw = [raw]
            if isinstance(raw, list):
                sources.extend(str(x).strip() for x in raw if str(x).strip())
        sources.extend(DAILY_TRIVIA_SOURCE_URLS)
        sources.extend(DAILY_TOPIC_SOURCE_URLS)
        return list(dict.fromkeys(url for url in sources if url.startswith(("https://", "http://"))))

    async def _recent_channel_messages(self, limit: int = DAILY_RECENT_MESSAGE_LIMIT) -> list[str]:
        messages: list[str] = []
        for channel_id in DAILY_CHAT_CHANNEL_IDS:
            channel = self.bot.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                continue
            try:
                async for message in channel.history(limit=limit, oldest_first=False):
                    if message.author.bot:
                        continue
                    text = message.content.strip()
                    if text:
                        messages.append(text[:700])
            except (discord.Forbidden, discord.HTTPException):
                logger.exception("Could not read daily-chat history from channel %s.", channel_id)
        return messages[-limit:]

    def _history_text(self, limit: int = 60) -> str:
        entries = self._daily_history()[-limit:]
        if not entries:
            return "(No previous daily-topic history.)"
        return "\n".join(
            f"- [{item.get('kind', 'unknown')}] {item.get('topic', '')}: {item.get('text', '')}"
            for item in entries
        )

    async def _call_ai(
        self,
        instruction: str,
        sources: Optional[list[str]] = None,
        task_name: str = "daily_prompt",
    ) -> Optional[str]:
        if not DAILY_AI_FALLBACK_ENABLED:
            return None
        ai_cog = self.bot.get_cog("AI")
        if ai_cog is None:
            return None
        try:
            answer = await ai_cog.try_gemini(0, instruction, sources or [], None)
            if answer is None:
                from .ai import OPENROUTER_FAST_MODEL

                answer = await ai_cog.try_openrouter(
                    OPENROUTER_FAST_MODEL,
                    task_name,
                    0,
                    instruction,
                    sources or [],
                    None,
                )
            if not answer:
                return None
            cleaned = re.sub(r"\s+", " ", answer).strip()
            return cleaned[:3000] if cleaned else None
        except Exception:
            logger.exception("AI daily-topic request failed (%s).", task_name)
            return None

    async def _is_too_similar(self, topic: str, candidate: str) -> bool:
        history = self._history_text(60)
        recent_messages = await self._recent_channel_messages()
        recent_text = "\n".join(f"- {msg}" for msg in recent_messages[-50:]) or "(No recent community messages.)"

        # Cheap exact/near-exact filter before paying for another AI call.
        candidate_norm = re.sub(r"[^a-z0-9 ]+", " ", candidate.lower())
        candidate_words = {w for w in candidate_norm.split() if len(w) > 3}
        for item in self._daily_history()[-60:]:
            existing_norm = re.sub(r"[^a-z0-9 ]+", " ", str(item.get("text", "")).lower())
            existing_words = {w for w in existing_norm.split() if len(w) > 3}
            if candidate_norm == existing_norm:
                return True
            if candidate_words and existing_words:
                overlap = len(candidate_words & existing_words) / max(1, len(candidate_words | existing_words))
                if overlap >= 0.78:
                    return True

        instruction = f"""
You are checking whether new daily community content is repetitive.

Topic: {topic}

NEW CANDIDATE:
{candidate}

PREVIOUS DAILY CONTENT:
{history}

RECENT COMMUNITY MESSAGES:
{recent_text}

Return exactly one word:
DUPLICATE
or
NEW

Use semantic meaning, not just matching words. Mark DUPLICATE when the candidate
asks substantially the same question, teaches substantially the same fact, or
would make the community feel like the same topic has just been repeated.
"""
        answer = await self._call_ai(instruction, [], "daily_duplicate_check")
        return bool(answer and answer.strip().upper().startswith("DUPLICATE"))

    async def _generate_ai_prompt(self, topic: str) -> Optional[str]:
        instruction = f"""
Create exactly ONE short, open-ended community discussion prompt about: {topic}

Do not state facts, dates, statistics, quotations, rankings, or trivia.
Use a fresh angle that is not similar to the previous daily content below.
Make it constructive, student-friendly, and easy to answer in Discord.
Return only the prompt.

PREVIOUS DAILY CONTENT:
{self._history_text()}
"""
        answer = await self._call_ai(instruction, [], "daily_prompt")
        if not answer:
            return None
        if await self._is_too_similar(topic, answer):
            return None
        return answer[:700]

    async def _retrieve_sources(self, topic: str, topic_data: Optional[dict[str, Any]]) -> list[dict[str, str]]:
        sources: list[dict[str, str]] = []
        configured = self._topic_sources(topic_data)

        # Explicitly configured sources are preferred.
        for url in configured[:8]:
            try:
                excerpt = await asyncio.to_thread(fetch_web_excerpt, url)
                if len(excerpt) >= 120:
                    sources.append({"url": url, "text": excerpt})
            except Exception as error:
                logger.warning("Could not retrieve trivia source %s: %s", url, error)

        # General-knowledge fallback: search Wikipedia for a concrete topic phrase.
        if not sources:
            result = await asyncio.to_thread(search_wikipedia, topic)
            if result:
                sources.append({"url": result["url"], "text": result["text"]})

        return sources

    async def _verify_trivia(
        self,
        topic: str,
        candidate: str,
        source_text: str,
        source_url: str,
    ) -> bool:
        instruction = f"""
You are a strict factual verifier for a student community bot.

TOPIC:
{topic}

CANDIDATE TRIVIA:
{candidate}

SOURCE URL:
{source_url}

SOURCE TEXT:
{source_text}

Check whether every factual claim in the candidate is directly supported by
this source. Reject if the wording adds an unsupported date, number, name,
quote, causal claim, superlative, or other detail. Also reject if the source is
not actually relevant to the candidate.

Return ONLY:
VERIFIED
or
REJECT
"""
        answer = await self._call_ai(
            instruction,
            [f"TRUSTED SOURCE\nSOURCE URL: {source_url}\nSOURCE TEXT:\n{source_text}"],
            "daily_trivia_verify",
        )
        return bool(answer and answer.strip().upper().startswith("VERIFIED"))

    async def _generate_dynamic_trivia(
        self,
        topic: str,
        topic_data: Optional[dict[str, Any]],
    ) -> Optional[dict[str, str]]:
        if not DAILY_DYNAMIC_ENABLED or not DAILY_AI_FALLBACK_ENABLED:
            return None

        sources = await self._retrieve_sources(topic, topic_data)
        if not sources:
            return None

        previous = self._history_text()
        recent = await self._recent_channel_messages()
        recent_text = "\n".join(f"- {msg}" for msg in recent[-40:]) or "(No recent community messages.)"

        for attempt in range(DAILY_MAX_DYNAMIC_ATTEMPTS):
            source = random.choice(sources)
            trivia_type = random.choice(TRIVIA_TYPES)
            instruction = f"""
You are the Daily Knowledge Editor for a student community.

TODAY'S TOPIC:
{topic}

TRIVIA STYLE:
{trivia_type}

PREVIOUS DAILY CONTENT:
{previous}

RECENT COMMUNITY MESSAGES:
{recent_text}

Create ONE genuinely new, interesting trivia item.

Rules:
1. Use ONLY information explicitly supported by the supplied source.
2. Do not use outside memory for factual details.
3. Do not invent or embellish names, dates, numbers, statistics, quotations,
   rankings, causes, or comparisons.
4. Avoid facts already used in previous daily content.
5. Avoid a topic that the recent community messages already discussed heavily.
6. Prefer a surprising but easy-to-understand general-knowledge fact.
7. Return exactly two lines:
Question: <question>
Answer: <one or two sentence answer>
8. If the source does not contain a suitable NEW fact, return NO_PROMPT.

SOURCE:
{source['text']}
"""
            candidate = await self._call_ai(
                instruction,
                [f"TRUSTED SOURCE\nSOURCE URL: {source['url']}\nSOURCE TEXT:\n{source['text']}"],
                "daily_trivia_generation",
            )
            if not candidate or candidate.upper() == "NO_PROMPT":
                continue
            if not re.search(r"Question:\s*.+Answer:\s*.+", candidate, flags=re.IGNORECASE):
                continue
            if await self._is_too_similar(topic, candidate):
                logger.info("Rejected repetitive dynamic trivia candidate on attempt %d.", attempt + 1)
                continue
            if not await self._verify_trivia(topic, candidate, source["text"], source["url"]):
                logger.info("Rejected unverified dynamic trivia candidate on attempt %d.", attempt + 1)
                continue

            return {
                "text": candidate[:1200],
                "source": source["url"],
            }

        return None

    async def _next_daily_embed(self) -> tuple[discord.Embed, Optional[str], dict[str, str]]:
        used = self.state.setdefault("used_daily_prompts", {})
        choices: list[tuple[str, str, str]] = []
        topics = load_topics()

        for topic in topics:
            name = str(topic["name"]).strip()
            for prompt in topic["prompts"]:
                text = str(prompt).strip()
                if not text:
                    continue
                key = f"{name}|{text}"
                if key not in used:
                    choices.append((name, text, key))

        if choices:
            topic, prompt, key = random.choice(choices)
            return (
                build_daily_embed(f"Daily {topic} Chat", prompt),
                key,
                {"topic": topic, "text": prompt, "kind": "json", "source": ""},
            )

        # All hand-written prompts have been used. This is where the bot becomes dynamic.
        topic_data = random.choice(topics) if topics else {"name": "Creative Technology", "prompts": []}
        topic = str(topic_data.get("name", "Creative Technology")).strip() or "Creative Technology"

        trivia = await self._generate_dynamic_trivia(topic, topic_data)
        if trivia:
            return (
                build_trivia_embed(topic, trivia["text"], trivia["source"]),
                None,
                {"topic": topic, "text": trivia["text"], "kind": "trivia", "source": trivia["source"]},
            )

        creative = await self._generate_ai_prompt(topic)
        if creative:
            return (
                build_daily_embed(
                    f"Daily {topic} Chat",
                    creative,
                    "AI-generated discussion prompt | no factual claims",
                ),
                None,
                {"topic": topic, "text": creative, "kind": "ai", "source": ""},
            )

        # Final deterministic fallback: begin a fresh JSON cycle.
        fresh_choices: list[tuple[str, str, str]] = []
        self.state["used_daily_prompts"] = {}
        for topic_item in topics:
            name = str(topic_item.get("name", "")).strip()
            prompts = topic_item.get("prompts", [])
            for prompt in prompts:
                text = str(prompt).strip()
                if name and text:
                    key = f"{name}|{text}"
                    self.state["used_daily_prompts"][key] = False
                    fresh_choices.append((name, text, key))
        self._save_state()

        topic, prompt, key = random.choice(fresh_choices) if fresh_choices else (
            "Creative Technology",
            "What creative project would you like to finish this week?",
            "Creative Technology|What creative project would you like to finish this week?",
        )
        return (
            build_daily_embed(f"Daily {topic} Chat", prompt),
            key,
            {"topic": topic, "text": prompt, "kind": "json_reset", "source": ""},
        )

    def _mark_daily_prompt_used(self, key: Optional[str], item: Optional[dict[str, str]] = None) -> None:
        if key:
            self.state.setdefault("used_daily_prompts", {})[key] = True
        if item:
            self._remember_daily_item(
                item.get("topic", "Creative Technology"),
                item.get("text", ""),
                item.get("kind", "unknown"),
                item.get("source", ""),
            )
        else:
            self._save_state()

    async def _post_embed(self, channel_ids: set[int], embed: discord.Embed) -> int:
        posted = 0
        for channel_id in channel_ids:
            channel = self.bot.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                continue
            try:
                await channel.send(embed=embed)
                posted += 1
            except (discord.Forbidden, discord.HTTPException):
                logger.exception("Could not post scheduled community message to channel %s.", channel_id)
        return posted

    async def _local_holidays(self, target: date) -> list[str]:
        expected = target.isoformat()
        notices: list[str] = []
        pattern = re.compile(rf"^LOCAL_HOLIDAY:\s*{re.escape(expected)}\s*\|\s*(.+)$", re.IGNORECASE)
        for channel_id in LOCAL_HOLIDAY_SOURCE_CHANNEL_IDS:
            channel = self.bot.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                continue
            try:
                async for message in channel.history(limit=LOCAL_HOLIDAY_LOOKBACK, oldest_first=False):
                    match = pattern.match(message.content.strip())
                    if match:
                        notices.append(match.group(1).strip()[:500])
            except (discord.Forbidden, discord.HTTPException):
                logger.exception("Could not read local-holiday source channel %s.", channel_id)
        return list(dict.fromkeys(notices))

    async def _announce_holidays(self, target: date) -> None:
        if not HOLIDAY_ANNOUNCEMENT_CHANNEL_IDS:
            return
        local = await self._local_holidays(target)
        try:
            nationwide = await asyncio.to_thread(fetch_nationwide_holidays, target)
        except Exception as error:
            logger.warning("Official Gazette holiday check failed: %s", error)
            nationwide = []

        notices = [("Nationwide holiday", item) for item in nationwide] + [
            ("BISCAST/local notice", item) for item in local
        ]
        for kind, detail in notices:
            key = f"holiday:{target.isoformat()}:{kind}:{detail}"
            if self._already_sent(key):
                continue
            embed = discord.Embed(
                title="Holiday Notice",
                description=f"**{detail}**\n\nDate: **{target.strftime('%B %d, %Y')}**",
                color=discord.Color.gold(),
            )
            if kind == "Nationwide holiday":
                embed.add_field(name="Official source", value=NATIONWIDE_HOLIDAY_URL, inline=False)
            else:
                embed.add_field(name="Source", value="Configured local knowledge/notice channel", inline=False)
            embed.set_footer(text="Please follow official institutional announcements for class or office arrangements.")
            if await self._post_embed(HOLIDAY_ANNOUNCEMENT_CHANNEL_IDS, embed):
                self.state["sent"][key] = True
                self._save_state()

    @tasks.loop(minutes=5)
    async def scheduler(self) -> None:
        now = datetime.now(TIMEZONE)
        today = now.date()
        if DAILY_CHAT_CHANNEL_IDS and now.time() >= configured_time(DAILY_CHAT_TIME):
            key = f"daily-chat:{today.isoformat()}"
            if not self._already_sent(key):
                embed, prompt_key, item = await self._next_daily_embed()
                if await self._post_embed(DAILY_CHAT_CHANNEL_IDS, embed):
                    self.state["sent"][key] = True
                    self._mark_daily_prompt_used(prompt_key, item)
        if now.time() >= configured_time(HOLIDAY_CHECK_TIME):
            await self._announce_holidays(today)

    @scheduler.before_loop
    async def before_scheduler(self) -> None:
        await self.bot.wait_until_ready()

    @app_commands.command(name="daily_chat_now", description="Post a daily community prompt now for testing.")
    @staff_only()
    async def daily_chat_now(self, interaction: discord.Interaction) -> None:
        if not DAILY_CHAT_CHANNEL_IDS:
            await interaction.response.send_message(
                "Set DAILY_CHAT_CHANNEL_IDS in .env, then restart EM Bot.",
                ephemeral=True,
            )
            return
        embed, prompt_key, item = await self._next_daily_embed()
        count = await self._post_embed(DAILY_CHAT_CHANNEL_IDS, embed)
        if count:
            self._mark_daily_prompt_used(prompt_key, item)
        await interaction.response.send_message(
            f"Posted the daily prompt to **{count}** configured channel(s).",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Community(bot))
