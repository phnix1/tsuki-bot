import os
import asyncio
import discord
from discord.ext import commands
import yt_dlp as youtube_dl


BASE_DIR = os.path.dirname(os.path.abspath(os.path.join(__file__, "..")))
FFMPEG_PATH = os.path.join(BASE_DIR, "ffmpeg", "bin", "ffmpeg.exe")

print("FFMPEG_PATH =", FFMPEG_PATH, "| exists:", os.path.exists(FFMPEG_PATH))

# ----------------- YTDL / FFMPEG CONFIG -----------------

ytdl_format_options = {
    "format": "bestaudio/best",
    "noplaylist": True,          # for single tracks
    "quiet": True,
    "ignoreerrors": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
    "extractor_args": {
        "youtube": {
            "player_client": ["default"]
        }
    },
}

ffmpeg_options = {
    "before_options": (
        "-reconnect 1 "
        "-reconnect_streamed 1 "
        "-reconnect_on_network_error 1 "
        "-reconnect_delay_max 5"
    ),
    # no video + reduce log noise
    "options": "-vn -loglevel error",
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

# separate YoutubeDL instance for playlists (we allow playlists here)
playlist_ytdl_options = dict(ytdl_format_options)
playlist_ytdl_options["noplaylist"] = False
playlist_ytdl_options["extract_flat"] = "in_playlist"  # we only need basic info
playlist_ytdl = youtube_dl.YoutubeDL(playlist_ytdl_options)



class YTDLSource(discord.PCMVolumeTransformer):
    """
    Audio source created by yt-dlp + FFmpeg.
    Stores song metadata like title and requester.
    """

    def __init__(self, source, *, data, requester, volume: float = 1.0):
        super().__init__(source, volume)
        self.data = data
        self.requester = requester
        self.title = data.get("title")
        self.url = data.get("webpage_url") or data.get("url")

    @classmethod
    async def from_query(cls, query: str, *, loop, requester, stream: bool = True):
        """
        Creates an audio source from a song name or URL.
        Automatically searches YouTube if no direct link is provided.
        """

        # If it's not a direct URL, treat it as a YouTube search
        if not query.startswith(("http://", "https://")):
            search_query = f"ytsearch1:{query}"
        else:
            search_query = query

        def run():
            return ytdl.extract_info(search_query, download=not stream)

        try:
            data = await loop.run_in_executor(None, run)
        except Exception as e:
            print("[YTDL] extract_info error:", e)
            raise

        if data is None:
            raise RuntimeError("yt-dlp returned no data.")

        # Search or playlist result → take first valid entry
        if "entries" in data:
            entries = [e for e in data["entries"] if e]
            if not entries:
                raise RuntimeError("No valid results found.")
            data = entries[0]

        print("[YTDL] Title:", data.get("title"))
        print("[YTDL] Stream URL:", data.get("url"))

        audio_url = data["url"] if stream else ytdl.prepare_filename(data)
        executable = FFMPEG_PATH if os.path.exists(FFMPEG_PATH) else "ffmpeg"

        print("[YTDL] Using ffmpeg executable:", executable)

        try:
            audio = discord.FFmpegPCMAudio(
                audio_url,
                executable=executable,
                **ffmpeg_options,
            )
        except Exception as e:
            print("[FFMPEG] Error:", e)
            raise

        return cls(audio, data=data, requester=requester)


class GuildMusicPlayer:
    """
    Controls the music queue and playback for a single guild.
    """

    def __init__(self, bot: commands.Bot, guild: discord.Guild):
        self.bot = bot
        self.guild = guild
        self.queue: list[YTDLSource] = []
        self.current: YTDLSource | None = None
        self.text_channel: discord.TextChannel | None = None
        self.volume: float = 1.0

    @property
    def voice(self) -> discord.VoiceClient | None:
        return self.guild.voice_client

    def is_playing(self) -> bool:
        vc = self.voice
        return vc is not None and vc.is_playing()

    async def add_to_queue(self, source: YTDLSource, channel: discord.TextChannel):
        """
        Adds a song to the queue and starts playback if nothing is playing.
        """
        self.queue.append(source)
        self.text_channel = channel
        print("[Music] Added to queue:", source.title)

        if not self.is_playing():
            await self.start_next()

    async def start_next(self):
        """
        Starts the next song or disconnects if the queue is empty.
        """
        vc = self.voice

        if vc is None or not vc.is_connected():
            print("[Music] Voice client not connected — clearing queue.")
            self.queue.clear()
            self.current = None
            return

        if not self.queue:
            print("[Music] Queue empty — disconnecting.")
            self.current = None
            await vc.disconnect()
            if self.text_channel:
                await self.text_channel.send("👋 Queue is empty. Leaving the voice channel.")
            return

        self.current = self.queue.pop(0)
        self.current.volume = self.volume

        print("[Music] Now playing:", self.current.title)

        def _after(error: Exception | None):
            if error:
                print("[Music] Playback error:", error)

            fut = asyncio.run_coroutine_threadsafe(self.start_next(), self.bot.loop)
            try:
                fut.result()
            except Exception as e:
                print("[Music] Error while playing next:", e)

        try:
            vc.play(self.current, after=_after)
        except Exception as e:
            print("[Music] vc.play() error:", e)

            if self.text_channel:
                asyncio.run_coroutine_threadsafe(
                    self.text_channel.send(
                        f"❌ **Failed to start playback:** `{e}`"
                    ),
                    self.bot.loop,
                )

            self.current = None
            return

        if self.text_channel:
            await self.text_channel.send(
                f"🎶 **Now playing:** {self.current.title} "
                f"(requested by {self.current.requester.mention})"
            )

    def stop(self):
        """
        Stops playback and clears the queue.
        """
        vc = self.voice
        if vc and vc.is_playing():
            vc.stop()

        self.queue.clear()
        self.current = None

        print("[Music] Playback stopped. Queue cleared.")



class Music(commands.Cog):
    """Music commands: play tracks, manage the queue and playback."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.players: dict[int, GuildMusicPlayer] = {}

    # helpers

    def get_player(self, guild: discord.Guild) -> GuildMusicPlayer:
        if guild.id not in self.players:
            self.players[guild.id] = GuildMusicPlayer(self.bot, guild)
        return self.players[guild.id]

    @staticmethod
    def _is_youtube_playlist(url: str) -> bool:
        """
        Rough check if a URL looks like a YouTube playlist.
        Supports both /playlist and watch?v=...&list=...
        """
        url = url.lower()
        if "youtube.com/playlist" in url:
            return True
        if "youtube.com/watch" in url and "list=" in url:
            return True
        if "youtu.be/" in url and "list=" in url:
            return True
        return False

    async def ensure_voice(self, ctx) -> discord.VoiceClient | None:
        """
        Make sure the bot is in the same voice channel as the user.
        - If not connected, it connects.
        - If connected to another channel, it moves.
        - If already connected to the correct channel, it just returns the client.
        """

        if ctx.author.voice is None:
            await ctx.send("You must be in a voice channel to use this command.")
            return None

        destination = ctx.author.voice.channel
        vc: discord.VoiceClient | None = ctx.guild.voice_client

        # case 1: already connected
        if vc and vc.is_connected():
            if vc.channel != destination:
                try:
                    await vc.move_to(destination)
                    print(f"[Music] Moved to voice channel: {destination}")
                except Exception as e:
                    print("[Music] Failed to move voice channel:", e)
                    await ctx.send(f"❌ Failed to move to your voice channel: `{e}`")
                    return None
            return vc

        # case 2: not connected yet + try to connect
        try:
            vc = await destination.connect()
            print(f"[Music] Connected to voice channel: {destination}")
            return vc

        except discord.ClientException as e:
            if "Already connected to a voice channel" in str(e):
                print("[Music] Got 'Already connected' but using existing voice client.")
                return ctx.guild.voice_client

            print("[Music] ClientException while connecting:", e)
            await ctx.send(f"❌ Failed to connect to voice: `{e}`")
            return None

        except Exception as e:
            print("[Music] General exception while connecting:", e)
            await ctx.send(f"❌ Failed to connect to voice: `{e}`")
            return None

    async def require_same_voice(self, ctx) -> discord.VoiceClient | None:
        """
        Ensures the user is in the same voice channel as the bot.
        """

        vc = ctx.guild.voice_client

        if vc is None or not vc.is_connected():
            await ctx.send("I'm not connected to a voice channel.")
            return None

        if ctx.author.voice is None:
            await ctx.send("You need to be in my voice channel.")
            return None

        if ctx.author.voice.channel != vc.channel:
            await ctx.send(f"You must be in `{vc.channel.name}` to use this command.")
            return None

        return vc

    @commands.command(name="queue", aliases=["q"])
    async def queue(self, ctx):
        """
        Show the current music queue.
        """
        player = self.get_player(ctx.guild)

        lines = []

        # now playing
        if player.current:
            lines.append(
                f"🎧 **Now playing:** {player.current.title} "
                f"(requested by {player.current.requester.mention})"
            )
        else:
            lines.append("🎧 **Now playing:** nothing.")

        # upcoming tracks
        if not player.queue:
            lines.append("\n📭 The queue is currently empty.")
            await ctx.send("\n".join(lines))
            return

        max_to_show = 15  # safety limit for long queues
        lines.append("\n📜 **Up next:**")

        for idx, track in enumerate(player.queue[:max_to_show], start=1):
            lines.append(
                f"`{idx}.` {track.title} "
                f"(requested by {track.requester.mention})"
            )

        remaining = len(player.queue) - max_to_show
        if remaining > 0:
            lines.append(f"\n… and `{remaining}` more track(s) in the queue.")

        await ctx.send("\n".join(lines))

    # commands

    @commands.command(name="join")
    async def join(self, ctx):
        """Join your voice channel."""
        vc = await self.ensure_voice(ctx)
        if vc:
            await ctx.send(f"✅ Connected to `{vc.channel.name}`.")

    @commands.command(name="leave", aliases=["disconnect", "dc"])
    async def leave(self, ctx):
        """Disconnect from voice and clear the queue."""
        vc = ctx.guild.voice_client
        player = self.get_player(ctx.guild)

        if not vc or not vc.is_connected():
            return await ctx.send("I'm not in a voice channel.")

        player.stop()
        await vc.disconnect()
        await ctx.send("👋 Disconnected.")

    @commands.command(name="play", aliases=["p"])
    async def play(self, ctx, *, query: str):
        """
        Plays a song by name or YouTube link.
        """
        vc = ctx.guild.voice_client

        if vc is None or not vc.is_connected():
            vc = await self.ensure_voice(ctx)
            if vc is None:
                return
        else:
            vc = await self.require_same_voice(ctx)
            if vc is None:
                return

        player = self.get_player(ctx.guild)

        status_msg = await ctx.send(f"🔍 Searching: `{query}`")

        # playlist handling
        if self._is_youtube_playlist(query):
            def run_playlist():
                return playlist_ytdl.extract_info(query, download=False)

            try:
                data = await self.bot.loop.run_in_executor(None, run_playlist)
            except Exception as e:
                print("[Music] Playlist extract error:", e)
                await status_msg.edit(content=f"❌ Error while loading playlist: `{e}`")
                return

            entries = data.get("entries") or []
            if not entries:
                await status_msg.edit(content="❌ No tracks found in this playlist.")
                return

            max_tracks = 50  # safety limit
            added = 0

            for entry in entries[:max_tracks]:
                if not entry:
                    continue

                # with extract_flat, 'id' is usually the video ID
                video_id = entry.get("id") or entry.get("url")
                if not video_id:
                    continue

                video_url = f"https://www.youtube.com/watch?v={video_id}"

                try:
                    source = await YTDLSource.from_query(
                        video_url,
                        loop=self.bot.loop,
                        requester=ctx.author,
                        stream=True,
                    )
                except Exception as e:
                    print("[Music] Error while adding playlist entry:", e)
                    continue

                await player.add_to_queue(source, ctx.channel)
                added += 1

            if added == 0:
                await status_msg.edit(content="❌ Failed to add any tracks from this playlist.")
            else:
                await status_msg.edit(
                    content=f"✅ Added `{added}` track(s) from the playlist to the queue."
                )

            return

        # single track / search
        try:
            source = await YTDLSource.from_query(
                query,
                loop=self.bot.loop,
                requester=ctx.author,
                stream=True,
            )
        except Exception as e:
            print("[Music] Single track error:", e)
            await status_msg.edit(content=f"❌ Error: `{e}`")
            return

        await player.add_to_queue(source, ctx.channel)
        await status_msg.edit(content=f"✅ Added to queue: **{source.title}**")

    @commands.command(name="skip")
    async def skip(self, ctx):
        """Skip the current song."""
        vc = await self.require_same_voice(ctx)
        if vc is None:
            return

        player = self.get_player(ctx.guild)
        if not player.is_playing():
            return await ctx.send("Nothing is playing.")

        vc.stop()
        await ctx.send("⏭️ Skipped.")

    @commands.command(name="stop")
    async def stop(self, ctx):
        """Stop playback and clear the queue."""
        vc = await self.require_same_voice(ctx)
        if vc is None:
            return

        self.get_player(ctx.guild).stop()
        vc.stop()
        await ctx.send("⏹️ Playback stopped.")

    @commands.command(name="pause")
    async def pause(self, ctx):
        """Pause playback."""
        vc = await self.require_same_voice(ctx)
        if vc and vc.is_playing():
            vc.pause()
            await ctx.send("⏸️ Paused.")

    @commands.command(name="resume")
    async def resume(self, ctx):
        """Resume playback."""
        vc = await self.require_same_voice(ctx)
        if vc and vc.is_paused():
            vc.resume()
            await ctx.send("▶️ Resumed.")

    @commands.command(name="volume", aliases=["vol"])
    async def volume(self, ctx, volume: int = None):
        """
        View or change the playback volume (0–100).

        Usage:
        !volume        -> shows current volume
        !volume 50     -> sets volume to 50%
        """
        vc = await self.require_same_voice(ctx)
        if vc is None:
            return

        player = self.get_player(ctx.guild)

        # show current volume
        if volume is None:
            current = int(player.volume * 100)
            await ctx.send(f"🔊 **Current volume:** `{current}%`")
            return

        # change volume
        if not 0 <= volume <= 100:
            await ctx.send("❌ Volume must be between 0 and 100.")
            return

        player.volume = volume / 100

        if vc.source and isinstance(vc.source, discord.PCMVolumeTransformer):
            vc.source.volume = player.volume

        await ctx.send(f"✅ **Volume set to:** `{volume}%`")



def setup(bot: commands.Bot):
    bot.add_cog(Music(bot))
