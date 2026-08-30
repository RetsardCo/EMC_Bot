from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from .common import (
    is_emc_faculty,
    is_moderator,
    is_staff,
)


COMMAND_DESCRIPTIONS = {
    "help": "Show this role-based command guide.",
    "ask": "Ask EM Bot an AI question; you can also attach an image for analysis.",
    "setup": "Open your introduction process. Student and verified-faculty flows are different.",
    "feedback": "Send a feedback message or suggestion to the private staff feedback channel.",
"knowledge": "Staff: open the general knowledge manager, activate verified documents, and review PDF drafts.",
    "knowledge_add": "Staff: upload an official PDF or CSV document for EM Bot to read.",
"knowledge_list": "Staff: list official documents stored in EM Bot knowledge.",
"knowledge_export": "Staff: export the complete knowledge base as a ZIP backup.",
"knowledge_export_md": "Staff: export generated Markdown knowledge files.",
"knowledge_import": "Staff: restore a previously exported knowledge backup.",
"knowledge_rebuild": "Staff: rebuild verified knowledge files using the strict extraction rules.",
"knowledge_rebuild_structured": "Staff: rebuild verified JSON/CSV knowledge only.",
"knowledge_test": "Staff: test exactly how /ask will retrieve official knowledge.",
"poll": "Use the poll features available to you.",
    "nick": "Manually change a member's nickname. Moderator/EMC Faculty only.",
    "announce": "Post an official announcement. Moderator/EMC Faculty only.",
    "timeout": "Temporarily restrict a member.",
    "kick": "Remove a member from the server.",
    "ban": "Ban a member from the server.",
    "purge": "Delete recent messages.",
    "ai_status": "View EM Bot AI routing and provider statistics.",
    "attendance_start": "Staff: start a voice-participation session for a selected voice channel.",
    "attendance_status": "Staff: view the active voice-participation session.",
    "attendance_end": "Staff: end the active voice-participation session and summarize it.",
    "attendance_export": "Staff: download the latest participation-session report as CSV.",
    "activity_export": "Staff: download server and voice activity records as CSV.",
    "daily_chat_now": "Staff: post a daily community prompt now for testing.",
}

STUDENT_COMMANDS = {
    "help",
    "ask",
    "setup",
    "feedback",
    "poll",
}

STAFF_COMMANDS = {
    "nick",
    "announce",
    "timeout",
    "kick",
    "ban",
    "purge",
    "ai_status",
    "knowledge",
    "knowledge_add",
    "knowledge_list",
    "knowledge_export",
    "knowledge_export_md",
    "knowledge_import",
    "knowledge_rebuild",
    "knowledge_rebuild_structured",
    "knowledge_test",
    "knowledge_test_json",
    "attendance_start",
    "attendance_status",
    "attendance_end",
    "attendance_export",
    "activity_export",
    "daily_chat_now",
}


def get_access_level(
    member: discord.Member,
) -> str:
    if is_moderator(member) and is_emc_faculty(member):
        return "Moderator + EMC Faculty"
    if is_moderator(member):
        return "Moderator"
    if is_emc_faculty(member):
        return "EMC Faculty"
    return "Student / General Member"


class Help(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
    ) -> None:
        self.bot = bot

    @app_commands.command(
        name="help",
        description="Show commands available to you.",
    )
    async def help(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if not isinstance(
            interaction.user,
            discord.Member,
        ):
            await interaction.response.send_message(
                "1. EM Bot could not determine your server role.",
                ephemeral=True,
            )
            return

        member = interaction.user
        names = sorted(
            STUDENT_COMMANDS
            | STAFF_COMMANDS
            if is_staff(member)
            else STUDENT_COMMANDS
        )

        embed = discord.Embed(
            title="🤖 EM Bot Help",
            description=(
                f"Access level: **{get_access_level(member)}**\n"
                "Only commands available to your role are listed."
            ),
            color=discord.Color.blurple(),
        )

        for name in names:
            embed.add_field(
                name=f"/{name}",
                value=COMMAND_DESCRIPTIONS[name],
                inline=False,
            )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True,
        )


async def setup(
    bot: commands.Bot,
) -> None:
    await bot.add_cog(
        Help(bot)
    )
