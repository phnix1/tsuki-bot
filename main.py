import json
import os
import discord
from discord.ext import commands

class CustomHelp(commands.MinimalHelpCommand):
    """Help command cu embed-uri drăguțe."""

    EMOJIS = {
        "Automations": "⚙️",
        "CustomCommands": "💬",
        "InviteTracker": "✉️",
        "Moderation": "🛡️",
        "Music": "🎵",
        "Ticketing": "🎫",
        "No Category": "📦",
    }

    async def send_bot_help(self, mapping):
        ctx = self.context
        prefix = ctx.clean_prefix

        embed = discord.Embed(
            title="Tsuki • Help",
            description=(
                f"Prefix: `{prefix}`\n"
                f"Use `{prefix}help <command>` or `{prefix}help <category>` "
                f"for more details.\n\n"
                "Available commands:"
            ),
            color=0x8A2BE2,
        )
        avatar_url = getattr(ctx.author.display_avatar, "url", None)
        embed.set_footer(text=f"Requested by {ctx.author}", icon_url=avatar_url)

        for cog, commands_list in mapping.items():
            filtered = await self.filter_commands(commands_list, sort=True)
            if not filtered:
                continue

            cog_name = cog.qualified_name if cog else "No Category"
            emoji = self.EMOJIS.get(cog_name, "•")

            value_lines = []
            for command in filtered:
                # command.short_doc = primul rand din docstring / help
                desc = command.short_doc or "No description"
                value_lines.append(f"`{prefix}{command.name}` – {desc}")

            value = "\n".join(value_lines)
            embed.add_field(
                name=f"{emoji} {cog_name}",
                value=value,
                inline=False,
            )

        dest = self.get_destination()
        await dest.send(embed=embed)

    async def send_cog_help(self, cog):
        ctx = self.context
        prefix = ctx.clean_prefix
        emoji = self.EMOJIS.get(cog.qualified_name, "•")

        embed = discord.Embed(
            title=f"{emoji} {cog.qualified_name}",
            description=cog.__doc__ or "No description.",
            color=0x8A2BE2,
        )

        filtered = await self.filter_commands(cog.get_commands(), sort=True)
        if not filtered:
            embed.add_field(name="Commands", value="There's no commands in this category.")
        else:
            lines = [
                f"`{prefix}{cmd.name}` – {cmd.short_doc or 'No description'}"
                for cmd in filtered
            ]
            embed.add_field(name="Commands", value="\n".join(lines), inline=False)

        await self.get_destination().send(embed=embed)

    async def send_command_help(self, command):
        ctx = self.context
        prefix = ctx.clean_prefix

        embed = discord.Embed(
            title=f"Comanda: {prefix}{command.qualified_name}",
            description=command.help or command.short_doc or "No description.",
            color=0x8A2BE2,
        )

        if command.aliases:
            embed.add_field(
                name="Aliases",
                value=", ".join(f"`{prefix}{a}`" for a in command.aliases),
                inline=False,
            )

        signature = self.get_command_signature(command)
        embed.add_field(name="Syntax", value=f"`{signature}`", inline=False)

        await self.get_destination().send(embed=embed)

    async def send_group_help(self, group):
        # for group commands (ex: ticket, cc)
        ctx = self.context
        prefix = ctx.clean_prefix

        embed = discord.Embed(
            title=f"Group: {prefix}{group.qualified_name}",
            description=group.help or "No description.",
            color=0x8A2BE2,
        )

        filtered = await self.filter_commands(group.commands, sort=True)
        if filtered:
            lines = [
                f"`{prefix}{cmd.qualified_name}` – {cmd.short_doc or 'No description.'}"
                for cmd in filtered
            ]
            embed.add_field(name="Subcommands", value="\n".join(lines), inline=False)

        await self.get_destination().send(embed=embed)


# =========== CONFIG LOADING ===========
CONFIG_PATH = "config.json"

if not os.path.exists(CONFIG_PATH):
    raise FileNotFoundError(
        "Can't find config.json. Copy config.example.json like config.json and fill in bot token."
    )

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

TOKEN = CONFIG["token"]
PREFIX = CONFIG.get("prefix", "!")


# =========== BOT SETUP ================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)
bot.help_command = CustomHelp()
bot.help_command.cog = None  # to show from above

initial_extensions = [
    "cogs.moderation",
    "cogs.automations",
    "cogs.custom_commands",
    "cogs.invite_tracker",
    "cogs.ticketing",
    "cogs.music",
]


@bot.event
async def on_ready():
    activity = discord.Game(name="da-mi-ai muie doamne")
    await bot.change_presence(status=discord.Status.online, activity=activity)

    print(f"Connected as {bot.user} (ID: {bot.user.id})")
    print("Servers:")
    for g in bot.guilds:
        print(f" - {g.name} ({g.id})")
    print("-----")



@bot.command(name="reload", hidden=True)
@commands.is_owner()
async def reload_cogs(ctx):
    """Reload all cogs (owner only)."""
    msgs = []
    for ext in initial_extensions:
        try:
            bot.reload_extension(ext)  # no await
            msgs.append(f"✅ {ext}")
        except Exception as e:
            msgs.append(f"❌ {ext} – {e}")
    await ctx.send("\n".join(msgs))


# === before run ===
for ext in initial_extensions:
    try:
        bot.load_extension(ext)  # no await
        print(f"Loaded {ext}")
    except Exception as e:
        print(f"Failed to load {ext}: {e}")

bot.run('DISCORD_TOKEN')
