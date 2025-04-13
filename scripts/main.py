from rich.console import Console, Group
from rich.panel import Panel
from rich.progress import Progress, BarColumn
from rich.live import Live
from rich.style import Style
from rich.text import Text
from rich.table import Table
from rich.align import Align
from spotipy import Spotify
from spotipy.oauth2 import SpotifyOAuth
from pathlib import Path
from dotenv import load_dotenv
import os
import time
import threading
import sys
import termios
import tty
import re

load_dotenv()
console = Console()

CACHE_PATH = Path.home() / ".cache-spotify"
sp = Spotify(auth_manager=SpotifyOAuth(
    scope="user-read-playback-state user-modify-playback-state",
    redirect_uri=os.getenv("SPOTIPY_REDIRECT_URI"),
    cache_path=str(CACHE_PATH)
))

spotify_green = "#1DB954"
track_grey = "grey30"
background_style = Style(bgcolor="#121212")

MODES = {"DDOS": 2, "AI": 5, "PY": 8}
MODE = os.getenv("SPOTIFY_UPDATE_MODE", "AI").upper()
POLL_INTERVAL = MODES.get(MODE, 3)

search_query = ""
search_results = []
current_selection = 0
scroll_offset = 0
lock = threading.Lock()
typing_mode = True
show_results = False
VISIBLE_ROWS = 5


def format_time(seconds):
    return f"{seconds // 60:02}:{seconds % 60:02}"


def clean_name(name):
    return re.sub(r"\s*\([^)]*\)", "", name).strip()


def fetch_playback():
    current = sp.current_playback()
    if not current or not current["item"]:
        return None

    item = current["item"]
    return {
        "title": clean_name(item["name"]),
        "artist": item["artists"][0]["name"],
        "album": clean_name(item["album"]["name"]),
        "device": current["device"]["name"],
        "duration": item["duration_ms"] // 1000,
        "elapsed": current["progress_ms"] // 1000,
        "is_playing": current["is_playing"]
    }


def create_panel(track, elapsed):
    meta = Text()
    meta.append("🎵 ")
    meta.append(f"{track['title']}", style="bold white")
    meta.append(" ┃ ")
    meta.append(" ")
    meta.append(f"{track['artist']}", style="green")
    meta.append(" ┃ ")
    meta.append("💿 ")
    meta.append(f"{track['album']}", style="italic cyan")

    progress_bar = Progress(
        BarColumn(bar_width=30, style=track_grey,
                  complete_style=spotify_green, finished_style=spotify_green),
        expand=False,
        console=console
    )
    task = progress_bar.add_task("", total=track["duration"])
    progress_bar.update(task, completed=elapsed)

    icon = "▶️ " if track["is_playing"] else "⏸️ "
    progress_row = Table.grid(padding=(0, 1))
    progress_row.add_column()
    progress_row.add_column()
    progress_row.add_column(justify="right")
    progress_row.add_column()
    progress_row.add_column(justify="left")

    progress_row.add_row(
        Text(icon, style=f"bold {spotify_green}"),
        *progress_bar.get_renderables(),
        Text(format_time(elapsed), style="bold yellow"),
        Text("/", style="dim"),
        Text(format_time(track["duration"]), style="bold cyan")
    )

    device = Text(f"Device: {track['device']}", style="dim")

    return Panel(Group(meta, progress_row, device),
                 title="Spotify V3",
                 border_style=spotify_green,
                 style=background_style)


def update_search_results(query):
    global search_results, current_selection, scroll_offset
    try:
        results = sp.search(q=query, limit=10, type="track")
        search_results = [{
            "title": item["name"],
            "artist": item["artists"][0]["name"],
            "uri": item["uri"]
        } for item in results["tracks"]["items"]]
        current_selection = 0
        scroll_offset = 0
    except Exception:
        search_results = []


