from __future__ import annotations

import csv
import io
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from discord import app_commands
from discord.ext import commands

from .common import is_staff

logger = logging.getLogger("em-bot.activity")

DATA_DIR = Path(os.getenv("ACTIVITY_DATA_DIR", "data"))
if not DATA_DIR.is_absolute():
    DATA_DIR = Path(__file__).resolve().parent.parent / DATA_DIR
DATA_DIR.mkdir(parents=True, exist_ok=True)

EVENTS_PATH = DATA_DIR / "activity_events.jsonl"
SESSIONS_PATH = DATA_DIR / "attendance_sessions.json"

ACTIVITY_LOG_CHANNEL_IDS = {
    int(value.strip())
    for value in os.getenv(
        "ACTIVITY_LOG_CHANNEL_IDS",
        os.getenv("ACTIVITY_LOG_CHANNEL_ID", ""),
    ).split(",")
    if value.strip().isdigit() and int(value.strip())
}

DEFAULT_LATE_AFTER_MINUTES = max(
    0,
    int(os.getenv("ATTENDANCE_LATE_AFTER_MINUTES", "15")),
)

try:
    MANILA_TZ = ZoneInfo("Asia/Manila")
except ZoneInfoNotFoundError:
    MANILA_TZ = timezone(
        timedelta(hours=8),
        name="Asia/Manila",
    )


def staff_only():
    async def predicate(interaction: discord.Interaction) -> bool:
        return (
            isinstance(interaction.user, discord.Member)
            and is_staff(interaction.user)
        )

    return app_commands.check(predicate)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def manila(value: str | datetime) -> datetime:
    parsed = parse_time(value) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(MANILA_TZ)


def format_manila(value: str | datetime) -> str:
    return manila(value).strftime("%B %d, %Y • %I:%M %p")


def format_duration(seconds: int | float) -> str:
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def new_session_id() -> str:
    return f"att-{uuid.uuid4().hex[:12]}"


def member_label(member: discord.Member) -> str:
    return member.display_name[:100]


