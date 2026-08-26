from __future__ import annotations

import os
from typing import Optional

import discord

FACULTY_ROLE_NAME = os.getenv("FACULTY_ROLE_NAME", "Faculty")
MODERATOR_ROLE_NAME = os.getenv("MODERATOR_ROLE_NAME", "Moderator")
PENDING_FACULTY_ROLE_NAME = os.getenv("PENDING_FACULTY_ROLE_NAME", "!Faculty")
EMC_FACULTY_ROLE_NAME = os.getenv("EMC_FACULTY_ROLE_NAME", "EMC Faculty")
STUDENT_ROLE_NAME = os.getenv("STUDENT_ROLE_NAME", "Student")
BISCAST_ROLE_NAME = os.getenv("BISCAST_ROLE_NAME", "BISCAST")
INTRODUCED_ROLE_NAME = os.getenv("INTRODUCED_ROLE_NAME", "Introduced")
UNINTRODUCED_ROLE_NAME = os.getenv("UNINTRODUCED_ROLE_NAME", "Unintroduced")

MOD_LOG_CHANNEL_ID = int(os.getenv("MOD_LOG_CHANNEL_ID", "0"))
WELCOME_CHANNEL_ID = int(os.getenv("WELCOME_CHANNEL_ID", "0"))
INTRO_COMPLETE_CHANNEL_ID = int(os.getenv("INTRO_COMPLETE_CHANNEL_ID", "0"))

def has_role(member: discord.Member, role_name: str) -> bool:
    return any(r.name.casefold() == role_name.casefold() for r in member.roles)

def is_faculty(member: discord.Member) -> bool:
    return has_role(member, FACULTY_ROLE_NAME)

def is_pending_faculty(member: discord.Member) -> bool:
    return has_role(member, PENDING_FACULTY_ROLE_NAME)

def is_emc_faculty(member: discord.Member) -> bool:
    return has_role(member, EMC_FACULTY_ROLE_NAME)

def is_moderator(member: discord.Member) -> bool:
    return has_role(member, MODERATOR_ROLE_NAME)

def is_staff(member: discord.Member) -> bool:
    return is_moderator(member) or is_emc_faculty(member)

def is_student(member: discord.Member) -> bool:
    return has_role(member, STUDENT_ROLE_NAME)

def is_introduced(member: discord.Member) -> bool:
    return has_role(member, INTRODUCED_ROLE_NAME)

async def get_text_channel(guild: discord.Guild, channel_id: int) -> Optional[discord.TextChannel]:
    if not channel_id:
        return None
    channel = guild.get_channel(channel_id)
    return channel if isinstance(channel, discord.TextChannel) else None

async def log_mod(guild: Optional[discord.Guild], content: str) -> None:
    if guild is None:
        return
    channel = await get_text_channel(guild, MOD_LOG_CHANNEL_ID)
    if channel:
        try:
            await channel.send(content)
        except (discord.Forbidden, discord.HTTPException):
            pass

async def add_role_if_missing(member: discord.Member, role_name: str, *, reason: str = "EM Bot") -> bool:
    role = discord.utils.get(member.guild.roles, name=role_name)
    if role is None:
        return False
    if role in member.roles:
        return True
    try:
        await member.add_roles(role, reason=reason)
        return True
    except (discord.Forbidden, discord.HTTPException):
        return False

async def remove_role_if_present(member: discord.Member, role_name: str, *, reason: str = "EM Bot") -> bool:
    role = discord.utils.get(member.guild.roles, name=role_name)
    if role is None or role not in member.roles:
        return True
    try:
        await member.remove_roles(role, reason=reason)
        return True
    except (discord.Forbidden, discord.HTTPException):
        return False
