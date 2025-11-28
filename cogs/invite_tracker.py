import json
import os
import discord
from discord.ext import commands

DATA_PATH = "data/invites.json"


def load_data():
    if not os.path.exists(DATA_PATH):
        return {}
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


class InviteTracker(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.data = load_data()  # guild_id -> {code: uses}
        self.inviter_stats = {}  # guild_id -> {user_id: count}

    async def cache_guild_invites(self, guild: discord.Guild):
        invites = await guild.invites()
        self.data[str(guild.id)] = {inv.code: inv.uses or 0 for inv in invites}
        save_data(self.data)

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            try:
                await self.cache_guild_invites(guild)
            except discord.Forbidden:
                pass

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        try:
            await self.cache_guild_invites(guild)
        except discord.Forbidden:
            pass

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        before = self.data.get(str(guild.id), {})
        try:
            invites = await guild.invites()
        except discord.Forbidden:
            return

        used_invite = None
        for inv in invites:
            old_uses = before.get(inv.code, 0)
            if (inv.uses or 0) > old_uses:
                used_invite = inv
                break

        # update cache
        self.data[str(guild.id)] = {inv.code: inv.uses or 0 for inv in invites}
        save_data(self.data)

        if used_invite and used_invite.inviter:
            inviter = used_invite.inviter
            guild_stats = self.inviter_stats.setdefault(str(guild.id), {})
            guild_stats[str(inviter.id)] = guild_stats.get(str(inviter.id), 0) + 1

            channel = guild.system_channel or next(
                (c for c in guild.text_channels if c.permissions_for(guild.me).send_messages),
                None,
            )
            if channel:
                await channel.send(
                    f"{member.mention} was invited from {inviter.mention} "
                    f"(code `{used_invite.code}`, total uses: {used_invite.uses})."
                )

    @commands.command(name="invites")
    async def invites(self, ctx, member: discord.Member = None):
        """Shows how many invites a member has."""
        member = member or ctx.author
        guild_stats = self.inviter_stats.get(str(ctx.guild.id), {})
        count = guild_stats.get(str(member.id), 0)
        await ctx.send(f"{member.mention} has **{count}** invites.")


def setup(bot: commands.Bot):
    bot.add_cog(InviteTracker(bot))
