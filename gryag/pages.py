"""A transcript drawn onto pages, so the model reads it as a picture.

Measured on 2026-10-26 over the chat's last 989 messages: as plain text they are 18,981
input tokens; drawn two columns to a 1536x2048 page they are five pages, and a page costs
a flat ~570 tokens at medium resolution or ~1,090 at high, whatever is on it. The picture
is the cheaper way to hand the model a long transcript, by a factor of three to seven.

The names in this chat are written in mathematical alphanumerics, Cyrillic and emoji, and
no single font has all of that. Each character is drawn in the first font that has it,
and emoji come from Noto Color Emoji, which only exists as a 109px bitmap and is scaled
down to the line. A tofu box where a name should be is a name the model cannot cite.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger(__name__)

FONT_DIRS = ("/usr/share/fonts/truetype", "/usr/share/fonts/opentype")

FALLBACK = (
    # Condensed first: two columns of a chat fit only if the body face is narrow.
    "dejavu/DejaVuSansCondensed.ttf",
    "noto/NotoSans-Regular.ttf",
    "noto/NotoSansMath-Regular.ttf",
    "noto/NotoSansSymbols-Regular.ttf",
    "noto/NotoSansSymbols2-Regular.ttf",
    "dejavu/DejaVuSans.ttf",
    # Covers the whole Basic Multilingual Plane, badly. Better than a box.
    "unifont/unifont.otf",
    "unifont/unifont_upper.otf",
)
EMOJI = "noto/NotoColorEmoji.ttf"
EMOJI_PX = 109
"""The only size the emoji font has; asking for any other fails to load it."""

# Joiners, variation selectors and skin tones change how an emoji looks, not what it is.
# Dropping them draws a family as its members and a thumbs-up in the default yellow.
INVISIBLE = {0x200D, 0xFE0E, 0xFE0F, *range(0x1F3FB, 0x1F400)}

WIDTH = 1536
HEIGHT = 2048
COLUMNS = 2
FONT_PX = 14


def _find(name: str) -> Path | None:
    for root in FONT_DIRS:
        path = Path(root) / name
        if path.exists():
            return path
    return None


@lru_cache(maxsize=None)
def _cmap(path: Path) -> frozenset[int]:
    return frozenset(TTFont(path, lazy=True, fontNumber=0).getBestCmap() or {})


@dataclass(frozen=True)
class _Face:
    font: ImageFont.FreeTypeFont
    chars: frozenset[int]


@lru_cache(maxsize=None)
def _faces(size: int) -> tuple[tuple[_Face, ...], _Face | None]:
    faces = []
    for name in FALLBACK:
        path = _find(name)
        if path is None:
            continue
        font = ImageFont.truetype(str(path), size, layout_engine=ImageFont.Layout.BASIC)
        faces.append(_Face(font, _cmap(path)))
    if not faces:
        raise RuntimeError("no fonts found for the transcript pages")
    emoji_path = _find(EMOJI)
    emoji = (
        _Face(ImageFont.truetype(str(emoji_path), EMOJI_PX), _cmap(emoji_path))
        if emoji_path
        else None
    )
    return tuple(faces), emoji


@dataclass
class _Run:
    """Consecutive characters drawn in one face. `face` None is an emoji."""

    face: _Face | None
    text: str


class Typesetter:
    def __init__(self, size: int = FONT_PX):
        self.size = size
        self.faces, self.emoji = _faces(size)
        self._emoji_cache: dict[str, Image.Image] = {}

    def _face_for(self, ch: str) -> _Face | None:
        code = ord(ch)
        # Emoji presentation wins over a text glyph: DejaVu has a black-and-white ☕ that
        # nobody in the chat meant.
        if self.emoji is not None and code >= 0x1F000 and code in self.emoji.chars:
            return None
        for face in self.faces:
            if code in face.chars:
                return face
        if self.emoji is not None and code in self.emoji.chars:
            return None
        return self.faces[0]

    def runs(self, text: str) -> list[_Run]:
        runs: list[_Run] = []
        for ch in text:
            if ord(ch) in INVISIBLE:
                continue
            face = self._face_for(ch)
            if runs and runs[-1].face is face and face is not None:
                runs[-1].text += ch
            else:
                runs.append(_Run(face, ch))
        return runs

    def width(self, text: str) -> float:
        return sum(self._run_width(r) for r in self.runs(text))

    def _run_width(self, run: _Run) -> float:
        if run.face is None:
            return self.size * 1.2
        return run.face.font.getlength(run.text)

    def _emoji(self, ch: str) -> Image.Image:
        cached = self._emoji_cache.get(ch)
        if cached is None:
            canvas = Image.new("RGBA", (EMOJI_PX * 2, EMOJI_PX * 2), (0, 0, 0, 0))
            ImageDraw.Draw(canvas).text(
                (0, 0), ch, font=self.emoji.font, embedded_color=True
            )
            box = canvas.getbbox() or (0, 0, 1, 1)
            glyph = canvas.crop(box)
            side = self.size + 1
            glyph.thumbnail((side, side), Image.LANCZOS)
            cached = self._emoji_cache[ch] = glyph
        return cached

    def draw(self, image: Image.Image, xy: tuple[float, float], text: str) -> None:
        draw = ImageDraw.Draw(image)
        x, y = xy
        for run in self.runs(text):
            if run.face is None:
                glyph = self._emoji(run.text)
                image.paste(glyph, (int(x), int(y + 1)), glyph)
            else:
                draw.text((x, y), run.text, font=run.face.font, fill=(0, 0, 0))
            x += self._run_width(run)

    def wrap(self, line: str, width: float) -> list[str]:
        """Word wrap, with continuation lines indented so a message's start stays visible."""
        out: list[str] = []
        current = ""
        for word in line.split(" "):
            candidate = f"{current} {word}" if current else word
            if not current or self.width(candidate) <= width:
                current = candidate
            else:
                out.append(current)
                current = "   " + word
        out.append(current)
        return out


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "PNG", optimize=True)
    return buffer.getvalue()


