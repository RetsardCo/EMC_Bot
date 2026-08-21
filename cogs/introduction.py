import os
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from .common import (
    FACULTY_ROLE_NAME,
    INTRO_COMPLETE_CHANNEL_ID,
    INTRODUCED_ROLE_NAME,
    STUDENT_ROLE_NAME,
    UNINTRODUCED_ROLE_NAME,
    add_role_if_missing,
    has_role,
    remove_role_if_present,
)

MAX_NICKNAME_LENGTH = 32
INTRO_CHANNEL_ID = int(os.getenv("INTRO_CHANNEL_ID", "0"))


def normalize_name(value: str) -> str:
    value = " ".join(value.split()).strip()
    if not value:
        return ""
    return value[0].upper() + value[1:]


def normalize_specialization(value: str) -> Optional[str]:
    value = " ".join(value.split()).strip().casefold()
    return {
        "dat": "DAT",
        "digital animation technology": "DAT",
        "gd": "GD",
        "game development": "GD",
    }.get(value)


def normalize_year(value: str) -> Optional[str]:
    value = " ".join(value.split()).strip().casefold()
    return {
        "1": "1st Year", "1st": "1st Year", "1st year": "1st Year", "first": "1st Year", "first year": "1st Year",
        "2": "2nd Year", "2nd": "2nd Year", "2nd year": "2nd Year", "second": "2nd Year", "second year": "2nd Year",
        "3": "3rd Year", "3rd": "3rd Year", "3rd year": "3rd Year", "third": "3rd Year", "third year": "3rd Year",
        "4": "4th Year", "4th": "4th Year", "4th year": "4th Year", "fourth": "4th Year", "fourth year": "4th Year",
    }.get(value)


def build_student_nickname(name: str, specialization: str, year: str) -> str:
    return f"{normalize_name(name)} {specialization} {year}"


def build_faculty_nickname(name: str) -> str:
    return f"{normalize_name(name)} BSEMC Faculty"