def display_search_panel():
    global search_query, search_results, current_selection, show_results, scroll_offset

    if not show_results:
        return Panel(
            Align.left(Text(f"/ {search_query}", style="bold green")),
            title="Search Spotify",
            border_style="cyan",
            style=background_style
        )

    table = Table.grid(expand=True)
    table.add_column(justify="left", ratio=1)
    table.add_column(justify="left", ratio=1)

    visible_tracks = search_results[scroll_offset:scroll_offset + VISIBLE_ROWS]

    for i, track in enumerate(visible_tracks):
        actual_index = scroll_offset + i
        style = "bold white" if actual_index == current_selection else "dim"
        table.add_row(track["title"], track["artist"], style=style)

    if len(search_results) > VISIBLE_ROWS:
        if current_selection >= scroll_offset + VISIBLE_ROWS:
            scroll_offset = current_selection - VISIBLE_ROWS + 1
        elif current_selection < scroll_offset:
            scroll_offset = current_selection

    search_group = Group(
        Align.left(Text(f"/ {search_query}", style="bold green")),
        table if search_results else Text("No results", style="dim red")
    )

    return Panel(
        search_group,
        title="Search & Play",
        border_style="cyan",
        style=background_style
    )


def input_thread():
    global search_query, current_selection, scroll_offset, search_results, typing_mode, show_results
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    tty.setcbreak(fd)

    try:
        while True:
            ch = sys.stdin.read(1)
            with lock:
                if typing_mode:
                    if ch == "\x7f":  # Backspace
                        search_query = search_query[:-1]
                    elif ch in ("\r", "\n"):  # Enter key
                        update_search_results(search_query)
                        typing_mode = False
                        show_results = True
                    elif ch.isprintable():  # Add typed character
                        search_query += ch
                else:
                    if ch == "\x1b":
                        next_char = sys.stdin.read(1)
                        if next_char == "[":
                            final_char = sys.stdin.read(1)
                            if final_char == "A":  # Up
                                if search_results:
                                    current_selection = (
                                        current_selection - 1) % len(search_results)
                                    if current_selection < scroll_offset:
                                        scroll_offset -= 1
                            elif final_char == "B":  # Down
                                if search_results:
                                    current_selection = (
                                        current_selection + 1) % len(search_results)
                                    if current_selection >= scroll_offset + VISIBLE_ROWS:
                                        scroll_offset += 1
                    elif ch == "j":
                        if search_results:
                            current_selection = (
                                current_selection + 1) % len(search_results)
                            if current_selection >= scroll_offset + VISIBLE_ROWS:
                                scroll_offset += 1
                    elif ch == "k":
                        if search_results:
                            current_selection = (
                                current_selection - 1) % len(search_results)
                            if current_selection < scroll_offset:
                                scroll_offset -= 1
                    elif ch in ("\r", "\n"):
                        if search_results:
                            play_track(
                                search_results[current_selection]["uri"])
                            search_query = ""
                            search_results = []
                            typing_mode = True
                            show_results = False
                            scroll_offset = 0
                    elif ch == "b":
                        search_query = ""
                        search_results = []
                        typing_mode = True
                        show_results = False
                        scroll_offset = 0

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def play_track(uri):
    try:
        devices = sp.devices()["devices"]
        if not devices:
            console.print(
                "[red]No active devices. Open Spotify somewhere bro![/red]")
            return
        device_id = devices[0]["id"]
        sp.start_playback(device_id=device_id, uris=[uri])
    except Exception as e:
        console.print(f"[red]Failed to play track:[/red] {e}")


with Live(console=console, refresh_per_second=10, screen=True) as live:
    live.update(
        Panel(
            Align.center(
                Group(
                    Text("Loading Spotify...", style="#1E90FF"),
                    Text("☕ Made with coffee by Praanesh", style="bold white")
                ),
                vertical="middle"
            ),
            style=background_style,
            border_style="cyan"
        )
    )
    time.sleep(1)

threading.Thread(target=input_thread, daemon=True).start()

with Live(console=console, refresh_per_second=20, screen=True) as live:
    last_poll = 0
    last_elapsed_update = 0
    cached_track = None
    true_elapsed = 0

    while True:
        now = time.time()

        if now - last_poll >= POLL_INTERVAL:
            playback = fetch_playback()
            if playback:
                cached_track = playback
                true_elapsed = playback["elapsed"]
            last_poll = now

        with lock:
            if cached_track:
                top = create_panel(cached_track, true_elapsed)
                bottom = display_search_panel()
                live.update(Group(top, bottom))

                if cached_track["is_playing"] and now - last_elapsed_update >= 1:
                    true_elapsed += 1
                    last_elapsed_update = now
            else:
                live.update(
                    Panel(
                        Align.center(
                            Text("This silence feels personal. Play something, will ya? 😅",
                                 style="dim white"),
                            vertical="middle"
                        ),
                        title="Spotify",
                        border_style="red",
                        style=background_style
                    )
                )

        time.sleep(0.05)
