import json
import os
import discord
from discord.ext import commands
from datetime import datetime, timedelta
import asyncio

DATA_PATH = "data/guild_config.json"


def load_data():
    if not os.path.exists(DATA_PATH):
        return {}
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


class Automations(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.data = load_data()

    # ------ helpers ------
    def get_guild_cfg(self, guild_id: int):
        return self.data.setdefault(str(guild_id), {})

    def set_guild_cfg(self, guild_id: int, key: str, value):
        cfg = self.get_guild_cfg(guild_id)
        if value is None and key in cfg:
            del cfg[key]
        else:
            cfg[key] = value
        save_data(self.data)

    # ------ events ------
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        cfg = self.get_guild_cfg(member.guild.id)
        # welcome message
        channel_id = cfg.get("welcome_channel")
        msg_template = cfg.get("welcome_message")
        if channel_id and msg_template:
            channel = member.guild.get_channel(channel_id)
            if channel:
                txt = msg_template.replace("{member}", member.mention).replace(
                    "{server}", member.guild.name
                )
                await channel.send(txt)

        # autorole
        role_id = cfg.get("autorole_id")
        if role_id:
            role = member.guild.get_role(role_id)
            if role:
                try:
                    await member.add_roles(role, reason="Autorole (automated)")
                except discord.Forbidden:
                    pass

    # ------ commands: config ------
    @commands.group(name="auto", invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def auto_group(self, ctx):
        """Automation settings: welcome / autorole / etc."""
        await ctx.send(
            "Subcomenzi: `auto welcome`, `auto autorole`, `auto show`.\n"
            "Ex: `!auto welcome #general Bine ai venit, {member} pe {server}!`"
        )

    @auto_group.command(name="welcome")
    @commands.has_permissions(manage_guild=True)
    async def auto_welcome(
        self, ctx, channel: discord.TextChannel, *, message: str = None
    ):
        """Set the channel + welcome message."""
        if message is None:
            message = "Welcome, {member} on {server}!"
        self.set_guild_cfg(ctx.guild.id, "welcome_channel", channel.id)
        self.set_guild_cfg(ctx.guild.id, "welcome_message", message)
        await ctx.send(
            f"Welcome message set for {channel.mention}.\n"
            f"Message: `{message}` (use {member} / {server})"
        )

    @auto_group.command(name="autorole")
    @commands.has_permissions(manage_roles=True)
    async def auto_autorole(self, ctx, role: discord.Role = None):
        """Enables or disables autorole."""
        if role is None:
            self.set_guild_cfg(ctx.guild.id, "autorole_id", None)
            await ctx.send("Autorole disabled.")
        else:
            self.set_guild_cfg(ctx.guild.id, "autorole_id", role.id)
            await ctx.send(f"Autorole is set on role {role.mention}.")

    @auto_group.command(name="show")
    @commands.has_permissions(manage_guild=True)
    async def auto_show(self, ctx):
        """Show the current settings."""
        cfg = self.get_guild_cfg(ctx.guild.id)
        wc = cfg.get("welcome_channel")
        wm = cfg.get("welcome_message")
        ar = cfg.get("autorole_id")

        ch = ctx.guild.get_channel(wc) if wc else None
        rl = ctx.guild.get_role(ar) if ar else None

        await ctx.send(
            "**Automation settings:**\n"
            f"- Welcome channel: {ch.mention if ch else 'undefined'}\n"
            f"- Welcome message: `{wm}`\n"
            f"- Autorole: {rl.mention if rl else 'undefined'}"
        )

    # ------ simple remind command ------
    @commands.command(name="remind")
    async def remind(self, ctx, minutes: int, *, text: str):
        """
        Simple reminder: !remind 10 drink water
        """
        if minutes <= 0:
            return await ctx.send("Minutes must be > 0.")
        await ctx.send(
            f"Ok {ctx.author.mention}, i will remind you that after {minutes} minute(s). ⏰"
        )

        async def _task():
            await asyncio.sleep(minutes * 60)
            try:
                await ctx.send(
                    f"⏰ {ctx.author.mention} reminder: {text}",
                    allowed_mentions=discord.AllowedMentions(users=True),
                )
            except discord.Forbidden:
                pass

        self.bot.loop.create_task(_task())


def setup(bot: commands.Bot):
    bot.add_cog(Automations(bot))
