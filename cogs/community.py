from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
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
KNOWLEDGE_DIR = PROJECT_DIR / "knowledge"
KNOWLEDGE_SOURCE_DIR = KNOWLEDGE_DIR / "source"
KNOWLEDGE_MANIFEST_PATH = KNOWLEDGE_DIR / "manifest.json"
TIMEZONE_NAME = os.getenv("COMMUNITY_TIMEZONE", "Asia/Manila")
TIMEZONE = ZoneInfo(TIMEZONE_NAME)
DAILY_CHAT_TIME = os.getenv("DAILY_CHAT_TIME", "09:00")
DAILY_AI_FALLBACK_ENABLED = os.getenv("DAILY_AI_FALLBACK_ENABLED", "true").casefold() in {"1", "true", "yes", "on"}
DAILY_DYNAMIC_ENABLED = os.getenv("DAILY_DYNAMIC_ENABLED", "true").casefold() in {"1", "true", "yes", "on"}
DAILY_MODE_PATH = PROJECT_DIR / "data" / "daily_knowledge_mode.json"
DAILY_OFFLINE_ITEMS_PATH = PROJECT_DIR / "knowledge" / "daily_items.json"
DAILY_OFFLINE_POOL_WEIGHT = max(1, int(os.getenv("DAILY_OFFLINE_POOL_WEIGHT", "20")))
DAILY_WEB_POOL_WEIGHT = max(1, int(os.getenv("DAILY_WEB_POOL_WEIGHT", "10")))
DAILY_WEBSITE_SOURCE_WEIGHT = max(1, int(os.getenv("DAILY_WEBSITE_SOURCE_WEIGHT", "10")))
DAILY_MAX_DYNAMIC_ATTEMPTS = max(1, int(os.getenv("DAILY_MAX_DYNAMIC_ATTEMPTS", "2")))
DAILY_AI_DUPLICATE_CHECK_ENABLED = os.getenv("DAILY_AI_DUPLICATE_CHECK_ENABLED", "false").casefold() in {"1", "true", "yes", "on"}
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
                "sources": [
                    "https://learn.unity.com/tutorial/controlling-gameobjects-using-components",
                    "https://dev.epicgames.com/documentation/en-us/unreal-engine/get-started",
                    "https://docs.godotengine.org/en/stable/tutorials/step_by_step/nodes_and_scenes.html",
                ],
            },
            {
                "name": "Game Engines",
                "sources": [
                    "https://docs.unity3d.com/6000.1/Documentation/Manual/Components.html",
                    "https://dev.epicgames.com/documentation/en-us/unreal-engine/get-started",
                    "https://docs.godotengine.org/en/stable/tutorials/step_by_step/scene_organization.html",
                ],
            },
            {
                "name": "Animation",
                "sources": [
                    "https://docs.blender.org/manual/en/latest/editors/dope_sheet/introduction.html",
                    "https://docs.blender.org/manual/en/latest/animation/keyframes/editing.html",
                    "https://www.animationmentor.com/articles/12-principles-of-animation/",
                ],
            },
            {
                "name": "3D Art",
                "sources": [
                    "https://docs.blender.org/manual/en/latest/",
                    "https://docs.blender.org/manual/en/latest/editors/dope_sheet/introduction.html",
                ],
            },
            {
                "name": "Computer Graphics",
                "sources": [
                    "https://www.khronos.org/opengl/wiki/Rendering_Pipeline_Overview",
                    "https://www.khronos.org/opengl/wiki/Getting_Started",
                ],
            },
            {
                "name": "Programming for Games",
                "sources": [
                    "https://dev.epicgames.com/documentation/en-us/unreal-engine/programming-basics-with-unreal-engine",
                    "https://docs.unity3d.com/6000.1/Documentation/Manual/Components.html",
                    "https://docs.godotengine.org/en/stable/tutorials/step_by_step/nodes_and_scenes.html",
                ],
            },
            {
                "name": "Anime",
                "sources": [
                    "https://en.wikipedia.org/wiki/Anime",
                ],
            },
            {
                "name": "Animated Works",
                "sources": [
                    "https://en.wikipedia.org/wiki/Animation",
                    "https://www.britannica.com/art/animation",
                ],
            },
            {
                "name": "Games",
                "sources": [
                    "https://en.wikipedia.org/wiki/Video_game",
                    "https://www.britannica.com/technology/video-game",
                ],
            },
        ]
    }


