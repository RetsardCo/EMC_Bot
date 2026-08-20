import os
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

STUDENT_ROLE_NAME = os.getenv("STUDENT_ROLE_NAME", "Student")
FACULTY_ROLE_NAME = os.getenv("FACULTY_ROLE_NAME", "Faculty")

INTRO_CHANNEL_ID = int(os.getenv("INTRO_CHANNEL_ID", "0"))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))

MAX_NICKNAME_LENGTH = 32


# -----------------------------
# Helpers
# -----------------------------

def has_role(member: discord.Member, role_name: str) -> bool:
    return any(role.name.casefold() == role_name.casefold() for role in member.roles)


def get_member_status(member: discord.Member) -> Optional[str]:
    # Faculty takes precedence if a member somehow has both roles.
    if has_role(member, FACULTY_ROLE_NAME):
        return "faculty"
    if has_role(member, STUDENT_ROLE_NAME):
        return "student"
    return None


def normalize_name(name: str) -> str:
    """Normalize whitespace and capitalize the first character of the name."""
    name = " ".join(name.split()).strip()

    if not name:
        return ""

    return name[0].upper() + name[1:]


def normalize_specialization(value: str) -> Optional[str]:
    value = " ".join(value.split()).strip().casefold()

    aliases = {
        "dat": "DAT",
        "digital animation technology": "DAT",
        "gd": "GD",
        "game development": "GD",
    }

    return aliases.get(value)


def normalize_year(value: str) -> Optional[str]:
    value = " ".join(value.split()).strip().casefold()

    aliases = {
        "1": "1st Year",
        "1st": "1st Year",
        "1st year": "1st Year",
        "first": "1st Year",
        "first year": "1st Year",
        "2": "2nd Year",
        "2nd": "2nd Year",
        "2nd year": "2nd Year",
        "second": "2nd Year",
        "second year": "2nd Year",
        "3": "3rd Year",
        "3rd": "3rd Year",
        "3rd year": "3rd Year",
        "third": "3rd Year",
        "third year": "3rd Year",
        "4": "4th Year",
        "4th": "4th Year",
        "4th year": "4th Year",
        "fourth": "4th Year",
        "fourth year": "4th Year",
    }

    return aliases.get(value)


def build_nickname(
    name: str,
    status: str,
    specialization: str = "",
    year: str = "",
) -> str:
    clean_name = normalize_name(name)

    if status == "faculty":
        return f"{clean_name} BSEMC Faculty"

    return f"{clean_name} BSEMC {specialization} {year}"


def nickname_too_long_message(nickname: str) -> str:
    return (
        f"Your generated nickname is **{len(nickname)} characters**, "
        f"but Discord allows a maximum of **{MAX_NICKNAME_LENGTH} characters**.\n\n"
        "Please enter a shorter name so the complete nickname can fit."
    )


async def log_change(
    guild: Optional[discord.Guild],
    member: discord.Member,
    nickname: str,
    status: str,
) -> None:
    if guild is None or not LOG_CHANNEL_ID:
        return

    channel = guild.get_channel(LOG_CHANNEL_ID)
    if not isinstance(channel, discord.TextChannel):
        return

    try:
        await channel.send(
            f"✏️ **Nickname Updated** | {member.mention} → `{nickname}` ({status})"
        )
    except (discord.Forbidden, discord.HTTPException):
        # Logging should never break a successful nickname update.
        pass


# -----------------------------
# Student form
# -----------------------------