class StudentIntroductionModal(discord.ui.Modal, title="Student Introduction"):
    full_name = discord.ui.TextInput(
        label="Full Name",
        placeholder="John Doe",
        required=True,
        min_length=2,
        max_length=80,
    )
    specialization = discord.ui.TextInput(
        label="Specialization",
        placeholder="DAT or GD",
        required=True,
        min_length=2,
        max_length=40,
    )
    year = discord.ui.TextInput(
        label="Year",
        placeholder="1st Year, 2nd Year, 3rd Year, or 4th Year",
        required=True,
        min_length=1,
        max_length=20,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("This can only be used in a server.", ephemeral=True)
            return

        if not has_role(member, STUDENT_ROLE_NAME):
            await interaction.response.send_message(
                f"You need the **{STUDENT_ROLE_NAME}** role first.",
                ephemeral=True,
            )
            return

        specialization = normalize_specialization(self.specialization.value)
        year = normalize_year(self.year.value)
        if not specialization:
            await interaction.response.send_message("Specialization must be DAT or GD.", ephemeral=True)
            return
        if not year:
            await interaction.response.send_message(
                "Year must be 1st Year, 2nd Year, 3rd Year, or 4th Year.",
                ephemeral=True,
            )
            return

        nickname = build_student_nickname(self.full_name.value, specialization, year)
        if len(nickname) > MAX_NICKNAME_LENGTH:
            await interaction.response.send_message(
                f"Your nickname would be {len(nickname)} characters. Discord allows 32.\n"
                "Please use a shorter name so the complete nickname fits.",
                ephemeral=True,
            )
            return

        try:
            await member.edit(nick=nickname, reason="EM Bot student introduction")
            await add_role_if_missing(member, INTRODUCED_ROLE_NAME)
            await remove_role_if_present(member, UNINTRODUCED_ROLE_NAME)
        except discord.Forbidden:
            await interaction.response.send_message(
                "I couldn't update your nickname/roles. Check EM Bot's role position and permissions.",
                ephemeral=True,
            )
            return
        except discord.HTTPException:
            await interaction.response.send_message(
                "Discord rejected the update. Please try again.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"Your nickname is now **{nickname}**. You can now explore and chat in the server.",
            ephemeral=True,
        )

        cog = interaction.client.get_cog("Welcome")
        if cog:
            await cog.send_introduction_complete_welcome(member, nickname)


class FacultyIntroductionModal(discord.ui.Modal, title="Faculty/Moderator Introduction"):
    full_name = discord.ui.TextInput(
        label="Full Name",
        placeholder="John Doe",
        required=True,
        min_length=2,
        max_length=80,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("This can only be used in a server.", ephemeral=True)
            return

        if not has_role(member, FACULTY_ROLE_NAME):
            await interaction.response.send_message(
                f"You need the **{FACULTY_ROLE_NAME}** role first.",
                ephemeral=True,
            )
            return

        nickname = build_faculty_nickname(self.full_name.value)
        if len(nickname) > MAX_NICKNAME_LENGTH:
            await interaction.response.send_message(
                f"Your nickname would be {len(nickname)} characters. Discord allows 32.\n"
                "Please use a shorter name.",
                ephemeral=True,
            )
            return

        try:
            await member.edit(nick=nickname, reason="EM Bot faculty introduction")
            await add_role_if_missing(member, INTRODUCED_ROLE_NAME)
            await remove_role_if_present(member, UNINTRODUCED_ROLE_NAME)
        except discord.Forbidden:
            await interaction.response.send_message(
                "I couldn't update your nickname/roles. Check EM Bot's role position and permissions.",
                ephemeral=True,
            )
            return
        except discord.HTTPException:
            await interaction.response.send_message("Discord rejected the update.", ephemeral=True)
            return

        await interaction.response.send_message(
            f"Your nickname is now **{nickname}**. You can now explore and chat in the server.",
            ephemeral=True,
        )

        cog = interaction.client.get_cog("Welcome")
        if cog:
            await cog.send_introduction_complete_welcome(member, nickname)


class IntroductionView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Introduce Yourself",
        style=discord.ButtonStyle.primary,
        emoji="👋",
        custom_id="em:introduce",
    )
    async def introduce(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if INTRO_CHANNEL_ID and interaction.channel_id != INTRO_CHANNEL_ID:
            await interaction.response.send_message(
                "Please use the introduction channel.",
                ephemeral=True,
            )
            return

        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("Server members only.", ephemeral=True)
            return

        if has_role(member, FACULTY_ROLE_NAME):
            await interaction.response.send_modal(FacultyIntroductionModal())
        elif has_role(member, STUDENT_ROLE_NAME):
            await interaction.response.send_modal(StudentIntroductionModal())
        else:
            await interaction.response.send_message(
                "Your Student or Faculty/Moderator role has not been assigned yet.",
                ephemeral=True,
            )


class Introduction(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.bot.add_view(IntroductionView())

    @app_commands.command(name="setup", description="Open the introduction process.")
    async def setup(self, interaction: discord.Interaction) -> None:
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("Server members only.", ephemeral=True)
            return

        if has_role(member, INTRODUCED_ROLE_NAME):
            await interaction.response.send_message(
                "Your introduction is already complete.",
                ephemeral=True,
            )
            return

        view = IntroductionView()
        embed = discord.Embed(
            title="BSEMC Introduction",
            description=(
                "Complete your introduction to unlock normal server access.\n\n"
                "Your Student or Faculty/Moderator role determines which form you receive."
            ),
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="setup_intro", description="Post the public introduction panel.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_intro(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="BSEMC Introduction",
            description=(
                "Once your community role has been assigned, click **Introduce Yourself**.\n\n"
                "**Students:** Full Name + Specialization + Year\n"
                "**Faculty/Moderator:** Full Name"
            ),
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, view=IntroductionView())

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Introduction(bot))
