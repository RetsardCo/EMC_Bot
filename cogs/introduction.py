from __future__ import annotations

import os
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from .common import (
    BISCAST_ROLE_NAME,
    FACULTY_ROLE_NAME,
    EMC_FACULTY_ROLE_NAME,
    INTRODUCED_ROLE_NAME,
    PENDING_FACULTY_ROLE_NAME,
    STUDENT_ROLE_NAME,
    UNINTRODUCED_ROLE_NAME,
    has_role,
    is_introduced,
    remove_role_if_present,
)

INTRO_CHANNEL_ID = int(os.getenv("INTRO_CHANNEL_ID", "0"))
MAX_NICKNAME_LENGTH = 32

def year_label(number: int) -> str:
    suffix = (
        "st" if number == 1
        else "nd" if number == 2
        else "rd" if number == 3
        else "th"
    )
    return f"{number}{suffix} Year"


YEAR_ROLE_NAMES = {
    "DAT": {
        year_label(n): f"DAT-{year_label(n).replace(' ', '-')}"
        for n in range(1, 5)
    },
    "GD": {
        year_label(n): f"GD-{year_label(n).replace(' ', '-')}"
        for n in range(1, 5)
    },
}
ALL_YEAR_ROLE_NAMES = {x for d in YEAR_ROLE_NAMES.values() for x in d.values()}

def get_role(guild: discord.Guild, name: str) -> Optional[discord.Role]:
    return discord.utils.get(guild.roles, name=name)

def normalize_name(name: str) -> str:
    name = " ".join(name.split()).strip()
    return name[:1].upper() + name[1:] if name else ""

def normalize_specialization(value: str) -> Optional[str]:
    return {
        "dat": "DAT",
        "digital animation technology": "DAT",
        "gd": "GD",
        "game development": "GD",
    }.get(" ".join(value.split()).strip().casefold())

def normalize_year(value: str) -> Optional[str]:
    return {
        "1": "1st Year", "1st": "1st Year", "1st year": "1st Year",
        "first": "1st Year", "first year": "1st Year",
        "2": "2nd Year", "2nd": "2nd Year", "2nd year": "2nd Year",
        "second": "2nd Year", "second year": "2nd Year",
        "3": "3rd Year", "3rd": "3rd Year", "3rd year": "3rd Year",
        "third": "3rd Year", "third year": "3rd Year",
        "4": "4th Year", "4th": "4th Year", "4th year": "4th Year",
        "fourth": "4th Year", "fourth year": "4th Year",
    }.get(" ".join(value.split()).strip().casefold())

def build_nickname(name: str, status: str, specialization: str = "", year: str = "") -> str:
    clean = normalize_name(name)
    return f"{clean} Faculty" if status == "faculty" else f"{clean} {specialization} {year}"

def role_check(guild: discord.Guild, role_names: list[str]) -> tuple[bool, str]:
    me = guild.me
    if me is None:
        return False, "I couldn't verify EM Bot's role position."
    if not me.guild_permissions.manage_roles:
        return False, "EM Bot needs **Manage Roles** permission."
    for name in role_names:
        role = get_role(guild, name)
        if role is None:
            return False, f"I couldn't find the **{name}** role."
        if role >= me.top_role:
            return False, f"EM Bot's role must be above **{name}**."
    return True, ""

def nickname_check(member: discord.Member) -> tuple[bool, str]:
    me = member.guild.me
    if me is None:
        return False, "I couldn't verify EM Bot's member permissions."
    if not me.guild_permissions.manage_nicknames:
        return False, "EM Bot needs **Manage Nicknames** permission."
    if member == member.guild.owner:
        return False, "Discord does not allow bots to change the server owner's nickname."
    if member.top_role >= me.top_role:
        return False, "EM Bot's role must be above your highest role to change your nickname."
    return True, ""

async def assign_student_roles(member: discord.Member, specialization: str, year: str) -> tuple[bool, str]:
    year_name = YEAR_ROLE_NAMES.get(specialization, {}).get(year)
    if not year_name:
        return False, "I couldn't determine the correct year role."
    ok, err = role_check(member.guild, [BISCAST_ROLE_NAME, STUDENT_ROLE_NAME, year_name, INTRODUCED_ROLE_NAME, UNINTRODUCED_ROLE_NAME])
    if not ok:
        return False, err
    roles = [get_role(member.guild, n) for n in (BISCAST_ROLE_NAME, STUDENT_ROLE_NAME, year_name)]
    old_years = [r for r in member.roles if r.name in ALL_YEAR_ROLE_NAMES and r.name != year_name]
    try:
        if old_years:
            await member.remove_roles(*old_years, reason="EM Bot onboarding year normalization")
        await member.add_roles(*[r for r in roles if r], reason="EM Bot student onboarding")
        intro = get_role(member.guild, INTRODUCED_ROLE_NAME)
        if intro:
            await member.add_roles(intro, reason="EM Bot onboarding")
        await remove_role_if_present(member, UNINTRODUCED_ROLE_NAME, reason="EM Bot onboarding")
        return True, ""
    except (discord.Forbidden, discord.HTTPException):
        return False, "Discord prevented EM Bot from assigning the student roles. Check Manage Roles and role hierarchy."

