import discord
from discord import app_commands
from discord.ext import commands

from .common import is_staff


def staff_only():
    async def predicate(interaction: discord.Interaction) -> bool:
        member = interaction.user
        return isinstance(member, discord.Member) and is_staff(member)

    return app_commands.check(predicate)


class AdminPanel(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=120)

    @discord.ui.button(label="Server Info", style=discord.ButtonStyle.secondary)
    async def server_info(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message(
                "Server only.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=guild.name,
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Members",
            value=str(guild.member_count or 0),
            inline=True,
        )
        embed.add_field(
            name="Channels",
            value=str(len(guild.channels)),
            inline=True,
        )
        embed.add_field(
            name="Roles",
            value=str(len(guild.roles)),
            inline=True,
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True,
        )

    @discord.ui.button(
        label="Panel Closed",
        style=discord.ButtonStyle.danger,
        disabled=True,
    )
    async def placeholder(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        pass


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="setup_panel",
        description="Open the EM Bot admin panel.",
    )
    @staff_only()
    async def setup_panel(
        self,
        interaction: discord.Interaction,
    ) -> None:
        embed = discord.Embed(
            title="EM Bot Admin Panel",
            description=(
                "Access is limited to the **Faculty** and **Moderator** roles.\n"
                "Use the bot's dedicated moderation/admin commands "
                "from the slash-command menu."
            ),
            color=discord.Color.dark_teal(),
        )

        await interaction.response.send_message(
            embed=embed,
            view=AdminPanel(),
            ephemeral=True,
        )

    @app_commands.command(
        name="nick",
        description="Manually change a member's nickname.",
    )
    @app_commands.checks.has_permissions(manage_nicknames=True)
    @staff_only()
    async def nick(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        nickname: str,
    ) -> None:
        nickname = nickname[:32]

        try:
            await member.edit(
                nick=nickname,
                reason=f"Manual nickname change by {interaction.user}",
            )
            await interaction.response.send_message(
                f"Changed **{member}** to `{nickname}`.",
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "I can't change that nickname.",
                ephemeral=True,
            )
        except discord.HTTPException:
            await interaction.response.send_message(
                "Discord rejected that nickname change.",
                ephemeral=True,
            )

    @app_commands.command(
        name="announce",
        description="Post an announcement.",
    )
    @staff_only()
    async def announce(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        message: str,
    ) -> None:
        embed = discord.Embed(
            title="Announcement",
            description=message,
            color=discord.Color.gold(),
        )
        embed.set_footer(
            text=f"Posted by {interaction.user.display_name}"
        )

        try:
            await channel.send(embed=embed)
            await interaction.response.send_message(
                f"Announcement posted in {channel.mention}.",
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "I can't send messages in that channel.",
                ephemeral=True,
            )
        except discord.HTTPException:
            await interaction.response.send_message(
                "Discord rejected the announcement.",
                ephemeral=True,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Admin(bot))
