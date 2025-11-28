import os
import discord
from discord.ext import commands
import asyncio
import yt_dlp as youtube_dl

# --------- FFMPEG PATH (ABSOLUTE) ---------
BASE_DIR = os.path.dirname(os.path.abspath(os.path.join(__file__, "..")))
FFMPEG_PATH = os.path.join(BASE_DIR, "ffmpeg", "bin", "ffmpeg.exe")

print("FFMPEG_PATH =", FFMPEG_PATH, "| exists:", os.path.exists(FFMPEG_PATH))

# -------- YTDL / FFMPEG CONFIG --------

ytdl_format_options = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "extract_flat": False,
    "extractor_args": {
        "youtube": {
            "player_client": ["default"]
        }
    },
}

ffmpeg_options = {
    "options": "-vn"
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, requester, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.requester = requester
        self.title = data.get("title")
        self.url = data.get("webpage_url")

    @classmethod
    async def from_query(cls, query, *, loop, requester, stream=True):
        # Converts plain query into a youtube search
        if not (query.startswith("http://") or query.startswith("https://")):
            query = f"ytsearch:{query}"

        def run():
            return ytdl.extract_info(query, download=not stream)

        data = await loop.run_in_executor(None, run)

        # if it's search or playlist, get the first entry
        if "entries" in data:
            data = data["entries"][0]

        audio_url = data["url"] if stream else ytdl.prepare_filename(data)

        audio = discord.FFmpegPCMAudio(
            audio_url,
            executable=FFMPEG_PATH,
            **ffmpeg_options
        )

        return cls(audio, data=data, requester=requester)


class GuildMusicPlayer:
    """Handles the music queue and playback for a single guild."""

    def __init__(self, bot: commands.Bot, guild: discord.Guild):
        self.bot = bot
        self.guild = guild
        self.queue: list[YTDLSource] = []
        self.current: YTDLSource | None = None
        self.text_channel: discord.TextChannel | None = None
        self.volume: float = 0.5  # default volume (50%)

    @property
    def voice(self) -> discord.VoiceClient | None:
        return self.guild.voice_client

    def is_playing(self):
        vc = self.voice
        return vc is not None and vc.is_playing()

    async def add_to_queue(self, source: YTDLSource, channel: discord.TextChannel):
        self.queue.append(source)
        self.text_channel = channel
        if not self.is_playing():
            await self.start_next()

    async def start_next(self):
        if not self.queue:
            self.current = None
            return

        vc = self.voice
        if vc is None or not vc.is_connected():
            self.current = None
            return

        self.current = self.queue.pop(0)

        def _after(error):
            if error:
                print(f"Playback error: {error}")
            fut = asyncio.run_coroutine_threadsafe(
                self.start_next(), self.bot.loop
            )
            try:
                fut.result()
            except Exception as e:
                print(f"Error starting next track: {e}")

        vc.play(self.current, after=_after)

        if self.text_channel:
            await self.text_channel.send(
                f"🎶 Now playing: **{self.current.title}** (requested by {self.current.requester.mention})"
            )

    def stop(self):
        vc = self.voice
        if vc and vc.is_playing():
            vc.stop()
        self.queue.clear()
        self.current = None


class Music(commands.Cog):
    """Music commands: play songs, manage the queue, control playback."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.players: dict[int, GuildMusicPlayer] = {}

    # ---- helpers ----
    def get_player(self, guild: discord.Guild) -> GuildMusicPlayer:
        if guild.id not in self.players:
            self.players[guild.id] = GuildMusicPlayer(self.bot, guild)
        return self.players[guild.id]

    async def ensure_voice(self, ctx) -> discord.VoiceClient | None:
        """Ensure the bot is connected to the user's voice channel (used for join / first play)."""
        if ctx.author.voice is None:
            await ctx.send("You must be in a voice channel to use music commands.")
            return None

        vc = ctx.guild.voice_client

        if vc is None or not vc.is_connected():
            try:
                vc = await ctx.author.voice.channel.connect()
            except Exception as e:
                await ctx.send(f"Failed to connect to voice: `{e}`")
                return None

        elif vc.channel != ctx.author.voice.channel:
            try:
                await vc.move_to(ctx.author.voice.channel)
            except Exception as e:
                await ctx.send(f"Failed to move to your channel: `{e}`")
                return None

        return vc

    async def require_same_voice(self, ctx) -> discord.VoiceClient | None:
        """
        Require the user to be in the same voice channel as the bot.
        Used for playback control commands (play/pause/resume/skip/stop/volume).
        """
        vc = ctx.guild.voice_client
        if vc is None or not vc.is_connected():
            await ctx.send("I'm not connected to a voice channel.")
            return None

        if ctx.author.voice is None:
            await ctx.send("You must be in my voice channel to use this command.")
            return None

        if ctx.author.voice.channel != vc.channel:
            await ctx.send(f"You must be in `{vc.channel.name}` to use this command.")
            return None

        return vc

    # ---- commands ----

    @commands.command(name="join")
    async def join(self, ctx):
        """Make the bot join your voice channel."""
        vc = await self.ensure_voice(ctx)
        if vc:
            await ctx.send(f"Connected to `{vc.channel.name}`.")

    @commands.command(name="leave")
    async def leave(self, ctx):
        """Disconnect the bot and clear the queue."""
        vc = ctx.guild.voice_client
        if vc and vc.is_connected():
            player = self.get_player(ctx.guild)
            player.stop()
            await vc.disconnect()
            await ctx.send("Disconnected and cleared the queue.")
        else:
            await ctx.send("I'm not connected to any voice channel.")

    @commands.command(name="play", aliases=["p"])
    async def play(self, ctx, *, query: str):
        """
        Add a song to the queue (or play it instantly).
        User MUST be in the same voice channel as the bot if the bot is already connected.
        """
        vc = ctx.guild.voice_client

        if vc is None or not vc.is_connected():
            # first time: join the user's channel
            vc = await self.ensure_voice(ctx)
            if vc is None:
                return
        else:
            # bot is already in a channel → require user to be with the bot
            vc = await self.require_same_voice(ctx)
            if vc is None:
                return

        player = self.get_player(ctx.guild)
        await ctx.send("🔍 Searching...")

        try:
            source = await YTDLSource.from_query(
                query,
                loop=self.bot.loop,
                requester=ctx.author,
                stream=True,
            )
        except Exception as e:
            print(e)
            return await ctx.send("Failed to retrieve audio.")

        # apply the server's volume to the new source
        source.volume = player.volume

        await player.add_to_queue(source, ctx.channel)

        if player.current is source and vc.is_playing():
            return
        else:
            await ctx.send(
                f"✅ Added to queue: **{source.title}** (requested by {ctx.author.mention})"
            )

    @commands.command(name="pause")
    async def pause(self, ctx):
        """Pause the current song (only if you're in the same voice channel as the bot)."""
        vc = await self.require_same_voice(ctx)
        if vc is None:
            return
        if not vc.is_playing():
            return await ctx.send("Nothing is playing.")
        vc.pause()
        await ctx.send("⏸️ Paused.")

    @commands.command(name="resume")
    async def resume(self, ctx):
        """Resume playback (only if you're in the same voice channel as the bot)."""
        vc = await self.require_same_voice(ctx)
        if vc is None:
            return
        if not vc.is_paused():
            return await ctx.send("Nothing to resume.")
        vc.resume()
        await ctx.send("▶️ Resumed.")

    @commands.command(name="skip")
    async def skip(self, ctx):
        """Skip the current song (only if you're in the same voice channel as the bot)."""
        vc = await self.require_same_voice(ctx)
        if vc is None:
            return
        if not vc.is_playing():
            return await ctx.send("Nothing is playing to skip.")
        vc.stop()
        await ctx.send("⏭️ Skipped.")

    @commands.command(name="stop")
    async def stop(self, ctx):
        """Stop playback and clear the queue (only if you're in the same voice channel as the bot)."""
        vc = await self.require_same_voice(ctx)
        if vc is None:
            return
        player = self.get_player(ctx.guild)
        player.stop()
        await ctx.send("⏹️ Stopped and cleared the queue.")

    @commands.command(name="nowplaying", aliases=["np"])
    async def now_playing(self, ctx):
        """Show the currently playing song."""
        player = self.get_player(ctx.guild)
        if not player.current:
            return await ctx.send("Nothing is playing right now.")
        await ctx.send(
            f"🎶 Now playing: **{player.current.title}** "
            f"(requested by {player.current.requester.mention})\n"
            f"🔗 {player.current.url}"
        )

    @commands.command(name="queue", aliases=["q"])
    async def queue_cmd(self, ctx):
        """Show the current queue."""
        player = self.get_player(ctx.guild)
        if not player.queue:
            return await ctx.send("The queue is empty.")
        lines = [
            f"{i}. **{src.title}** (requested by {src.requester.display_name})"
            for i, src in enumerate(player.queue, start=1)
        ]
        await ctx.send("📜 **Current Queue:**\n" + "\n".join(lines))

    @commands.command(name="volume", aliases=["vol"])
    async def volume(self, ctx, volume: int | None = None):
        """
        View or set the volume (0–100).
        User must be in the same voice channel as the bot.
        """
        vc = await self.require_same_voice(ctx)
        if vc is None:
            return

        player = self.get_player(ctx.guild)

        if volume is None:
            return await ctx.send(
                f"🔊 Current volume: `{int(player.volume * 100)}%`"
            )

        if volume < 0 or volume > 100:
            return await ctx.send("Please choose a value between `0` and `100`.")

        player.volume = volume / 100

        # update current track
        if vc.source and isinstance(vc.source, discord.PCMVolumeTransformer):
            vc.source.volume = player.volume

        await ctx.send(f"✅ Volume set to `{volume}%`.")


def setup(bot: commands.Bot):
    bot.add_cog(Music(bot))
