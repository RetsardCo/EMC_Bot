import os
import logging
from dotenv import load_dotenv

import discord
from discord.ext import commands

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing. Put it in your .env file.")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

class EMBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,
        )

    async def setup_hook(self):
        extensions = [
            "cogs.welcome",
            "cogs.introduction",
            "cogs.moderation",
            "cogs.admin",
        ]

        for extension in extensions:
            await self.load_extension(extension)
            logging.info("Loaded %s", extension)

        # Global slash-command sync.
        synced = await self.tree.sync()
        logging.info("Synced %d application command(s).", len(synced))

    async def on_ready(self):
        logging.info("Logged in as %s (ID: %s)", self.user, self.user.id)
        logging.info("Connected to %d server(s).", len(self.guilds))

bot = EMBot()

@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    if isinstance(error, commands.CommandNotFound):
        return
    logging.exception("Command error", exc_info=error)

bot.run(TOKEN)
