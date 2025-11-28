import discord
from discord.ext import commands
from datetime import timedelta

BANNED_WORDS = ["nigga", "bitch", "nigger", "autistic", "retarded"]


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.user_message_times = {}

    # --------- Filter + anti-spam ----------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        content_lower = message.content.lower()

        # word filter
        if any(bad in content_lower for bad in BANNED_WORDS):
            try:
                await message.delete()
                await message.channel.send(
                    f"{message.author.mention}, stop swearing bro.",
                    delete_after=8,
                )
            except discord.Forbidden:
                pass

        # anti-spam
        from datetime import datetime

        now = datetime.utcnow()
        uid = message.author.id
        times = self.user_message_times.get(uid, [])
        times = [t for t in times if (now - t).total_seconds() <= 8]
        times.append(now)
        self.user_message_times[uid] = times

        if len(times) > 6:
            try:
                await message.channel.send(
                    f"{message.author.mention}, you gotta chill out",
                    delete_after=8,
                )
                await message.author.edit(
                    timed_out_until=discord.utils.utcnow() + timedelta(minutes=1),
                    reason="Spam (automat)",
                )
            except discord.Forbidden:
                pass

    # --------- Commands ----------
    @commands.command(name="clear")
    @commands.has_permissions(manage_messages=True)
    async def clear(self, ctx, amount: int = 10):
        """Delete X messages (default 10)."""
        deleted = await ctx.channel.purge(limit=amount + 1)
        await ctx.send(f"I deleted {len(deleted) - 1} messages 🧹", delete_after=5)

    @clear.error
    async def clear_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You do not have permission to delete messages.")

    @commands.command(name="kick")
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason: str = None):
        """Kick someone (not in their ass)."""
        try:
            await member.kick(reason=reason)
            await ctx.send(
                f"{ctx.author.mention} has kicked {member}. Reason: {reason or 'undefined'}"
            )
        except discord.Forbidden:
            await ctx.send("Can't kick this member.")

    @commands.command(name="ban")
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx, member: discord.Member, *, reason: str = None):
        """Ban someone."""
        try:
            await member.ban(reason=reason, delete_message_days=1)
            await ctx.send(
                f"{ctx.author.mention} has banned {member}. Reason: {reason or 'undefined'} 🔨"
            )
        except discord.Forbidden:
            await ctx.send("Can't ban this one.")

    @commands.command(name="unban")
    @commands.has_permissions(ban_members=True)
    async def unban(self, ctx, user_id: int):
        """Unban a user using name:tag"""
        user = await self.bot.fetch_user(user_id)
        try:
            await ctx.guild.unban(user)
            await ctx.send(f"{user} was unbanned. ✅")
        except discord.NotFound:
            await ctx.send("This user wasn't banned here.")
        except discord.Forbidden:
            await ctx.send("I don't have permission to unban this user.")

    @commands.command(name="timeout")
    @commands.has_permissions(moderate_members=True)
    async def timeout(
        self, ctx, member: discord.Member, minutes: int = 5, *, reason: str = None
    ):
        """Timeout someone"""
        until = discord.utils.utcnow() + timedelta(minutes=minutes)
        try:
            await member.edit(timed_out_until=until, reason=reason or "Timeout")
            await ctx.send(
                f"{ctx.author.mention} has timeout {member.mention} for: {minutes} ⏰"
            )
        except discord.Forbidden:
            await ctx.send("Can't timeout this member.")

    @commands.command(name="untimeout")
    @commands.has_permissions(moderate_members=True)
    async def untimeout(self, ctx, member: discord.Member):
        """Remove someones timeout"""
        try:
            await member.edit(timed_out_until=None, reason="Timeout removed")
            await ctx.send(f"The timeout was removed for {member.mention} ✅")
        except discord.Forbidden:
            await ctx.send("Can't remove the timeout for this member.")


def setup(bot):
    bot.add_cog(Moderation(bot))