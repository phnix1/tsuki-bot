import json
import os
from discord.ext import commands
import discord

DATA_PATH = "data/custom_commands.json"


def load_data():
    if not os.path.exists(DATA_PATH):
        return {}
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


class CustomCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.data = load_data()

    def get_guild_cmds(self, guild_id: int):
        return self.data.setdefault(str(guild_id), {})

    def set_cmd(self, guild_id: int, name: str, response: str):
        cmds = self.get_guild_cmds(guild_id)
        cmds[name.lower()] = response
        save_data(self.data)

    def del_cmd(self, guild_id: int, name: str):
        cmds = self.get_guild_cmds(guild_id)
        if name.lower() in cmds:
            del cmds[name.lower()]
            save_data(self.data)
            return True
        return False

    # -------- MANAGEMENT COMMANDS -------
    @commands.group(name="cc", invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def cc_group(self, ctx):
        """Add, show, or delete custom commands"""
        await ctx.send(
            "Subcommands: `cc add`, `cc del`, `cc list`.\n"
            "Ex: `!cc add hello -Hello world!-` → comanda `!hello`"
        )

    @cc_group.command(name="add")
    @commands.has_permissions(manage_guild=True)
    async def cc_add(self, ctx, name: str, *, response: str):
        if name.startswith(self.bot.command_prefix):
            name = name[len(self.bot.command_prefix) :]
        self.set_cmd(ctx.guild.id, name, response)
        await ctx.send(f"Custom command `{self.bot.command_prefix}{name}` added ✅")

    @cc_group.command(name="del")
    @commands.has_permissions(manage_guild=True)
    async def cc_del(self, ctx, name: str):
        if name.startswith(self.bot.command_prefix):
            name = name[len(self.bot.command_prefix) :]
        if self.del_cmd(ctx.guild.id, name):
            await ctx.send(f"Custom command `{name}` was deleted.")
        else:
            await ctx.send("Can't find this command.")

    @cc_group.command(name="list")
    async def cc_list(self, ctx):
        cmds = self.get_guild_cmds(ctx.guild.id)
        if not cmds:
            return await ctx.send("This command doesn't exist.")
        text = "**Custom commands:**\n" + "\n".join(
            f"- `{self.bot.command_prefix}{name}` → `{resp}`"
            for name, resp in cmds.items()
        )
        await ctx.send(text)

    # -------- EXECUTION HOOK --------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        prefix = self.bot.command_prefix
        content = message.content
        if isinstance(prefix, (list, tuple)):
            p = next((p for p in prefix if content.startswith(p)), None)
            if not p:
                return
            used_prefix = p
        else:
            if not content.startswith(prefix):
                return
            used_prefix = prefix

        cmd_name = content[len(used_prefix) :].split(" ", 1)[0].lower()
        cmds = self.get_guild_cmds(message.guild.id)
        if cmd_name in cmds:
            resp = cmds[cmd_name].replace("{user}", message.author.mention)
            await message.channel.send(resp)
            return

def setup(bot: commands.Bot):
    bot.add_cog(CustomCommands(bot))