class StudentIntroductionModal(discord.ui.Modal, title="Student Introduction"):
    full_name = discord.ui.TextInput(
        label="Full Name",
        placeholder="Juan Dela Cruz",
        required=True,
        min_length=2,
        max_length=80,
    )

    specialization = discord.ui.TextInput(
        label="Specialization",
        placeholder="DAT or GD",
        required=True,
        min_length=2,
        max_length=32,
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
            await interaction.response.send_message(
                "This form can only be used inside the server.",
                ephemeral=True,
            )
            return

        if not has_role(member, STUDENT_ROLE_NAME):
            await interaction.response.send_message(
                f"You need the **{STUDENT_ROLE_NAME}** role to use the student form.",
                ephemeral=True,
            )
            return

        specialization = normalize_specialization(self.specialization.value)
        if specialization is None:
            await interaction.response.send_message(
                "Specialization must be **DAT** (Digital Animation Technology) "
                "or **GD** (Game Development).",
                ephemeral=True,
            )
            return

        normalized_year = normalize_year(self.year.value)
        if normalized_year is None:
            await interaction.response.send_message(
                "Year must be **1st Year**, **2nd Year**, **3rd Year**, or **4th Year**.",
                ephemeral=True,
            )
            return

        nickname = build_nickname(
            self.full_name.value,
            "student",
            specialization,
            normalized_year,
        )

        if not nickname:
            await interaction.response.send_message(
                "Please enter a valid name.",
                ephemeral=True,
            )
            return

        # Never silently cut off the nickname. This prevents
        # values such as "4th Yea" from being created.
        if len(nickname) > MAX_NICKNAME_LENGTH:
            await interaction.response.send_message(
                nickname_too_long_message(nickname),
                ephemeral=True,
            )
            return

        try:
            await member.edit(
                nick=nickname,
                reason="EM Bot student introduction",
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "I couldn't change your nickname. Please make sure EM Bot's role "
                "is above your role and that it has **Manage Nicknames** permission.",
                ephemeral=True,
            )
            return
        except discord.HTTPException:
            await interaction.response.send_message(
                "Discord rejected the nickname change. Please try again.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"Your nickname has been updated to **{nickname}**.",
            ephemeral=True,
        )
        await log_change(interaction.guild, member, nickname, "Student")


# -----------------------------
# Faculty form
# -----------------------------

class FacultyIntroductionModal(discord.ui.Modal, title="Faculty Introduction"):
    full_name = discord.ui.TextInput(
        label="Full Name",
        placeholder="Juan Dela Cruz",
        required=True,
        min_length=2,
        max_length=80,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        member = interaction.user

        if not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "This form can only be used inside the server.",
                ephemeral=True,
            )
            return

        if not has_role(member, FACULTY_ROLE_NAME):
            await interaction.response.send_message(
                f"You need the **{FACULTY_ROLE_NAME}** role to use the faculty form.",
                ephemeral=True,
            )
            return

        nickname = build_nickname(self.full_name.value, "faculty")

        if not nickname:
            await interaction.response.send_message(
                "Please enter a valid name.",
                ephemeral=True,
            )
            return

        if len(nickname) > MAX_NICKNAME_LENGTH:
            await interaction.response.send_message(
                nickname_too_long_message(nickname),
                ephemeral=True,
            )
            return

        try:
            await member.edit(
                nick=nickname,
                reason="EM Bot faculty introduction",
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "I couldn't change your nickname. Please make sure EM Bot's role "
                "is above your role and that it has **Manage Nicknames** permission.",
                ephemeral=True,
            )
            return
        except discord.HTTPException:
            await interaction.response.send_message(
                "Discord rejected the nickname change. Please try again.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"Your nickname has been updated to **{nickname}**.",
            ephemeral=True,
        )
        await log_change(interaction.guild, member, nickname, "Faculty")


# -----------------------------
# Introduction button
# -----------------------------

class IntroductionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Introduce Yourself",
        style=discord.ButtonStyle.primary,
        emoji="👋",
        custom_id="em_bot:introduce",
    )
    async def introduce(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        member = interaction.user

        if not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "This can only be used inside the server.",
                ephemeral=True,
            )
            return

        if INTRO_CHANNEL_ID and interaction.channel_id != INTRO_CHANNEL_ID:
            await interaction.response.send_message(
                "Please use the introduction channel for this form.",
                ephemeral=True,
            )
            return

        status = get_member_status(member)

        if status == "student":
            await interaction.response.send_modal(StudentIntroductionModal())
        elif status == "faculty":
            await interaction.response.send_modal(FacultyIntroductionModal())
        else:
            await interaction.response.send_message(
                f"I couldn't identify your role. Please make sure you have the "
                f"**{STUDENT_ROLE_NAME}** or **{FACULTY_ROLE_NAME}** role.",
                ephemeral=True,
            )


class Introduction(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # Register the persistent button after every restart.
        self.bot.add_view(IntroductionView())

    @app_commands.command(
        name="setup_intro",
        description="Post the EM Bot introduction panel.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_intro(self, interaction: discord.Interaction) -> None:
        channel = interaction.channel

        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "Use this command in a text channel.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="BSEMC Introduction",
            description=(
                "Welcome to the BSEMC community!\n\n"
                "Click the button below to introduce yourself.\n"
                "Your existing **Student** or **Faculty** role determines which "
                "form you receive.\n\n"
                "**Students:** Name, specialization, and year\n"
                "**Faculty:** Name only"
            ),
            color=discord.Color.blurple(),
        )

        await interaction.response.send_message(
            embed=embed,
            view=IntroductionView(),
        )

    @setup_intro.error
    async def setup_intro_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.errors.MissingPermissions):
            await interaction.response.send_message(
                "You need **Manage Server** permission to use this command.",
                ephemeral=True,
            )
            return

        raise error


async def setup(bot: commands.Bot):
    await bot.add_cog(Introduction(bot))
