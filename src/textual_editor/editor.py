import asyncio
import fcntl
import os
import pty
import shlex
import struct
import termios
from collections.abc import Callable
from functools import lru_cache
from typing import Any, cast

from anyio import Event, NamedTemporaryFile, wait_readable
from pyte import Screen, Stream
from rich.color import Color, parse_rgb_hex
from rich.segment import Segment
from rich.style import Style
from textual import events
from textual.geometry import Region
from textual.strip import Strip
from textual.widget import Widget
from wcwidth import wcwidth as _wcwidth

KEYS = {
    "left": "\u001b[D",
    "right": "\u001b[C",
    "up": "\u001b[A",
    "down": "\u001b[B",
    "escape": "\u001b",
    "home": "\u001b[H",
    "end": "\u001b[4~",
    "insert": "\u001b[2~",
    "delete": "\u001b[3~",
    "pageup": "\u001b[5~",
    "pagedown": "\u001b[6~",
    "ctrl+left": "\u001b[1;5C",
    "ctrl+right": "\u001b[1;5D",
    "ctrl+up": "\u001b[1;5A",
    "ctrl+down": "\u001b[1;5B",
}

wcwidth: Callable[[str], int] = lru_cache(maxsize=4096)(_wcwidth)


class Terminal:
    def __init__(self, ncol: int = 0, nrow: int = 0) -> None:
        self._screen = Screen(ncol, nrow)
        self._stream = Stream(self._screen)
        self._cache: dict[int, Strip] = {}
        self._dirty = set([i for i in range(self._screen.lines)])
        self.cursor_x = None
        self.cursor_y = None
        self._content = None

    def get_line(self, y: int) -> Strip:
        if self._content is not None:
            if y < len(self._content):
                line = self._content[y]
                segments = [Segment(c) for c in line]
                return Strip(segments)
            return Strip([])

        self._dirty.update(self._screen.dirty)
        self._screen.dirty.clear()
        if y in self._dirty:
            line = self._screen.buffer[y]
            is_wide_char = False
            segments = []
            for x in range(self._screen.columns):
                if is_wide_char:
                    is_wide_char = False
                    continue
                char = line[x].data
                assert sum(map(wcwidth, char[1:])) == 0
                is_wide_char = wcwidth(char[0]) == 2
                char = line[x]
                reverse = char.reverse
                if x == self._screen.cursor.x and y == self._screen.cursor.y:
                    reverse = not reverse
                color = get_color(char.fg)
                bgcolor = get_color(char.bg)
                segments.append(
                    Segment(
                        char.data,
                        Style(
                            color=color,
                            bgcolor=bgcolor,
                            bold=char.bold,
                            italic=char.italics,
                            underline=char.underscore,
                            blink=char.blink,
                            strike=char.strikethrough,
                            reverse=reverse,
                        ),
                    )
                )
            self._cache[y] = Strip(segments)
            self._dirty.remove(y)
        return self._cache.get(y, Strip([]))


class Editor(Widget, can_focus=True):
    def __init__(
        self,
        *args: Any,
        path: str | None = None,
        environ: str | None = None,
        language: str | None = None,
        content: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._editor = os.environ[environ] if environ else path
        self._suffix = ".txt" if language is None else f".{language}"
        self._content = content
        self._terminal: Terminal | None = None
        self._editor_created = Event()
        self._terminal_created = Event()
        self._task = asyncio.create_task(self._run())

    async def get_text(self) -> str:
        await self._tempfile.seek(0)
        content = await self._tempfile.read()
        return content

    async def set_text(self, value: str) -> None:
        await self._tempfile.seek(0)
        await self._tempfile.write(value)
        await self._tempfile.truncate()
        await self._tempfile.flush()

    def render_line(self, y: int) -> Strip:
        if self._terminal is None:
            return Strip([])
        return self._terminal.get_line(y)

    def _open_editor(self, name: str) -> int:
        pid, fd = pty.fork()
        if pid == 0:
            argv = shlex.split(f"{self._editor} {name}")
            env = dict(
                TERM="linux",
                LC_ALL="en_GB.UTF-8",
                COLUMNS=str(self._ncol),
                LINES=str(self._nrow),
            )
            os.execvpe(argv[0], argv, env)
        return fd

    async def _run(self) -> None:
        await self._terminal_created.wait()
        assert self._terminal is not None
        async with NamedTemporaryFile(mode="w+", suffix=self._suffix) as self._tempfile:
            if self._content:
                await self.set_text(self._content)
            self._editor_fd = self._open_editor(cast(str, self._tempfile.name))
            self._editor_file = os.fdopen(self._editor_fd, "w+b", 0)
            self._editor_created.set()
            data_list = []
            try:
                while True:
                    await wait_readable(self._editor_file)
                    data = self._editor_file.read(65536)
                    data_list.append(data)
                    try:
                        data = (b"".join(data_list)).decode()
                    except Exception:
                        continue
                    data_list.clear()
                    self._terminal._stream.feed(data)
                    # rerender lines where cursor moved from/to:
                    if (
                        self._terminal._screen.cursor.x != self._terminal.cursor_x
                        or self._terminal._screen.cursor.y != self._terminal.cursor_y
                    ):
                        self._terminal._screen.dirty.add(
                            self._terminal._screen.cursor.y
                        )
                        if self._terminal.cursor_y is not None:
                            self._terminal._screen.dirty.add(self._terminal.cursor_y)
                        self._terminal.cursor_x = self._terminal._screen.cursor.x
                        self._terminal.cursor_y = self._terminal._screen.cursor.y
                    # rerender dirty lines:
                    for y in set(self._terminal._screen.dirty):
                        self.refresh(Region(0, y, self._terminal._screen.columns, 1))
            except BaseException:
                await self._tempfile.seek(0)
                content = await self._tempfile.read()
                self._terminal._content = content.splitlines()
                self.refresh()

    async def on_resize(self, event: events.Resize):
        self._ncol = event.size.width
        self._nrow = event.size.height
        self._terminal = Terminal(self._ncol, self._nrow)
        self._terminal_created.set()
        await self._editor_created.wait()
        size = struct.pack("HH", self._nrow, self._ncol)
        fcntl.ioctl(self._editor_fd, termios.TIOCSWINSZ, size)

    async def on_event(self, event: events.Event) -> None:
        await super().on_event(event)

        if isinstance(event, events.Key):
            assert self._terminal is not None
            if self._terminal._content is not None:
                return

            char = KEYS.get(event.key, event.character)
            if char is None:
                return

            self._editor_file.write(char.encode())
            event.stop()
            return

        if isinstance(event, events.MouseMove):
            char = f"\x1b[<35;{event.x + 1};{event.y + 1}M"
            self._editor_file.write(char.encode())
            event.stop()
            return

        if isinstance(event, events.MouseDown):
            char = f"\x1b[<0;{event.x + 1};{event.y + 1}M"
            self._editor_file.write(char.encode())
            event.stop()
            return

        if isinstance(event, events.MouseUp):
            char = f"\x1b[<0;{event.x + 1};{event.y + 1}m"
            self._editor_file.write(char.encode())
            event.stop()
            return


def get_color(color: str) -> Color | str | None:
    try:
        return Color.from_triplet(parse_rgb_hex(color))
    except Exception:
        match color:
            case "default":
                return None
            case "brown":
                return "orange4"
        return color