def render(
    lines: list[str],
    *,
    width: int = WIDTH,
    height: int = HEIGHT,
    columns: int = COLUMNS,
    size: int = FONT_PX,
    pad: int = 8,
    gap: int = 16,
) -> list[bytes]:
    """PNG pages, filled column by column. A message's own line breaks become ` / `."""
    setter = Typesetter(size)
    line_height = int(size * 1.25)
    column_width = (width - 2 * pad - gap * (columns - 1)) // columns
    rows = (height - 2 * pad) // line_height

    wrapped: list[str] = []
    for line in lines:
        wrapped.extend(setter.wrap(line.replace("\n", " / "), column_width))

    per_page = rows * columns
    pages = []
    for start in range(0, len(wrapped), per_page):
        image = Image.new("RGB", (width, height), "white")
        for index, text in enumerate(wrapped[start : start + per_page]):
            column, row = divmod(index, rows)
            setter.draw(
                image, (pad + column * (column_width + gap), pad + row * line_height), text
            )
        pages.append(_png(image))
    return pages


def contact_sheet(
    photos: list[tuple[str, bytes]],
    *,
    width: int = WIDTH,
    height: int = HEIGHT,
    grid: tuple[int, int] = (2, 3),
    size: int = 28,
) -> list[bytes]:
    """Photos tiled several to a page, each under its label, so one page's flat token
    price covers several of them. Unreadable files are skipped, not fatal."""
    columns, rows = grid
    label_height = int(size * 1.4)
    cell_w, cell_h = width // columns, height // rows
    setter = Typesetter(size)
    pages = []
    per_page = columns * rows
    for start in range(0, len(photos), per_page):
        sheet = Image.new("RGB", (width, height), "white")
        for index, (label, payload) in enumerate(photos[start : start + per_page]):
            column, row = divmod(index, rows)
            x, y = column * cell_w, row * cell_h
            try:
                photo = Image.open(io.BytesIO(payload)).convert("RGB")
            except Exception as exc:
                log.debug("skipping unreadable photo %s: %s", label, exc)
                continue
            photo.thumbnail((cell_w - 12, cell_h - label_height - 12))
            sheet.paste(photo, (x + 6, y + label_height + 4))
            setter.draw(sheet, (x + 6, y + 4), label)
        pages.append(_png(sheet))
    return pages