def load_topics() -> list[dict[str, Any]]:
    try:
        content = json.loads(TOPICS_PATH.read_text(encoding="utf-8"))
        topics = content.get("topics", []) if isinstance(content, dict) else []
        usable = []
        for topic in topics:
            if not isinstance(topic, dict) or not topic.get("name"):
                continue
            sources = topic.get("sources", topic.get("source_urls", []))
            if isinstance(sources, str):
                sources = [sources]
            if not isinstance(sources, list):
                sources = []
            cleaned = [str(x).strip() for x in sources if str(x).strip().startswith(("https://", "http://"))]
            usable.append({"name": str(topic["name"]).strip(), "sources": cleaned})
        if usable:
            return usable
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not load daily topics from %s; using defaults.", TOPICS_PATH)
    return default_topics()["topics"]


def format_daily_source(source: object) -> str:
    if not source:
        return "Source not provided."

    if isinstance(source, dict):
        source_type = str(source.get("type", "")).strip().casefold()

        if source_type == "website":
            name = str(source.get("name", "Approved Website")).strip()
            url = str(source.get("url", "")).strip()
            if name and url:
                return f"**{name}**\n{url}"
            return url or name or "Approved Website"

        if source_type == "book":
            title = str(
                source.get(
                    "title",
                    source.get("name", "Reference Book"),
                )
            ).strip()
            author = str(source.get("author", "")).strip()
            page = source.get("page", "")

            lines = [f"**{title or 'Reference Book'}**"]
            if author:
                lines.append(author)
            if page not in ("", None):
                lines.append(f"Page {page}")
            return "\n".join(lines)

        name = str(
            source.get(
                "name",
                source.get("title", "Approved Source"),
            )
        ).strip()
        url = str(source.get("url", "")).strip()
        return f"**{name}**\n{url}" if name and url else (name or url)

    return str(source).strip() or "Source not provided."


def build_knowledge_embed(
    topic: str,
    fact: str,
    explanation: str,
    source: object,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"Daily {topic} Knowledge",
        description=f"**{fact}**\n\n{explanation}",
        color=discord.Color.teal(),
        timestamp=discord.utils.utcnow(),
    )

    if source:
        if isinstance(source, dict):
            kind = str(source.get("type", "")).strip().casefold()
            label = (
                "Reference Book"
                if kind == "book"
                else "Website"
                if kind == "website"
                else "Source"
            )
            value = format_daily_source(source)
        elif isinstance(source, str) and source.startswith("book://"):
            filename = source[len("book://"):]
            title = Path(filename).stem.replace("_", " ").strip()
            try:
                manifest = json.loads(
                    KNOWLEDGE_MANIFEST_PATH.read_text(
                        encoding="utf-8"
                    )
                )
                title = str(
                    manifest.get(filename, {}).get(
                        "title",
                        title,
                    )
                ).strip()
            except (OSError, json.JSONDecodeError):
                pass

            label = "Reference Book"
            value = f"**{title}**\n`{filename}`"
        else:
            label = "Source"
            value = format_daily_source(source)

        embed.add_field(
            name=label,
            value=value[:1024],
            inline=False,
        )

    embed.set_footer(
        text="Source-backed daily knowledge | EM Bot"
    )
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



def load_reference_book_sources() -> list[dict[str, Any]]:
    try:
        manifest = json.loads(
            KNOWLEDGE_MANIFEST_PATH.read_text(
                encoding="utf-8"
            )
        )
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(manifest, dict):
        return []

    results: list[dict[str, Any]] = []

    for filename, entry in manifest.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("category") != "reference_book":
            continue
        if not entry.get("daily_source_enabled"):
            continue
        if str(entry.get("status", "")).casefold() in {"draft", "archived"}:
            continue

        path = KNOWLEDGE_SOURCE_DIR / str(filename)
        if not path.is_file() or path.suffix.casefold() != ".json":
            continue

        try:
            data = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, json.JSONDecodeError):
            logger.warning(
                "Could not load reference book %s for Daily Knowledge.",
                filename,
            )
            continue

        text = json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ).strip()

        if len(text) < 120:
            continue

        try:
            weight = max(
                1,
                min(
                    100,
                    int(
                        entry.get(
                            "daily_source_weight",
                            25,
                        )
                    ),
                ),
            )
        except (TypeError, ValueError):
            weight = 25

        results.append(
            {
                "url": f"book://{filename}",
                "text": text[:18000],
                "title": str(
                    entry.get(
                        "title",
                        Path(filename).stem.replace("_", " "),
                    )
                ).strip()[:120],
                "weight": weight,
                "source_type": "reference_book",
            }
        )

    return results


