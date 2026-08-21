import discord
from discord.ext import commands

from .common import (
    INTRO_COMPLETE_CHANNEL_ID,
    UNINTRODUCED_ROLE_NAME,
    WELCOME_CHANNEL_ID,
    add_role_if_missing,
    get_text_channel,
    is_introduced,
)


class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return

        await add_role_if_missing(member, UNINTRODUCED_ROLE_NAME)

        channel = await get_text_channel(member.guild, WELCOME_CHANNEL_ID)
        if not channel:
            return

        embed = discord.Embed(
            title="Welcome to BSEMC!",
            description=(
                f"Welcome, {member.mention}!\n\n"
                "Please complete the community questions first. Once your role is assigned, "
                "use the **Introduce Yourself** button to set your nickname and unlock the server."
            ),
            color=discord.Color.blurple(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        await channel.send(embed=embed)

    async def send_introduction_complete_welcome(
        self,
        member: discord.Member,
        nickname: str,
    ) -> None:
        channel = await get_text_channel(member.guild, INTRO_COMPLETE_CHANNEL_ID)
        if not channel:
            return

        embed = discord.Embed(
            title="Welcome to BSEMC!",
            description=(
                f"Welcome, {member.mention}!\n\n"
                "Your introduction is complete, and you can now explore and participate in the server.\n\n"
                f"**Nickname:** `{nickname}`"
            ),
            color=discord.Color.green(),
        )
        await channel.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Welcome(bot))
