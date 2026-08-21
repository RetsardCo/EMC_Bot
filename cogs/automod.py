from __future__ import annotations

import os
import re
import time
from collections import defaultdict, deque

import discord
from discord.ext import commands, tasks

from .common import MOD_LOG_CHANNEL_ID, log_mod


SPAM_MESSAGE_COUNT = int(os.getenv("SPAM_MESSAGE_COUNT", "5"))
SPAM_WINDOW_SECONDS = float(os.getenv("SPAM_WINDOW_SECONDS", "5"))
MENTION_LIMIT = int(os.getenv("MENTION_LIMIT", "5"))
REPEAT_COUNT = int(os.getenv("REPEAT_COUNT", "3"))
REPEAT_WINDOW_SECONDS = float(os.getenv("REPEAT_WINDOW_SECONDS", "10"))
NEW_ACCOUNT_DAYS = int(os.getenv("NEW_ACCOUNT_DAYS", "7"))
AUTO_TIMEOUT_MINUTES = int(os.getenv("AUTO_TIMEOUT_MINUTES", "10"))

_raw_words = os.getenv("BAD_WORDS", "")
BAD_WORDS = {w.strip().casefold() for w in _raw_words.split(",") if w.strip()}

URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)

message_times: dict[int, deque[float]] = defaultdict(deque)
recent_messages: dict[int, deque[tuple[float, str]]] = defaultdict(deque)
join_times: dict[int, deque[float]] = defaultdict(deque)
strikes: dict[int, int] = defaultdict(int)


class AutoMod(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cleanup.start()

    def cog_unload(self) -> None:
        self.cleanup.cancel()

    def exempt(self, message: discord.Message) -> bool:
        if message.author.bot or not message.guild:
            return True

        member = message.author
        exempt_names = {
            n.strip().casefold()
            for n in os.getenv("AUTOMOD_EXEMPT_ROLES", "").split(",")
            if n.strip()
        }
        if any(role.name.casefold() in exempt_names for role in getattr(member, "roles", [])):
            return True

        exempt_channels = {
            int(x) for x in os.getenv("AUTOMOD_EXEMPT_CHANNEL_IDS", "").split(",")
            if x.strip().isdigit()
        }
        return message.channel.id in exempt_channels

    async def add_strike(self, member: discord.Member, reason: str, public_text: str) -> None:
        strikes[member.id] += 1
        count = strikes[member.id]

        try:
            await member.send(f"EM Bot AutoMod warning: {reason}. Strike {count}.")
        except discord.HTTPException:
            pass

        try:
            await member.timeout(
                discord.utils.utcnow() + __import__("datetime").timedelta(minutes=AUTO_TIMEOUT_MINUTES)
                if count >= 3 else discord.utils.utcnow(),
                reason=f"EM Bot AutoMod: {reason}",
            ) if count >= 3 else None
        except (discord.Forbidden, discord.HTTPException):
            pass

        await log_mod(
            member.guild,
            f"🛡️ AutoMod | {member.mention} | {reason} | strike={count}",
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if self.exempt(message):
            return

        member = message.author
        now = time.monotonic()
        times = message_times[member.id]
        repeats = recent_messages[member.id]

        while times and now - times[0] > SPAM_WINDOW_SECONDS:
            times.popleft()
        while repeats and now - repeats[0][0] > REPEAT_WINDOW_SECONDS:
            repeats.popleft()

        times.append(now)
        normalized = message.content.casefold().strip()
        repeats.append((now, normalized))

        reasons: list[str] = []

        if len(times) >= SPAM_MESSAGE_COUNT:
            reasons.append("rapid spam")

        if normalized and sum(1 for _, content in repeats if content == normalized) >= REPEAT_COUNT:
            reasons.append("repeated message spam")

        if len(message.mentions) >= MENTION_LIMIT:
            reasons.append("excessive mentions")

        if BAD_WORDS:
            lowered = normalized
            if any(word in lowered for word in BAD_WORDS):
                reasons.append("blocked word")

        urls = URL_RE.findall(message.content)
        if urls:
            suspicious = any(
                url.lower().startswith(("http://", "https://")) and
                not any(domain in url.lower() for domain in (
                    "discord.com", "discord.gg", "youtube.com", "youtu.be",
                    "google.com", "github.com"
                ))
                for url in urls
            )
            if suspicious and os.getenv("BLOCK_UNAPPROVED_LINKS", "false").casefold() == "true":
                reasons.append("unapproved link")

        if reasons:
            try:
                await message.delete()
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                pass

            await self.add_strike(
                member,
                ", ".join(dict.fromkeys(reasons)),
                "Spam/AutoMod violation detected.",
            )
            await message.channel.send(
                f"{member.mention}, please slow down. AutoMod detected {', '.join(dict.fromkeys(reasons))}.",
                delete_after=8,
            )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return
        now = time.monotonic()
        for times in join_times.values():
            while times and now - times[0] > 15:
                times.popleft()

        recent = join_times[member.guild.id]
        recent.append(now)

        if len(recent) >= int(os.getenv("RAID_JOIN_THRESHOLD", "8")):
            await log_mod(
                member.guild,
                f"🚨 Possible raid detected: {len(recent)} joins within 15 seconds. No automatic lockdown was performed.",
            )

        age_days = (discord.utils.utcnow() - member.created_at).total_seconds() / 86400
        if age_days < NEW_ACCOUNT_DAYS:
            await log_mod(
                member.guild,
                f"⚠️ Suspicious new account: {member.mention} is about {age_days:.1f} days old.",
            )

    @tasks.loop(minutes=10)
    async def cleanup(self) -> None:
        now = time.monotonic()
        for mapping in (message_times, recent_messages):
            for key in list(mapping):
                dq = mapping[key]
                while dq:
                    first = dq[0][0] if isinstance(dq[0], tuple) else dq[0]
                    if now - first <= 120:
                        break
                    dq.popleft()
                if not dq:
                    mapping.pop(key, None)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AutoMod(bot))
