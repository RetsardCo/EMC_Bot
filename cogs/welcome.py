import os

import discord
from discord.ext import commands

WELCOME_CHANNEL_ID = int(os.getenv("WELCOME_CHANNEL_ID", "0"))

class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        channel = member.guild.get_channel(WELCOME_CHANNEL_ID) if WELCOME_CHANNEL_ID else None
        if channel is None or not isinstance(channel, discord.TextChannel):
            return

        embed = discord.Embed(
            title="Welcome to the BSEMC Server!",
            description=(
                f"Welcome, {member.mention}!\n\n"
                "Please complete the introduction form so EM Bot can set your server nickname.\n"
                "Use the **Introduce Yourself** button in the introduction channel."
            ),
            color=discord.Color.blurple(),
        )
        await channel.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(Welcome(bot))