def weighted_random_source(
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    if not sources:
        raise RuntimeError("No daily knowledge sources are available.")

    return random.choices(
        sources,
        weights=[
            max(1, int(source.get("weight", 1)))
            for source in sources
        ],
        k=1,
    )[0]



def load_offline_daily_sources() -> list[dict[str, Any]]:
    try:
        data = json.loads(
            DAILY_OFFLINE_ITEMS_PATH.read_text(
                encoding="utf-8"
            )
        )
    except (OSError, json.JSONDecodeError):
        return []

    raw_sources = data.get("sources", []) if isinstance(data, dict) else []
    if not isinstance(raw_sources, list):
        return []

    sources: list[dict[str, Any]] = []

    for source_index, raw in enumerate(raw_sources):
        if not isinstance(raw, dict):
            continue

        items = raw.get("items", [])
        if not isinstance(items, list):
            continue

        usable: list[dict[str, Any]] = []

        for item_index, item in enumerate(items):
            if not isinstance(item, dict):
                continue

            fact = str(item.get("fact", "")).strip()
            explanation = str(item.get("explanation", "")).strip()

            if not fact or not explanation:
                continue

            item_id = str(
                item.get(
                    "id",
                    f"offline-{source_index + 1}-{item_index + 1}",
                )
            ).strip()

            if not item_id:
                continue

            usable.append(
                {
                    "id": item_id,
                    "topic": str(
                        item.get(
                            "topic",
                            raw.get(
                                "topic",
                                "Creative Technology",
                            ),
                        )
                    ).strip() or "Creative Technology",
                    "title": str(
                        item.get(
                            "title",
                            "",
                        )
                    ).strip(),
                    "fact": fact,
                    "explanation": explanation,
                    "source": item.get(
                        "source",
                        raw.get(
                            "source",
                            "Approved Offline Reference",
                        ),
                    ),
                }
            )

        if not usable:
            continue

        try:
            weight = max(
                1,
                min(
                    100,
                    int(
                        raw.get(
                            "weight",
                            DAILY_OFFLINE_POOL_WEIGHT,
                        )
                    ),
                ),
            )
        except (TypeError, ValueError):
            weight = DAILY_OFFLINE_POOL_WEIGHT

        sources.append(
            {
                "id": str(
                    raw.get(
                        "id",
                        f"offline-source-{source_index + 1}",
                    )
                ),
                "title": str(
                    raw.get(
                        "title",
                        f"Offline Source {source_index + 1}",
                    )
                ).strip()[:120],
                "weight": weight,
                "items": usable,
            }
        )

    return sources


def load_daily_mode() -> dict[str, Any]:
    try:
        data = json.loads(
            DAILY_MODE_PATH.read_text(
                encoding="utf-8"
            )
        )
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass

    return {
        "mode": "offline",
        "web_today": None,
    }


def save_daily_mode(data: dict[str, Any]) -> None:
    DAILY_MODE_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    temporary = DAILY_MODE_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    temporary.replace(DAILY_MODE_PATH)


def current_daily_mode() -> str:
    data = load_daily_mode()
    today = datetime.now(TIMEZONE).date().isoformat()

    if data.get("web_today") == today:
        return "web_today"

    mode = str(
        data.get("mode", "offline")
    ).casefold()

    return mode if mode in {"offline", "mixed"} else "offline"


def set_daily_mode(mode: str) -> None:
    data = load_daily_mode()
    today = datetime.now(TIMEZONE).date().isoformat()

    if mode == "web_today":
        data["web_today"] = today
    else:
        data["mode"] = mode
        data["web_today"] = None

    data["updated_at"] = datetime.now(
        timezone.utc
    ).isoformat()

    save_daily_mode(data)


def choose_offline_item(
    state: dict[str, Any],
) -> Optional[dict[str, Any]]:
    sources = load_offline_daily_sources()
    if not sources:
        return None

    used = state.setdefault(
        "used_offline_daily_items",
        {},
    )

    groups: list[dict[str, Any]] = []

    for source in sources:
        unused = [
            item
            for item in source["items"]
            if not used.get(item["id"])
        ]

        if unused:
            groups.append(
                {
                    **source,
                    "items": unused,
                }
            )

    if not groups:
        # Reset the corpus for a new cycle.
        used.clear()

        for source in sources:
            groups.append(source)

    source = random.choices(
        groups,
        weights=[
            group["weight"]
            for group in groups
        ],
        k=1,
    )[0]

    return random.choice(source["items"])


class DailyKnowledgeModeView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=180)
        self.refresh_buttons()

    def refresh_buttons(self) -> None:
        mode = current_daily_mode()
        self.offline.disabled = mode == "offline"
        self.mixed.disabled = mode == "mixed"
        self.web_today.disabled = mode == "web_today"

    @discord.ui.button(
        label="Offline Only",
        style=discord.ButtonStyle.success,
        emoji="📚",
    )
    async def offline(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user):
            await interaction.response.send_message(
                "Only staff can change Daily Knowledge mode.",
                ephemeral=True,
            )
            return

        set_daily_mode("offline")
        self.refresh_buttons()

        await interaction.response.edit_message(
            content=(
                "📚 **Daily Knowledge: Offline Only**\n\n"
                "Scheduled posts use the pre-generated local corpus.\n"
                "**No AI generation request is required.**"
            ),
            view=self,
        )

    @discord.ui.button(
        label="Mixed",
        style=discord.ButtonStyle.primary,
        emoji="🎲",
    )
    async def mixed(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user):
            await interaction.response.send_message(
                "Only staff can change Daily Knowledge mode.",
                ephemeral=True,
            )
            return

        set_daily_mode("mixed")
        self.refresh_buttons()

        await interaction.response.edit_message(
            content=(
                "🎲 **Daily Knowledge: Mixed**\n\n"
                "Offline and online sources are selected by pool weight.\n"
                "If online generation fails, the offline corpus takes over."
            ),
            view=self,
        )

    @discord.ui.button(
        label="Web for Today",
        style=discord.ButtonStyle.secondary,
        emoji="🌐",
    )
    async def web_today(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user):
            await interaction.response.send_message(
                "Only staff can change Daily Knowledge mode.",
                ephemeral=True,
            )
            return

        set_daily_mode("web_today")
        self.refresh_buttons()

        await interaction.response.edit_message(
            content=(
                "🌐 **Daily Knowledge: Web for Today**\n\n"
                "The online/AI path is enabled for today's scheduled post only.\n"
                "The next Manila date automatically returns to Offline Only."
            ),
            view=self,
        )


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

        if not DAILY_AI_DUPLICATE_CHECK_ENABLED:
            return False

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
teaches substantially the same fact or repeats substantially the same information.
"""
        answer = await self._call_ai(instruction, [], "daily_duplicate_check")
        return bool(answer and answer.strip().upper().startswith("DUPLICATE"))

    async def _retrieve_sources(
        self,
        topic: str,
        topic_data: Optional[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        sources: list[dict[str, Any]] = []

        for url in self._topic_sources(topic_data)[:8]:
            try:
                excerpt = await asyncio.to_thread(
                    fetch_web_excerpt,
                    url,
                )
                if len(excerpt) >= 120:
                    sources.append(
                        {
                            "url": url,
                            "text": excerpt,
                            "title": topic,
                            "weight": DAILY_WEBSITE_SOURCE_WEIGHT,
                            "source_type": "website",
                        }
                    )
            except Exception as error:
                logger.warning(
                    "Could not retrieve trivia source %s: %s",
                    url,
                    error,
                )

        sources.extend(
            load_reference_book_sources()
        )

        if not sources:
            result = await asyncio.to_thread(
                search_wikipedia,
                topic,
            )
            if result:
                sources.append(
                    {
                        "url": result["url"],
                        "text": result["text"],
                        "title": result["title"],
                        "weight": 5,
                        "source_type": "fallback",
                    }
                )

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

    async def _generate_daily_knowledge(
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
            source = weighted_random_source(sources)
            knowledge_type = random.choice(TRIVIA_TYPES)
            instruction = f"""