class ActivityStore:
    def append_event(
        self,
        event_type: str,
        guild: discord.Guild,
        member: discord.Member,
        **details: Any,
    ) -> None:
        payload = {
            "recorded_at": iso(utcnow()),
            "event_type": event_type,
            "guild_id": guild.id,
            "discord_id": member.id,
            "display_name": member_label(member),
            **details,
        }
        with EVENTS_PATH.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def recent_events(
        self,
        guild_id: int,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        if not EVENTS_PATH.exists():
            return []
        records: list[dict[str, Any]] = []
        try:
            for line in EVENTS_PATH.read_text(
                encoding="utf-8"
            ).splitlines()[-limit:]:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if item.get("guild_id") == guild_id:
                    records.append(item)
        except OSError:
            logger.exception("Could not read activity records.")
        return records

    def load_sessions(self) -> dict[str, dict[str, Any]]:
        if not SESSIONS_PATH.exists():
            return {}
        try:
            raw = json.loads(
                SESSIONS_PATH.read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, json.JSONDecodeError):
            logger.exception("Could not read attendance sessions.")
            return {}

        if isinstance(raw, dict) and isinstance(
            raw.get("sessions"), dict
        ):
            raw = raw["sessions"]

        if not isinstance(raw, dict):
            return {}

        sessions: dict[str, dict[str, Any]] = {}
        for key, value in raw.items():
            if not isinstance(value, dict):
                continue
            if not (
                value.get("guild_id")
                and value.get("channel_id")
                and value.get("started_at")
            ):
                continue

            sid = str(
                value.get(
                    "session_id",
                    key,
                )
            )

            # Backward compatibility with the previous guild_id-keyed format.
            if sid.isdigit():
                sid = (
                    f"legacy-{value['guild_id']}-"
                    f"{parse_time(value['started_at']).strftime('%Y%m%d%H%M%S')}"
                )

            value["session_id"] = sid
            sessions[sid] = value

        return sessions

    def save_sessions(
        self,
        sessions: dict[str, dict[str, Any]],
    ) -> None:
        temporary = SESSIONS_PATH.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "version": 2,
                    "sessions": sessions,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary.replace(SESSIONS_PATH)


def session_rows(
    session: dict[str, Any],
    end_time: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    end = end_time or parse_time(
        session.get("ended_at") or iso(utcnow())
    )
    start = parse_time(session["started_at"])
    late_cutoff = start + timedelta(
        minutes=int(session.get("late_after_minutes", 0))
    )

    rows: list[dict[str, Any]] = []

    for participant in session.get(
        "participants",
        {},
    ).values():
        first_join: Optional[datetime] = None
        last_leave: Optional[datetime] = None
        total = 0.0

        for interval in participant.get(
            "intervals",
            [],
        ):
            joined = parse_time(interval["joined_at"])
            left = min(
                parse_time(
                    interval.get("left_at") or iso(end)
                ),
                end,
            )

            if left < joined:
                continue

            total += (
                left - joined
            ).total_seconds()

            first_join = (
                joined
                if first_join is None
                else min(first_join, joined)
            )
            last_leave = (
                left
                if last_leave is None
                else max(last_leave, left)
            )

        if first_join is None:
            continue

        labels: list[str] = []

        if first_join > late_cutoff:
            labels.append("Late")

        if (
            last_leave is not None
            and last_leave < end - timedelta(seconds=2)
        ):
            labels.append("Left Early")

        rows.append(
            {
                "discord_id": participant["discord_id"],
                "display_name": participant["display_name"],
                "first_join": iso(first_join),
                "last_leave": iso(last_leave or end),
                "total_seconds": int(total),
                "status": " / ".join(
                    labels or ["Present"]
                ),
            }
        )

    return sorted(
        rows,
        key=lambda row: (
            row["display_name"].casefold(),
            row["discord_id"],
        ),
    )


def attendance_counts(
    rows: list[dict[str, Any]],
) -> tuple[int, int, int]:
    present = sum(
        row["status"] == "Present"
        for row in rows
    )
    late = sum(
        "Late" in row["status"]
        for row in rows
    )
    early = sum(
        "Left Early" in row["status"]
        for row in rows
    )
    return present, late, early


def build_attendance_csv(
    rows: list[dict[str, Any]],
) -> str:
    """Build the human-facing attendance report in Manila time."""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "Discord ID",
            "Student/Display Name",
            "Date (Manila)",
            "First Join (Manila)",
            "Last Leave (Manila)",
            "Total Time",
            "Status",
        ],
    )
    writer.writeheader()

    for row in rows:
        first_join = manila(row["first_join"])
        last_leave = manila(row["last_leave"])

        writer.writerow(
            {
                "Discord ID": row["discord_id"],
                "Student/Display Name": row["display_name"],
                "Date (Manila)": first_join.strftime("%B %d, %Y"),
                "First Join (Manila)": first_join.strftime("%I:%M:%S %p"),
                "Last Leave (Manila)": last_leave.strftime("%I:%M:%S %p"),
                "Total Time": format_duration(row["total_seconds"]),
                "Status": row["status"],
            }
        )

    return output.getvalue()