async def finalize_faculty(member: discord.Member) -> tuple[bool, str]:
    ok, err = role_check(member.guild, [PENDING_FACULTY_ROLE_NAME, FACULTY_ROLE_NAME, INTRODUCED_ROLE_NAME, UNINTRODUCED_ROLE_NAME])
    if not ok:
        return False, err
    pending = get_role(member.guild, PENDING_FACULTY_ROLE_NAME)
    faculty = get_role(member.guild, FACULTY_ROLE_NAME)
    introduced = get_role(member.guild, INTRODUCED_ROLE_NAME)
    try:
        await member.add_roles(faculty, introduced, reason="EM Bot verified faculty onboarding")
        await member.remove_roles(pending, reason="EM Bot verified faculty onboarding")
        await remove_role_if_present(member, UNINTRODUCED_ROLE_NAME, reason="EM Bot onboarding")
        refreshed = member.guild.get_member(member.id)
        if refreshed and not has_role(refreshed, FACULTY_ROLE_NAME):
            return False, "I couldn't verify the Faculty role after assigning it."
        return True, ""
    except (discord.Forbidden, discord.HTTPException):
        return False, "Discord prevented the !Faculty → Faculty role transition. Check Manage Roles and role hierarchy."

async def apply_nickname(member: discord.Member, nickname: str, *, reason: str) -> tuple[bool, str]:
    ok, err = nickname_check(member)
    if not ok:
        return False, err
    before = member.nick
    try:
        await member.edit(nick=nickname, reason=reason)
    except discord.Forbidden:
        return False, "Discord refused the nickname change. Check Manage Nicknames and role hierarchy."
    except discord.HTTPException:
        return False, "Discord rejected the nickname change."
    # Verify the change actually stuck.
    refreshed = member.guild.get_member(member.id) or member
    if refreshed.nick != nickname:
        try:
            fetched = await member.guild.fetch_member(member.id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            fetched = refreshed
        if fetched.nick != nickname:
            try:
                await member.edit(nick=nickname, reason=reason + " (retry)")
            except (discord.Forbidden, discord.HTTPException):
                pass
            refreshed = member.guild.get_member(member.id) or member
            if refreshed.nick != nickname:
                return False, "The nickname change was not confirmed by Discord. Please check EM Bot's role position and Manage Nicknames permission."
    return True, ""

async def safe_followup(
    interaction: discord.Interaction,
    content: str,
) -> None:
    try:
        if interaction.response.is_done():
            await interaction.followup.send(content, ephemeral=True)
        else:
            await interaction.response.send_message(content, ephemeral=True)
    except (discord.NotFound, discord.HTTPException):
        pass


class StudentIntroductionModal(discord.ui.Modal, title="Student Introduction"):
    full_name = discord.ui.TextInput(label="Full Name", placeholder="Juan Dela Cruz", required=True, min_length=2, max_length=80)
    specialization = discord.ui.TextInput(label="Specialization", placeholder="DAT or GD", required=True, min_length=2, max_length=32)
    year = discord.ui.TextInput(label="Year", placeholder="1st Year, 2nd Year, 3rd Year, or 4th Year", required=True, min_length=1, max_length=20)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.HTTPException:
            return

        member = interaction.user
        if not isinstance(member, discord.Member):
            await safe_followup(
                interaction,
                "This form can only be used inside the server.",
            )
            return

        if not has_role(member, STUDENT_ROLE_NAME):
            await safe_followup(
                interaction,
                f"You need the **{STUDENT_ROLE_NAME}** role to use the student form.",
            )
            return

        if is_introduced(member):
            await safe_followup(
                interaction,
                "You have already completed your introduction. "
                "Future nickname changes must be done manually by Moderator or EMC Faculty staff.",
            )
            return

        specialization = normalize_specialization(self.specialization.value)
        year = normalize_year(self.year.value)

        if not specialization:
            await safe_followup(
                interaction,
                "Specialization must be **DAT** or **GD**.",
            )
            return

        if not year:
            await safe_followup(
                interaction,
                "Year must be **1st Year**, **2nd Year**, **3rd Year**, or **4th Year**.",
            )
            return

        nickname = build_nickname(
            self.full_name.value,
            "student",
            specialization,
            year,
        )

        if len(nickname) > MAX_NICKNAME_LENGTH:
            await safe_followup(
                interaction,
                f"Your nickname is {len(nickname)} characters. "
                f"Discord allows a maximum of {MAX_NICKNAME_LENGTH}. "
                "Please enter a shorter name.",
            )
            return

        ok, err = await apply_nickname(
            member,
            nickname,
            reason="EM Bot student introduction",
        )
        if not ok:
            await safe_followup(interaction, f"1. {err}")
            return

        ok, err = await assign_student_roles(
            member,
            specialization,
            year,
        )
        if not ok:
            await safe_followup(
                interaction,
                f"1. Your nickname was changed to **{nickname}**.\n\n"
                f"2. Onboarding could not finish.\n\n"
                f"3. {err}",
            )
            return

        await safe_followup(
            interaction,
            f"1. Your nickname is now **{nickname}**.\n\n"
            f"2. You received **{BISCAST_ROLE_NAME}**, **{STUDENT_ROLE_NAME}**, "
            f"and **{YEAR_ROLE_NAMES[specialization][year]}**.\n\n"
            "3. Your introduction is complete.",
        )

class FacultyIntroductionModal(discord.ui.Modal, title="Faculty Introduction"):
    full_name = discord.ui.TextInput(label="Full Name", placeholder="Juan Dela Cruz", required=True, min_length=2, max_length=80)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.HTTPException:
            return

        member = interaction.user
        if not isinstance(member, discord.Member):
            await safe_followup(
                interaction,
                "This form can only be used inside the server.",
            )
            return

        if not has_role(member, PENDING_FACULTY_ROLE_NAME):
            await safe_followup(
                interaction,
                f"You need the **{PENDING_FACULTY_ROLE_NAME}** role. "
                "It is assigned manually after faculty verification.",
            )
            return

        if is_introduced(member):
            await safe_followup(
                interaction,
                "You have already completed your introduction. "
                "Future nickname changes must be done manually by Moderator or EMC Faculty staff.",
            )
            return

        nickname = build_nickname(
            self.full_name.value,
            "faculty",
        )
        if len(nickname) > MAX_NICKNAME_LENGTH:
            await safe_followup(
                interaction,
                "Please enter a shorter name.",
            )
            return

        ok, err = await apply_nickname(
            member,
            nickname,
            reason="EM Bot faculty introduction",
        )
        if not ok:
            await safe_followup(interaction, f"1. {err}")
            return

        ok, err = await finalize_faculty(member)
        if not ok:
            await safe_followup(
                interaction,
                f"1. Nickname changed to **{nickname}**, but faculty role completion failed.\n\n"
                f"2. {err}",
            )
            return

        await safe_followup(
            interaction,
            f"1. Your nickname is now **{nickname}**.\n\n"
            f"2. **{PENDING_FACULTY_ROLE_NAME}** was replaced with **{FACULTY_ROLE_NAME}**.\n\n"
            f"3. **{EMC_FACULTY_ROLE_NAME}** is never assigned automatically; "
            "a trusted administrator must promote you manually.\n\n"
            "4. Your introduction is complete.",
        )

class IntroductionView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Introduce Yourself", style=discord.ButtonStyle.primary, emoji="👋", custom_id="em_bot:introduce")
    async def introduce(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("Server only.", ephemeral=True)
            return
        if INTRO_CHANNEL_ID and interaction.channel_id != INTRO_CHANNEL_ID:
            await interaction.response.send_message("Please use the introduction channel.", ephemeral=True)
            return
        if is_introduced(member):
            await interaction.response.send_message("You have already completed your introduction. Future nickname changes must be done manually by Moderator or EMC Faculty staff.", ephemeral=True)
            return
        if has_role(member, PENDING_FACULTY_ROLE_NAME):
            await interaction.response.send_modal(FacultyIntroductionModal())
        elif has_role(member, STUDENT_ROLE_NAME):
            await interaction.response.send_modal(StudentIntroductionModal())
        else:
            await interaction.response.send_message(
                f"You need **{STUDENT_ROLE_NAME}** or manually verified **{PENDING_FACULTY_ROLE_NAME}**.",
                ephemeral=True,
            )

class Introduction(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(IntroductionView())

    @app_commands.command(name="setup", description="Open your introduction process.")
    async def setup(self, interaction: discord.Interaction) -> None:
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("Server only.", ephemeral=True)
            return
        if INTRO_CHANNEL_ID and interaction.channel_id != INTRO_CHANNEL_ID:
            await interaction.response.send_message("Please use **/setup** in the introduction channel.", ephemeral=True)
            return
        if is_introduced(member):
            await interaction.response.send_message("You have already completed your introduction. Future nickname changes must be done manually by Moderator or EMC Faculty staff.", ephemeral=True)
            return
        if has_role(member, PENDING_FACULTY_ROLE_NAME):
            await interaction.response.send_modal(FacultyIntroductionModal())
        elif has_role(member, STUDENT_ROLE_NAME):
            await interaction.response.send_modal(StudentIntroductionModal())
        else:
            await interaction.response.send_message(
                f"1. I couldn't identify your setup role.\n\n"
                f"2. Students need **{STUDENT_ROLE_NAME}**.\n\n"
                f"3. Verified faculty members need the manually assigned **{PENDING_FACULTY_ROLE_NAME}** role.",
                ephemeral=True,
            )

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Introduction(bot))
