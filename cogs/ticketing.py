import json
import os
import discord
from discord.ext import commands

DATA_PATH = "data/tickets.json"
CONFIG_PATH = "config.json"


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


class Ticketing(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.tickets = load_json(DATA_PATH, {})  # guild_id -> {user_id: channel_id}
        self.global_cfg = load_json(CONFIG_PATH, {})

    def get_guild_tickets(self, guild_id: int):
        return self.tickets.setdefault(str(guild_id), {})

    def set_ticket(self, guild_id: int, user_id: int, channel_id: int | None):
        gt = self.get_guild_tickets(guild_id)
        if channel_id is None:
            gt.pop(str(user_id), None)
        else:
            gt[str(user_id)] = channel_id
        save_json(DATA_PATH, self.tickets)

    # ---- helpers ----
    def get_default_category_name(self):
        return self.global_cfg.get("default_ticket_category", "Tickets")

    def get_default_staff_role_name(self):
        return self.global_cfg.get("default_staff_role", "Staff")

    async def get_or_create_category(self, guild: discord.Guild):
        name = self.get_default_category_name()
        category = discord.utils.get(guild.categories, name=name)
        if category:
            return category
        # create category
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True),
        }
        return await guild.create_category(name=name, overwrites=overwrites)

    def get_staff_role(self, guild: discord.Guild):
        name = self.get_default_staff_role_name()
        return discord.utils.get(guild.roles, name=name)

    # ---- commands ----
    @commands.group(name="ticket", invoke_without_command=True)
    async def ticket_group(self, ctx):
        """Open a ticket."""
        await ctx.send(
            "Subcomenzi: `ticket open [descriere]`, `ticket close`, `ticket add @user`, `ticket remove @user`."
        )

    @ticket_group.command(name="open")
    async def ticket_open(self, ctx, *, subject: str = "No subject"):
        guild = ctx.guild
        author = ctx.author

        existing_id = self.get_guild_tickets(guild.id).get(str(author.id))
        if existing_id:
            ch = guild.get_channel(existing_id)
            if ch:
                return await ctx.send(
                    f"You already have oppened the ticket: {ch.mention}", delete_after=10
                )

        category = await self.get_or_create_category(guild)
        staff_role = self.get_staff_role(guild)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            author: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            ),
        }
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            )

        channel_name = f"ticket-{author.name.lower().replace(' ', '-')}"
        ticket_channel = await guild.create_text_channel(
            name=channel_name, category=category, overwrites=overwrites
        )

        self.set_ticket(guild.id, author.id, ticket_channel.id)

        await ticket_channel.send(
            f"Welcome {author.mention}! 🎫\n"
            f"Subject: **{subject}**\n"
            f"Our team is going to help you soon.\n"
            f"`!ticket close` to close the ticket."
        )
        await ctx.send(f"Created ticket: {ticket_channel.mention}", delete_after=10)

    @ticket_group.command(name="close")
    @commands.has_permissions(administrator=True)
    async def ticket_close(self, ctx):
        """
        Close the ticket.
        (just admins can run this command).
        """
        guild = ctx.guild
        channel = ctx.channel

        # verify ticket channel
        guild_tickets = self.get_guild_tickets(guild.id)
        owner_id = None
        for uid, ch_id in guild_tickets.items():
            if ch_id == channel.id:
                owner_id = int(uid)
                break

        if owner_id is None:
            return await ctx.send("This doesn't seem to be a ticket channel.")

        # removing ticket channel
        self.set_ticket(guild.id, owner_id, None)

        await ctx.send("Ticket closed. The channel will be deleted. 🔒", delete_after=3)

        try:
            await channel.delete(reason=f"Ticket closed by {ctx.author}")
        except discord.Forbidden:
            await ctx.send("I don't have permissions to delete this channel.")


    @ticket_group.command(name="add")
    async def ticket_add(self, ctx, member: discord.Member):
        """Add a member in the ticket (just staff/owner)."""
        guild = ctx.guild
        channel = ctx.channel

        guild_tickets = self.get_guild_tickets(guild.id)
        owner_id = None
        for uid, ch_id in guild_tickets.items():
            if ch_id == channel.id:
                owner_id = int(uid)
                break
        if owner_id is None:
            return await ctx.send("This doesnt seem to be a ticket channel.")

        staff_role = self.get_staff_role(guild)
        if (
            ctx.author.id != owner_id
            and not ctx.author.guild_permissions.manage_channels
            and (not staff_role or staff_role not in ctx.author.roles)
        ):
            return await ctx.send("You do not have permission to modify this ticket.")

        await channel.set_permissions(
            member,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
        )
        await ctx.send(f"{member.mention} was added in the ticket.")

    @ticket_group.command(name="remove")
    async def ticket_remove(self, ctx, member: discord.Member):
        guild = ctx.guild
        channel = ctx.channel

        guild_tickets = self.get_guild_tickets(guild.id)
        owner_id = None
        for uid, ch_id in guild_tickets.items():
            if ch_id == channel.id:
                owner_id = int(uid)
                break
        if owner_id is None:
            return await ctx.send("This doesn't seem to be a ticket channel.")

        staff_role = self.get_staff_role(guild)
        if (
            ctx.author.id != owner_id
            and not ctx.author.guild_permissions.manage_channels
            and (not staff_role or staff_role not in ctx.author.roles)
        ):
            return await ctx.send("You do not have permission to modify this ticket.")

        await channel.set_permissions(member, overwrite=None)
        await ctx.send(f"{member.mention} was removed from the ticket.")


def setup(bot: commands.Bot):
    bot.add_cog(Ticketing(bot))
