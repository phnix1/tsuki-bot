import os
import json
import asyncio
from datetime import datetime, timedelta

import discord
from discord.ext import commands

# file where we store filtered words
WORD_FILTER_FILE = "data/wordfilter.json"

# optional default words (can be removed/edited)
DEFAULT_BANNED_WORDS = ["nigga", "bitch", "nigger", "autistic", "retarded"]


def load_filtered_words() -> list[str]:
    """Load filtered words from JSON file."""
    if not os.path.exists(WORD_FILTER_FILE):
        # if file doesn't exist, create it with defaults
        save_filtered_words(DEFAULT_BANNED_WORDS)
        return list(DEFAULT_BANNED_WORDS)

    with open(WORD_FILTER_FILE, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            # if file is corrupted, reset to defaults
            save_filtered_words(DEFAULT_BANNED_WORDS)
            return list(DEFAULT_BANNED_WORDS)

    # make sure it's a list of strings
    if not isinstance(data, list):
        return list(DEFAULT_BANNED_WORDS)

    return [str(w).lower() for w in data]


def save_filtered_words(words: list[str]) -> None:
    """Save filtered words to JSON file."""
    os.makedirs(os.path.dirname(WORD_FILTER_FILE), exist_ok=True)
    with open(WORD_FILTER_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(set(w.lower() for w in words)), f, indent=4)


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pending_fullclear = {}
        self.user_message_times: dict[int, list[datetime]] = {}

    # --------- Filter + anti-spam ----------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # ignore bots
        if message.author.bot:
            return

        # ignore DMs
        if not message.guild:
            return

        # word filter
        content = message.content.lower()
        filtered_words = load_filtered_words()

        for bad_word in filtered_words:
            if bad_word and bad_word in content:
                try:
                    await message.delete()
                except discord.Forbidden:
                    pass
                except discord.NotFound:
                    pass

                try:
                    await message.channel.send(
                        f"{message.author.mention}, watch your language.",
                        delete_after=8,
                    )
                except discord.Forbidden:
                    pass

                # don't continue with spam check if we already deleted the message
                return

        # anti-spam (too many messages in short time)
        now = datetime.utcnow()
        uid = message.author.id

        times = self.user_message_times.get(uid, [])
        # keep only messages from last 8 seconds
        times = [t for t in times if (now - t).total_seconds() <= 8]
        times.append(now)
        self.user_message_times[uid] = times

        # more than 6 messages in 8 seconds => 1 minute timeout
        if len(times) > 6:
            try:
                await message.channel.send(
                    f"{message.author.mention}, you gotta chill out.",
                    delete_after=8,
                )
                await message.author.edit(
                    timed_out_until=discord.utils.utcnow() + timedelta(minutes=1),
                    reason="Spam (auto)",
                )
            except discord.Forbidden:
                pass

    # word filter commands

    @commands.command(name="wordlist")
    @commands.has_permissions(moderate_members=True)
    async def wordlist(self, ctx, action: str = None, *, word: str | None = None):
        """
        Manage filtered words.
        Usage:
        !wordlist add <word>
        !wordlist remove <word>
        !wordlist list
        """
        if action is None:
            return await ctx.send(
                "Usage: `!wordlist add <word>` / `!wordlist remove <word>` / `!wordlist list`"
            )

        action = action.lower()
        words = load_filtered_words()

        if action == "add":
            if not word:
                return await ctx.send("Usage: `!wordlist add <word>`")

            w = word.lower().strip()
            if w in words:
                return await ctx.send("That word is already in the filter list.")

            words.append(w)
            save_filtered_words(words)
            return await ctx.send(f"Added `{w}` to the filter list ✅")

        elif action == "remove":
            if not word:
                return await ctx.send("Usage: `!wordlist remove <word>`")

            w = word.lower().strip()
            if w not in words:
                return await ctx.send("That word is not in the filter list.")

            words.remove(w)
            save_filtered_words(words)
            return await ctx.send(f"Removed `{w}` from the filter list ❌")

        elif action == "list":
            if not words:
                return await ctx.send("No filtered words are set.")
            formatted = ", ".join(f"`{w}`" for w in words)
            return await ctx.send(f"📛 **Filtered words:**\n{formatted}")

        else:
            return await ctx.send(
                "Invalid action.\n"
                "Use: `!wordlist add <word>` / `!wordlist remove <word>` / `!wordlist list`"
            )

    # --------- Clear ----------
    @commands.command(name="clear")
    @commands.has_permissions(manage_messages=True)
    async def clear(self, ctx, amount: int = 10):
        """Delete a number of messages from the current channel."""
        if amount <= 0:
            return await ctx.send("Amount must be at least 1.")

        deleted = await ctx.channel.purge(limit=amount + 1)
        await ctx.send(
            f"I deleted {len(deleted) - 1} messages 🧹",
            delete_after=5,
        )

    @clear.error
    async def clear_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You do not have permission to delete messages.")

    # fullclear

    @commands.command(name="fullclear")
    @commands.has_permissions(manage_messages=True)
    async def fullclear(self, ctx):
        """Delete all messages from the current channel."""

        user_id = ctx.author.id
        channel_id = ctx.channel.id

        self.pending_fullclear[user_id] = channel_id

        await ctx.send(
            "⚠️ **DANGER ZONE** ⚠️\n\n"
            f"You are about to delete **ALL messages** in {ctx.channel.mention}.\n"
            "This action is **permanent and CANNOT be undone**.\n\n"
            "Type **`!confirm`** within **5 seconds** to continue.\n"
        )

        await asyncio.sleep(7)

        if self.pending_fullclear.get(user_id) == channel_id:
            self.pending_fullclear.pop(user_id, None)
            await ctx.send("⌛ **Fullclear expired — action cancelled.**")

    # -------------------------------------------------

    @commands.command(hidden=True)
    async def confirm(self, ctx):
        user_id = ctx.author.id

        # check if user has a pending fullclear
        if user_id not in self.pending_fullclear:
            await ctx.send("❌ You have nothing to confirm.")
            return

        channel_id = self.pending_fullclear.pop(user_id)

        # confirm in correct channel
        if ctx.channel.id != channel_id:
            await ctx.send("❌ You must confirm in the same channel where you started the command.")
            return

        channel = ctx.channel

        try:
            deleted = await channel.purge()
            await ctx.send(
                f"✅ **Full clear successful!** Deleted `{len(deleted)}` messages.",
                delete_after=5
            )

        except discord.Forbidden:
            await ctx.send("❌ I don’t have permission to delete messages.")
        except Exception as e:
            await ctx.send(f"❌ An error occurred:\n```{e}```")

    # -------------------------------------------------

    @fullclear.error
    async def fullclear_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ You need `Manage Messages` permission to use this command.")
        else:
            raise error

    # --------- Kick / Ban ----------

    @commands.command(name="kick")
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason: str | None = None):
        """Kick someone."""
        try:
            await member.kick(reason=reason)
            await ctx.send(
                f"{ctx.author.mention} has kicked {member}. "
                f"Reason: {reason or 'undefined'}"
            )
        except discord.Forbidden:
            await ctx.send("Can't kick this member.")

    @commands.command(name="ban")
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx, member: discord.Member, *, reason: str | None = None):
        """Ban someone."""
        try:
            await member.ban(reason=reason, delete_message_days=1)
            await ctx.send(
                f"{ctx.author.mention} has banned {member}. "
                f"Reason: {reason or 'undefined'} 🔨"
            )
        except discord.Forbidden:
            await ctx.send("Can't ban this one.")

    @commands.command(name="unban")
    @commands.has_permissions(ban_members=True)
    async def unban(self, ctx, *, user: str):
        """Unban someone by name#discriminator or ID."""
        banned_users = await ctx.guild.fetch_members().flatten()

        # user can be "name#discrim" or just id
        try:
            user_id = int(user)
        except ValueError:
            user_id = None

        if user_id is not None:
            # try unban by ID
            for ban_entry in await ctx.guild.bans():
                if ban_entry.user.id == user_id:
                    await ctx.guild.unban(ban_entry.user)
                    return await ctx.send(f"Unbanned {ban_entry.user} ✅")
        else:
            name, discrim = user.split("#")
            for ban_entry in await ctx.guild.bans():
                if ban_entry.user.name == name and ban_entry.user.discriminator == discrim:
                    await ctx.guild.unban(ban_entry.user)
                    return await ctx.send(f"Unbanned {ban_entry.user} ✅")

        await ctx.send("User not found in ban list.")

    # --------- Timeout / Un-timeout (text mute) ----------

    @commands.command(name="timeout")
    @commands.has_permissions(moderate_members=True)
    async def timeout(self, ctx, member: discord.Member, minutes: int, *, reason: str | None = None):
        """Timeout someone for X minutes."""
        try:
            duration = discord.utils.utcnow() + timedelta(minutes=minutes)
            await member.edit(
                timed_out_until=duration,
                reason=reason or "Timeout",
            )
            await ctx.send(
                f"{member.mention} has been timed out for {minutes} minute(s). "
                f"Reason: {reason or 'undefined'} ⏳"
            )
        except discord.Forbidden:
            await ctx.send("Can't timeout this member.")

    @commands.command(name="untimeout")
    @commands.has_permissions(moderate_members=True)
    async def untimeout(self, ctx, member: discord.Member):
        """Remove someone's timeout."""
        try:
            await member.edit(timed_out_until=None, reason="Timeout removed")
            await ctx.send(f"The timeout was removed for {member.mention} ✅")
        except discord.Forbidden:
            await ctx.send("Can't remove the timeout for this member.")

    # --------- Mute / Unmute (text, via timeout) ----------

    @commands.command(name="mute")
    @commands.has_permissions(moderate_members=True)
    async def mute(self, ctx, member: discord.Member, minutes: int, *, reason: str | None = None):
        """
        Mute a member in text (timeout).
        Usage: !mute @user <minutes> [reason]
        """
        try:
            duration = discord.utils.utcnow() + timedelta(minutes=minutes)
            await member.edit(
                timed_out_until=duration,
                reason=reason or "Text mute",
            )
            await ctx.send(
                f"{member.mention} has been muted for {minutes} minute(s). 🔇 "
                f"Reason: {reason or 'undefined'}"
            )
        except discord.Forbidden:
            await ctx.send("Cannot mute this member.")

    @commands.command(name="unmute")
    @commands.has_permissions(moderate_members=True)
    async def unmute(self, ctx, member: discord.Member, *, reason: str | None = None):
        """
        Remove text mute (timeout).
        Usage: !unmute @user [reason]
        """
        try:
            await member.edit(
                timed_out_until=None,
                reason=reason or "Text unmute",
            )
            await ctx.send(
                f"{member.mention} has been unmuted. 🔊 "
                f"Reason: {reason or 'undefined'}"
            )
        except discord.Forbidden:
            await ctx.send("Cannot unmute this member.")


def setup(bot: commands.Bot):
    bot.add_cog(Moderation(bot))