import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing from .env")

# Development/test guilds.
# Put both server IDs in .env like:
# TEST_GUILD_IDS=1509065648788213790,SECOND_SERVER_ID
_raw_test_guild_ids = os.getenv("TEST_GUILD_IDS", "1509065648788213790")
TEST_GUILD_IDS = [
    int(value.strip())
    for value in _raw_test_guild_ids.split(",")
    if value.strip().isdigit()
]

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("em-bot")


class EMBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,
        )

        logger.info(
            "Discord intents: members=%s message_content=%s",
            intents.members,
            intents.message_content,
        )

    async def setup_hook(self) -> None:
        extensions = (
            "cogs.welcome",
            "cogs.introduction",
            "cogs.moderation",
            "cogs.admin",
            "cogs.polls",
            "cogs.automod",
            "cogs.ai",
            "cogs.help",
            "cogs.feedback",
            "cogs.knowledge",
        )

        for extension in extensions:
            try:
                await self.load_extension(extension)
                logger.info("Loaded %s", extension)
            except Exception:
                logger.exception("Failed to load %s", extension)

        # -----------------------------------------------------------
        # DEVELOPMENT SYNC
        #
        # Commands are copied to each test guild so updates appear
        # immediately during development.
        # -----------------------------------------------------------
        for guild_id in TEST_GUILD_IDS:
            guild = discord.Object(id=guild_id)

            try:
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)

                logger.info(
                    "Synced %d command(s) to guild %s",
                    len(synced),
                    guild_id,
                )

                for command in synced:
                    logger.info("  /%s", command.name)

            except Exception:
                logger.exception(
                    "Failed to sync commands to guild %s",
                    guild_id,
                )

        # -----------------------------------------------------------
        # REMOVE GLOBAL COMMAND DUPLICATES
        #
        # Older versions of EM Bot created global commands. Those
        # global commands can appear alongside the guild commands.
        # We keep the guild commands for development and remove the
        # global copies.
        # -----------------------------------------------------------
        try:
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
            logger.info("Cleared old global application commands.")
        except Exception:
            logger.exception("Failed to clear global application commands.")

    async def on_ready(self) -> None:
        logger.info(
            "Logged in as %s (%s)",
            self.user,
            self.user.id,
        )
        logger.info(
            "Connected to %d server(s).",
            len(self.guilds),
        )

        for guild in self.guilds:
            logger.info(
                "  - %s (%s)",
                guild.name,
                guild.id,
            )
            logger.info(
                "    system_channel=%s",
                getattr(guild.system_channel, "id", None),
            )


bot = EMBot()


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: discord.app_commands.AppCommandError,
) -> None:
    if isinstance(error, discord.app_commands.errors.MissingPermissions):
        message = "You do not have the Discord permissions required for this command."
    elif isinstance(error, discord.app_commands.errors.MissingRole):
        message = "You do not have the required server role for this command."
    elif isinstance(error, discord.app_commands.errors.CommandOnCooldown):
        message = (
            f"Please wait {error.retry_after:.1f} seconds "
            "before trying again."
        )
    else:
        logger.exception("Application command error", exc_info=error)
        message = (
            "Something went wrong while running that command. "
            "Check the EM Bot console for details."
        )

    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        logger.exception("Failed to send application-command error response.")


if __name__ == "__main__":
    bot.run(TOKEN)