You are the Daily Knowledge Editor for a student community.

TODAY'S TOPIC:
{topic}

KNOWLEDGE STYLE:
{knowledge_type}

PREVIOUS DAILY CONTENT:
{previous}

RECENT COMMUNITY MESSAGES:
{recent_text}

Create ONE genuinely new, useful, interesting factual item for students.

Rules:
1. Use ONLY information explicitly supported by the supplied source.
2. Do not use outside memory for factual details.
3. Do not invent or embellish names, dates, numbers, statistics, quotations,
   rankings, causes, or comparisons.
4. Avoid facts already used in previous daily content.
5. Avoid a topic that the recent community messages already discussed heavily.
6. Do NOT ask a question anywhere in the output.
7. Do NOT use question marks.
8. Return exactly three lines:
FACT: <one clear factual statement>
EXPLANATION: <one or two beginner-friendly sentences>
TOPIC: <short topic label>
9. If the source does not contain a suitable NEW fact, return NO_ITEM.

SOURCE URL:
{source['url']}

SOURCE TEXT:
{source['text']}
"""
            candidate = await self._call_ai(
                instruction,
                [f"TRUSTED SOURCE\nSOURCE URL: {source['url']}\nSOURCE TEXT:\n{source['text']}"],
                "daily_knowledge_generation",
            )
            if not candidate or candidate.strip().upper() == "NO_ITEM":
                continue

            match = re.search(
                r"FACT:\s*(.+?)\s+EXPLANATION:\s*(.+?)\s+TOPIC:\s*(.+)$",
                candidate,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if not match:
                continue

            fact = re.sub(r"\s+", " ", match.group(1)).strip()
            explanation = re.sub(r"\s+", " ", match.group(2)).strip()
            label = re.sub(r"\s+", " ", match.group(3)).strip()
            if "?" in fact or "?" in explanation or "?" in label:
                continue
            if await self._is_too_similar(topic, f"{fact} {explanation}"):
                logger.info("Rejected repetitive daily knowledge candidate on attempt %d.", attempt + 1)
                continue

            candidate_text = f"FACT: {fact}\nEXPLANATION: {explanation}"
            if not await self._verify_trivia(topic, candidate_text, source["text"], source["url"]):
                logger.info("Rejected unverified daily knowledge candidate on attempt %d.", attempt + 1)
                continue

            return {
                "topic": label or topic,
                "fact": fact,
                "explanation": explanation,
                "source": source["url"],
                "text": f"{fact}\n\n{explanation}",
            }

        return None

    async def _next_daily_embed(
        self,
    ) -> tuple[discord.Embed, Optional[str], dict[str, Any]]:
        mode = current_daily_mode()

        # Offline: zero AI generation calls.
        if mode == "offline":
            item = choose_offline_item(self.state)

            if not item:
                raise RuntimeError(
                    "No pre-generated offline daily knowledge items are available."
                )

            self.state.setdefault(
                "used_offline_daily_items",
                {},
            )[item["id"]] = True
            self._save_state()

            source = item.get(
                "source",
                "Approved Offline Reference",
            )

            return (
                build_knowledge_embed(
                    item["topic"],
                    item["fact"],
                    item["explanation"],
                    source,
                ),
                item["id"],
                {
                    "topic": item["topic"],
                    "text": f"{item['fact']}\n\n{item['explanation']}",
                    "kind": "offline_knowledge",
                    "source": source,
                },
            )

        # Mixed: choose offline vs web BEFORE making any web/AI request.
        if mode == "mixed" and load_offline_daily_sources():
            selected = random.choices(
                ["offline", "web"],
                weights=[
                    DAILY_OFFLINE_POOL_WEIGHT,
                    DAILY_WEB_POOL_WEIGHT,
                ],
                k=1,
            )[0]

            if selected == "offline":
                item = choose_offline_item(self.state)

                if item:
                    self.state.setdefault(
                        "used_offline_daily_items",
                        {},
                    )[item["id"]] = True
                    self._save_state()

                    source = item.get(
                        "source",
                        "Approved Offline Reference",
                    )

                    return (
                        build_knowledge_embed(
                            item["topic"],
                            item["fact"],
                            item["explanation"],
                            source,
                        ),
                        item["id"],
                        {
                            "topic": item["topic"],
                            "text": f"{item['fact']}\n\n{item['explanation']}",
                            "kind": "offline_knowledge",
                            "source": source,
                        },
                    )

        # Web path. It remains limited to configured topic sources.
        topics = load_topics()
        candidates = topics[:]
        random.shuffle(candidates)

        for topic_data in candidates:
            topic = str(
                topic_data.get(
                    "name",
                    "Creative Technology",
                )
            ).strip() or "Creative Technology"

            item = await self._generate_daily_knowledge(
                topic,
                topic_data,
            )

            if item:
                return (
                    build_knowledge_embed(
                        item["topic"],
                        item["fact"],
                        item["explanation"],
                        item["source"],
                    ),
                    None,
                    {
                        "topic": item["topic"],
                        "text": item["text"],
                        "kind": "web_knowledge",
                        "source": item["source"],
                    },
                )

        # Online failed: offline takeover.
        item = choose_offline_item(self.state)

        if item:
            self.state.setdefault(
                "used_offline_daily_items",
                {},
            )[item["id"]] = True
            self._save_state()

            source = item.get(
                "source",
                "Approved Offline Reference",
            )

            return (
                build_knowledge_embed(
                    item["topic"],
                    item["fact"],
                    item["explanation"],
                    source,
                ),
                item["id"],
                {
                    "topic": item["topic"],
                    "text": f"{item['fact']}\n\n{item['explanation']}",
                    "kind": "offline_fallback",
                    "source": source,
                },
            )

        raise RuntimeError(
            "No verified daily knowledge item is available from approved online or offline sources."
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

    async def _announce_holidays(self, target: date, days_ahead: int = 0) -> None:
        if not HOLIDAY_ANNOUNCEMENT_CHANNEL_IDS:
            return

        local = await self._local_holidays(target)
        try:
            nationwide = await asyncio.to_thread(fetch_nationwide_holidays, target)
        except Exception as error:
            logger.warning("Official Gazette holiday check failed for %s: %s", target, error)
            nationwide = []

        notices = [("Nationwide holiday", item) for item in nationwide] + [
            ("BISCAST/local notice", item) for item in local
        ]
        for kind, detail in notices:
            if days_ahead == 3:
                key = f"holiday-reminder:{target.isoformat()}:{kind}:{detail}"
                title = "Holiday Reminder"
                description = (
                    f"**{detail}** is coming in **3 days**.\n\n"
                    f"Date: **{target.strftime('%B %d, %Y')}**"
                )
            else:
                key = f"holiday:{target.isoformat()}:{kind}:{detail}"
                title = "Holiday Notice"
                description = f"**{detail}**\n\nDate: **{target.strftime('%B %d, %Y')}**"

            if self._already_sent(key):
                continue

            embed = discord.Embed(
                title=title,
                description=description,
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
            key = f"daily-knowledge:{today.isoformat()}"
            if not self._already_sent(key):
                try:
                    embed, prompt_key, item = await self._next_daily_embed()
                    posted = await self._post_embed(DAILY_CHAT_CHANNEL_IDS, embed)
                    if posted:
                        self.state["sent"][key] = True
                        self._mark_daily_prompt_used(prompt_key, item)
                        logger.info("Daily knowledge post sent for %s to %d channel(s).", today, posted)
                except Exception:
                    logger.exception("Daily knowledge generation/post failed for %s", today)

        if now.time() >= configured_time(HOLIDAY_CHECK_TIME):
            await self._announce_holidays(today, 0)
            await self._announce_holidays(today + timedelta(days=3), 3)

    @scheduler.before_loop
    async def before_scheduler(self) -> None:
        await self.bot.wait_until_ready()

    @app_commands.command(
        name="daily_knowledge",
        description="Choose Daily Knowledge source mode.",
    )
    @staff_only()
    async def daily_knowledge(
        self,
        interaction: discord.Interaction,
    ) -> None:
        labels = {
            "offline": "📚 Offline Only",
            "mixed": "🎲 Mixed",
            "web_today": "🌐 Web for Today",
        }

        await interaction.response.send_message(
            (
                "🧠 **Daily Knowledge Mode**\n\n"
                f"Current mode: **{labels.get(current_daily_mode(), '📚 Offline Only')}**\n\n"
                "Choose how the scheduled Daily Knowledge post should get its content."
            ),
            view=DailyKnowledgeModeView(),
            ephemeral=True,
        )

    @app_commands.command(name="daily_chat_now", description="Post a daily knowledge item now for testing.")
    @staff_only()
    async def daily_chat_now(self, interaction: discord.Interaction) -> None:
        if not DAILY_CHAT_CHANNEL_IDS:
            await interaction.response.send_message(
                "Set DAILY_CHAT_CHANNEL_IDS in .env, then restart EM Bot.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        try:
            embed, _, item = await self._next_daily_embed()
            count = await self._post_embed(DAILY_CHAT_CHANNEL_IDS, embed)
            if count:
                self._remember_daily_item(
                    item.get("topic", "Creative Technology"),
                    item.get("text", ""),
                    item.get("kind", "knowledge"),
                    item.get("source", ""),
                )
            await interaction.followup.send(
                f"Posted the daily knowledge test to **{count}** configured channel(s).\n"
                "This test does **not** consume today's scheduled post.",
                ephemeral=True,
            )
        except Exception as error:
            logger.exception("Daily knowledge test failed: %s", error)
            await interaction.followup.send(
                "No verified daily knowledge item could be generated right now. Check the EM Bot console for details.",
                ephemeral=True,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Community(bot))