class AttendanceReportView(discord.ui.View):
    PAGE_SIZE = 5

    def __init__(
        self,
        session: dict[str, Any],
        rows: list[dict[str, Any]],
    ) -> None:
        super().__init__(timeout=300)
        self.session = session
        self.rows = rows
        self.page = 0
        self.pages = max(
            1,
            (len(rows) + self.PAGE_SIZE - 1)
            // self.PAGE_SIZE,
        )
        self.sync_buttons()

    def sync_buttons(self) -> None:
        self.previous.disabled = self.page <= 0
        self.next.disabled = self.page >= self.pages - 1

    def make_embed(self) -> discord.Embed:
        present, late, early = attendance_counts(
            self.rows
        )

        embed = discord.Embed(
            title="📋 Attendance Session Report",
            description=(
                f"**Session:** {self.session['title']}\n"
                f"**Voice channel:** <#{self.session['channel_id']}>\n"
                f"**Date:** "
                f"{manila(self.session['started_at']).strftime('%B %d, %Y')}\n"
                f"**Started:** {format_manila(self.session['started_at']).split(' • ')[1]}\n"
                f"**Ended:** {format_manila(self.session['ended_at']).split(' • ')[1]}\n\n"
                f"**Recorded participants:** {len(self.rows)}\n"
                f"**Present:** {present}  •  "
                f"**Late:** {late}  •  "
                f"**Left Early:** {early}"
            ),
            color=discord.Color.blurple(),
        )

        begin = self.page * self.PAGE_SIZE
        for number, row in enumerate(
            self.rows[begin:begin + self.PAGE_SIZE],
            start=begin + 1,
        ):
            embed.add_field(
                name=f"{number}. {row['display_name']}"[:256],
                value=(
                    f"**Status:** {row['status']}\n"
                    f"**Joined:** {format_manila(row['first_join'])}\n"
                    f"**Last left:** {format_manila(row['last_leave'])}\n"
                    f"**Total time:** "
                    f"{format_duration(row['total_seconds'])}"
                ),
                inline=False,
            )

        if not self.rows:
            embed.add_field(
                name="Participants",
                value="No recorded voice participation.",
                inline=False,
            )

        embed.set_footer(
            text=(
                f"Page {self.page + 1} of {self.pages} • "
                "Manila time (UTC+8)"
            )
        )
        return embed

    @discord.ui.button(
        label="Previous",
        style=discord.ButtonStyle.secondary,
        emoji="◀️",
    )
    async def previous(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.page = max(0, self.page - 1)
        self.sync_buttons()
        await interaction.response.edit_message(
            embed=self.make_embed(),
            view=self,
        )

    @discord.ui.button(
        label="Next",
        style=discord.ButtonStyle.secondary,
        emoji="▶️",
    )
    async def next(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.page = min(self.pages - 1, self.page + 1)
        self.sync_buttons()
        await interaction.response.edit_message(
            embed=self.make_embed(),
            view=self,
        )


class AttendanceSessionSelect(discord.ui.Select):
    def __init__(
        self,
        sessions: list[dict[str, Any]],
        action: str,
    ) -> None:
        self.action = action

        options = [
            discord.SelectOption(
                label=session["title"][:100],
                description=(
                    f"{session['channel_name']} • "
                    f"{format_manila(session['started_at'])}"
                )[:100],
                value=session["session_id"],
            )
            for session in sessions[:25]
        ]

        super().__init__(
            placeholder="Select an attendance session...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ) -> None:
        cog = interaction.client.get_cog("Activity")

        if cog is None:
            await interaction.response.edit_message(
                content="The activity system is unavailable.",
                view=None,
            )
            return

        session = cog.sessions.get(
            self.values[0]
        )

        if not session:
            await interaction.response.edit_message(
                content="That attendance session is no longer available.",
                view=None,
            )
            return

        if self.action == "status":
            rows = session_rows(
                session,
                utcnow(),
            )
            await interaction.response.edit_message(
                content=None,
                embed=cog.build_status_embed(
                    session,
                    rows,
                ),
                view=None,
            )
            return

        await cog.end_session(
            interaction,
            session,
            selector=True,
        )


class AttendanceSessionSelectView(discord.ui.View):
    def __init__(
        self,
        sessions: list[dict[str, Any]],
        action: str,
    ) -> None:
        super().__init__(timeout=120)
        self.add_item(
            AttendanceSessionSelect(
                sessions,
                action,
            )
        )


class Activity(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
    ) -> None:
        self.bot = bot
        self.store = ActivityStore()
        self.sessions = self.store.load_sessions()
        self.voice_started: dict[
            tuple[int, int],
            datetime,
        ] = {}

    def active_sessions(
        self,
        guild_id: int,
    ) -> list[dict[str, Any]]:
        return [
            session
            for session in self.sessions.values()
            if session.get("guild_id") == guild_id
            and not session.get("ended_at")
        ]

    def active_session_for_channel(
        self,
        guild_id: int,
        channel_id: int,
    ) -> Optional[dict[str, Any]]:
        for session in self.active_sessions(guild_id):
            if session.get("channel_id") == channel_id:
                return session
        return None

    def save(self) -> None:
        self.store.save_sessions(
            self.sessions
        )

    async def send_staff_log(
        self,
        guild: discord.Guild,
        content: str,
    ) -> None:
        for channel_id in ACTIVITY_LOG_CHANNEL_IDS:
            channel = guild.get_channel(channel_id)

            if not isinstance(
                channel,
                discord.TextChannel,
            ):
                continue

            try:
                await channel.send(
                    content[:2000]
                )
            except (
                discord.Forbidden,
                discord.HTTPException,
            ):
                logger.warning(
                    "Could not send activity log to channel %s.",
                    channel_id,
                )

    def add_interval(
        self,
        session: dict[str, Any],
        member: discord.Member,
        joined_at: datetime,
    ) -> None:
        participant = (
            session
            .setdefault(
                "participants",
                {},
            )
            .setdefault(
                str(member.id),
                {
                    "discord_id": member.id,
                    "display_name": member_label(member),
                    "intervals": [],
                },
            )
        )

        participant["display_name"] = (
            member_label(member)
        )

        intervals = participant["intervals"]

        if (
            not intervals
            or intervals[-1].get("left_at")
        ):
            intervals.append(
                {
                    "joined_at": iso(joined_at),
                    "left_at": None,
                }
            )

    def close_interval(
        self,
        session: dict[str, Any],
        member_id: int,
        left_at: datetime,
    ) -> None:
        participant = (
            session
            .get(
                "participants",
                {},
            )
            .get(str(member_id))
        )

        if not participant:
            return

        intervals = participant.get(
            "intervals",
            [],
        )

        if (
            intervals
            and not intervals[-1].get("left_at")
        ):
            intervals[-1]["left_at"] = iso(
                left_at
            )

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        now = utcnow()
        self.voice_started.clear()

        for guild in self.bot.guilds:
            for channel in guild.voice_channels:
                for member in channel.members:
                    if not member.bot:
                        self.voice_started[
                            (
                                guild.id,
                                member.id,
                            )
                        ] = now

    @commands.Cog.listener()
    async def on_member_join(
        self,
        member: discord.Member,
    ) -> None:
        if member.bot:
            return

        self.store.append_event(
            "SERVER_JOIN",
            member.guild,
            member,
        )

        await self.send_staff_log(
            member.guild,
            (
                f"📥 **SERVER JOIN** {member.mention} "
                f"(`{member.id}`)"
            ),
        )

    @commands.Cog.listener()
    async def on_member_remove(
        self,
        member: discord.Member,
    ) -> None:
        if member.bot:
            return

        self.store.append_event(
            "SERVER_LEAVE",
            member.guild,
            member,
        )

        await self.send_staff_log(
            member.guild,
            (
                f"📤 **SERVER LEAVE** "
                f"**{member_label(member)}** "
                f"(`{member.id}`)"
            ),
        )

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if (
            member.bot
            or before.channel == after.channel
        ):
            return

        now = utcnow()
        guild = member.guild
        key = (
            guild.id,
            member.id,
        )

        if before.channel:
            joined_at = self.voice_started.pop(
                key,
                now,
            )

            duration = max(
                0,
                int(
                    (
                        now - joined_at
                    ).total_seconds()
                ),
            )

            self.store.append_event(
                "VOICE_LEAVE"
                if after.channel is None
                else "VOICE_MOVE",
                guild,
                member,
                channel_id=before.channel.id,
                channel_name=before.channel.name,
                joined_at=iso(joined_at),
                left_at=iso(now),
                duration_seconds=duration,
            )

            for session in self.active_sessions(
                guild.id
            ):
                if (
                    session["channel_id"]
                    == before.channel.id
                ):
                    self.close_interval(
                        session,
                        member.id,
                        now,
                    )

            self.save()

            await self.send_staff_log(
                guild,
                (
                    f"🔊 **VOICE LEFT** "
                    f"{member.mention} — "
                    f"**{before.channel.name}** — "
                    f"{format_duration(duration)}"
                ),
            )

        if after.channel:
            self.voice_started[key] = now

            self.store.append_event(
                "VOICE_JOIN"
                if before.channel is None
                else "VOICE_MOVE",
                guild,
                member,
                channel_id=after.channel.id,
                channel_name=after.channel.name,
                joined_at=iso(now),
            )

            for session in self.active_sessions(
                guild.id
            ):
                if (
                    session["channel_id"]
                    == after.channel.id
                ):
                    self.add_interval(
                        session,
                        member,
                        now,
                    )

            self.save()

            await self.send_staff_log(
                guild,
                (
                    f"🎙️ **VOICE JOINED** "
                    f"{member.mention} — "
                    f"**{after.channel.name}**"
                ),
            )

    def build_status_embed(
        self,
        session: dict[str, Any],
        rows: list[dict[str, Any]],
    ) -> discord.Embed:
        present, late, early = attendance_counts(
            rows
        )
        return discord.Embed(
            title="📊 Attendance Status",
            description=(
                f"**Session:** {session['title']}\n"
                f"**Channel:** <#{session['channel_id']}>\n"
                f"**Started:** {format_manila(session['started_at'])}\n"
                f"**Recorded participants:** {len(rows)}\n\n"
                f"**Present:** {present}  •  "
                f"**Late:** {late}  •  "
                f"**Left Early:** {early}"
            ),
            color=discord.Color.blurple(),
        )

    @app_commands.command(
        name="attendance_start",
        description="Start a voice-participation attendance session.",
    )
    @app_commands.describe(
        channel="Voice channel to observe",
        title="Optional session title",
        late_after_minutes="Minutes after start considered late",
    )
    @staff_only()
    async def attendance_start(
        self,
        interaction: discord.Interaction,
        channel: discord.VoiceChannel,
        title: Optional[str] = None,
        late_after_minutes: Optional[
            app_commands.Range[int, 0, 240]
        ] = None,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        if self.active_session_for_channel(
            interaction.guild.id,
            channel.id,
        ):
            await interaction.response.send_message(
                (
                    f"An attendance session is already active for "
                    f"{channel.mention}."
                ),
                ephemeral=True,
            )
            return

        now = utcnow()
        sid = new_session_id()

        session = {
            "session_id": sid,
            "guild_id": interaction.guild.id,
            "channel_id": channel.id,
            "channel_name": channel.name,
            "title": (title or channel.name).strip()[:100],
            "started_at": iso(now),
            "ended_at": None,
            "started_by": interaction.user.id,
            "late_after_minutes": (
                late_after_minutes
                if late_after_minutes is not None
                else DEFAULT_LATE_AFTER_MINUTES
            ),
            "participants": {},
        }

        self.sessions[sid] = session

        for member in channel.members:
            if not member.bot:
                self.add_interval(
                    session,
                    member,
                    now,
                )

        self.save()

        self.store.append_event(
            "ATTENDANCE_STARTED",
            interaction.guild,
            interaction.user,
            session_id=sid,
            channel_id=channel.id,
            channel_name=channel.name,
            title=session["title"],
        )

        await interaction.response.send_message(
            (
                f"Attendance session **{session['title']}** "
                f"started for {channel.mention}.\n\n"
                f"Late threshold: **{session['late_after_minutes']} minutes**\n"
                f"Started: **{format_manila(now)}**\n"
                f"Session ID: `{sid}`"
            ),
            ephemeral=True,
        )

    @app_commands.command(
        name="attendance_status",
        description="Show active voice-participation sessions.",
    )
    @app_commands.describe(
        channel="Optional voice channel to inspect.",
    )
    @staff_only()
    async def attendance_status(
        self,
        interaction: discord.Interaction,
        channel: Optional[discord.VoiceChannel] = None,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        sessions = self.active_sessions(
            interaction.guild.id
        )

        if channel:
            sessions = [
                session
                for session in sessions
                if session["channel_id"] == channel.id
            ]

        if not sessions:
            await interaction.response.send_message(
                "No active attendance session matches that request.",
                ephemeral=True,
            )
            return

        if len(sessions) > 1:
            await interaction.response.send_message(
                "Select the attendance session you want to view.",
                view=AttendanceSessionSelectView(
                    sessions,
                    "status",
                ),
                ephemeral=True,
            )
            return

        session = sessions[0]
        rows = session_rows(
            session,
            utcnow(),
        )

        await interaction.response.send_message(
            embed=self.build_status_embed(
                session,
                rows,
            ),
            ephemeral=True,
        )

    async def end_session(
        self,
        interaction: discord.Interaction,
        session: dict[str, Any],
        *,
        selector: bool = False,
    ) -> None:
        now = utcnow()

        for participant in session.get(
            "participants",
            {},
        ).values():
            intervals = participant.get(
                "intervals",
                [],
            )
            if (
                intervals
                and not intervals[-1].get("left_at")
            ):
                intervals[-1]["left_at"] = iso(now)

        session["ended_at"] = iso(now)
        self.save()

        rows = session_rows(
            session
        )
        present, late, early = attendance_counts(
            rows
        )

        self.store.append_event(
            "ATTENDANCE_ENDED",
            interaction.guild,
            interaction.user,
            session_id=session["session_id"],
            channel_id=session["channel_id"],
            title=session["title"],
            recorded_participants=len(rows),
            present=present,
            late=late,
            left_early=early,
        )

        csv_data = build_attendance_csv(
            rows
        )

        file = discord.File(
            io.BytesIO(
                csv_data.encode(
                    "utf-8-sig"
                )
            ),
            filename=(
                f"attendance-"
                f"{manila(session['started_at']).strftime('%Y%m%d-%H%M')}-"
                f"{session['session_id']}.csv"
            ),
        )

        view = AttendanceReportView(
            session,
            rows,
        )

        content = (
            f"✅ **Attendance session ended:** "
            f"{session['title']}\n\n"
            f"Recorded participants: **{len(rows)}**\n"
            f"Present: **{present}**\n"
            f"Late: **{late}**\n"
            f"Left Early: **{early}**\n\n"
            "The GUI below uses the same recorded rows as "
            "the CSV export."
        )

        if selector:
            await interaction.response.edit_message(
                content=content,
                embed=view.make_embed(),
                view=view,
            )
            await interaction.followup.send(
                content="CSV export:",
                file=file,
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            content=content,
            embed=view.make_embed(),
            view=view,
            file=file,
            ephemeral=True,
        )

    @app_commands.command(
        name="attendance_end",
        description="End an attendance session and show its report.",
    )
    @app_commands.describe(
        channel="Optional voice channel to end.",
    )
    @staff_only()
    async def attendance_end(
        self,
        interaction: discord.Interaction,
        channel: Optional[discord.VoiceChannel] = None,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        sessions = self.active_sessions(
            interaction.guild.id
        )

        if channel:
            sessions = [
                session
                for session in sessions
                if session["channel_id"] == channel.id
            ]

        if not sessions:
            await interaction.response.send_message(
                "No active attendance session matches that request.",
                ephemeral=True,
            )
            return

        if len(sessions) > 1:
            await interaction.response.send_message(
                "Select the attendance session you want to end.",
                view=AttendanceSessionSelectView(
                    sessions,
                    "end",
                ),
                ephemeral=True,
            )
            return

        await self.end_session(
            interaction,
            sessions[0],
        )

    @app_commands.command(
        name="attendance_export",
        description="Download a completed attendance session as CSV.",
    )
    @app_commands.describe(
        channel="Optional voice channel to export.",
    )
    @staff_only()
    async def attendance_export(
        self,
        interaction: discord.Interaction,
        channel: Optional[discord.VoiceChannel] = None,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        sessions = [
            session
            for session in self.sessions.values()
            if session.get("guild_id") == interaction.guild.id
            and session.get("ended_at")
        ]

        if channel:
            sessions = [
                session
                for session in sessions
                if session.get("channel_id") == channel.id
            ]

        if not sessions:
            await interaction.response.send_message(
                "No completed attendance session is available.",
                ephemeral=True,
            )
            return

        session = max(
            sessions,
            key=lambda item: parse_time(
                item["ended_at"]
            ),
        )

        rows = session_rows(
            session
        )
        file = discord.File(
            io.BytesIO(
                build_attendance_csv(rows).encode(
                    "utf-8-sig"
                )
            ),
            filename=(
                f"attendance-"
                f"{manila(session['started_at']).strftime('%Y%m%d-%H%M')}-"
                f"{session['session_id']}.csv"
            ),
        )

        await interaction.response.send_message(
            (
                f"Attendance export for **{session['title']}** "
                f"({len(rows)} recorded participants)."
            ),
            file=file,
            ephemeral=True,
        )

    @app_commands.command(
        name="activity_export",
        description="Download recorded server and voice activity as CSV.",
    )
    @app_commands.describe(
        limit="Maximum recent records, from 1 to 10000",
    )
    @staff_only()
    async def activity_export(
        self,
        interaction: discord.Interaction,
        limit: app_commands.Range[int, 1, 10000] = 1000,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        records = self.store.recent_events(
            interaction.guild.id,
            limit,
        )

        if not records:
            await interaction.response.send_message(
                "No activity records are available yet.",
                ephemeral=True,
            )
            return

        fields = sorted(
            {
                key
                for record in records
                for key in record
            }
        )

        output = io.StringIO(newline="")
        writer = csv.DictWriter(
            output,
            fieldnames=fields,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(records)

        await interaction.response.send_message(
            content=f"Exported **{len(records)}** activity record(s).",
            file=discord.File(
                io.BytesIO(
                    output.getvalue().encode(
                        "utf-8-sig"
                    )
                ),
                filename="activity-log.csv",
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Activity(bot))
