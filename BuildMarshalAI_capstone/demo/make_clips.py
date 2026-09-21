"""Assemble the short animated clips the deck plays.

Each clip is built from captured frames -- the real interface, in sequence --
rather than a mock-up. GIF is used because a slide deck plays it in an ordinary
<img>, with no player and no hosting.

A cut between two screenshots tells a viewer that something changed but not
*what was pressed*, so each transition is acted out: the pointer travels to the
control, a ring pulses under it, and only then does the next screen appear. The
coordinates are not guessed -- `capture_screens.py` records the bounding box of
every element it clicks, as a fraction of the viewport, into `gestures.json`.

    python demo/make_clips.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
SHOTS = HERE / "screens"
CLIPS = HERE / "clips"

#: Wide enough to read a heading on a slide, small enough to stay a few MB.
WIDTH = 1280

#: The accent the ripple and highlight are drawn in -- the deck's orange, which
#: appears nowhere in the application's own interface, so it never reads as UI.
MARK = (235, 104, 52)
CURSOR_FILL = (255, 255, 255)
CURSOR_EDGE = (22, 32, 43)

#: How long each kind of frame is held, in milliseconds.
HOLD_SETTLED = 1500      # a finished screen, long enough to read
HOLD_APPROACH = 260      # the pointer on its way
HOLD_PRESS = 420         # the ring at its widest

#: name -> (hold on settled frames, frames)
CLIPS_WANTED: dict[str, tuple[int, list[str]]] = {
    "chat-window-states": (1500, [
        "26c-chat-docked", "27-chat-full", "28-chat-minimised", "26c-chat-docked"]),
    "onboarding-steps": (2100, [
        "17-onboarding", "17b-onboarding-upload", "17c-onboarding-draft",
        "17d-onboarding-missing", "17e-onboarding-plan"]),
    "statistics-scroll": (1700, [
        "08-statistics-top", "09-statistics-curve", "10-statistics-flow",
        "11-statistics-risks"]),
    "report-by-phase": (1900, [
        "12b-report-baseline", "12-report-dialog", "12c-report-final"]),
    "project-tabs": (1500, [
        "03-project-overview", "04-project-people", "05-project-cost",
        "06-project-timeline", "07-project-procurement", "08-statistics-top"]),
    "workspace-google": (1900, [
        "29-google-connected", "29b-google-drive", "29c-google-drive-selected",
        "29d-google-mail", "29e-google-calendar"]),
    "workspace-microsoft": (1900, [
        "30-microsoft-connected", "30b-microsoft-drive", "30d-microsoft-mail",
        "30e-microsoft-calendar"]),
    "chat-automation": (2200, [
        "31-chat-create-project", "32-chat-create-user",
        "33-chat-schedule-meeting", "33b-chat-meeting-booked",
        "34-chat-redirect-onboarding"]),
    "storage-sweep": (2000, [
        "14-documents", "15-storage", "16-storage-reclaim"]),
}


def load(name: str) -> Image.Image | None:
    path = SHOTS / f"{name}.png"
    if not path.exists():
        print(f"    ! missing frame {name}.png")
        return None
    image = Image.open(path).convert("RGB")
    height = round(image.height * WIDTH / image.width)
    return image.resize((WIDTH, height), Image.LANCZOS)


# ── The pointer and its click ────────────────────────────────────────────

def draw_cursor(image: Image.Image, x: float, y: float, scale: float = 1.0) -> None:
    """A standard arrow pointer, white on a dark edge so it reads anywhere."""
    size = 34 * scale
    # The classic arrow, in units of its own height.
    shape = [(0.00, 0.00), (0.00, 0.72), (0.17, 0.56), (0.30, 0.86),
             (0.42, 0.81), (0.29, 0.52), (0.50, 0.50)]
    points = [(x + px * size, y + py * size) for px, py in shape]
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    pen = ImageDraw.Draw(layer)
    # A soft drop shadow keeps the pointer visible over white panels.
    shadow = [(px + 2, py + 2) for px, py in points]
    pen.polygon(shadow, fill=(22, 32, 43, 70))
    pen.polygon(points, fill=CURSOR_FILL + (255,), outline=CURSOR_EDGE + (255,))
    pen.line(points + [points[0]], fill=CURSOR_EDGE + (255,), width=max(2, int(2 * scale)))
    image.paste(Image.alpha_composite(image.convert("RGBA"), layer).convert("RGB"), (0, 0))


def draw_ripple(image: Image.Image, x: float, y: float, progress: float) -> None:
    """An expanding ring under the pointer: the moment of the press."""
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    pen = ImageDraw.Draw(layer)
    outer = 16 + 44 * progress
    fade = int(210 * (1 - progress) ** 1.3)
    pen.ellipse([x - outer, y - outer, x + outer, y + outer],
                outline=MARK + (fade,), width=max(3, int(7 * (1 - progress) + 3)))
    inner = 10 * (1 - progress) + 5
    pen.ellipse([x - inner, y - inner, x + inner, y + inner],
                fill=MARK + (int(70 * (1 - progress)),))
    image.paste(Image.alpha_composite(image.convert("RGBA"), layer).convert("RGB"), (0, 0))


def draw_target(image: Image.Image, box: tuple[float, float, float, float]) -> None:
    """A rounded outline around the control about to be pressed."""
    left, top, right, bottom = box
    pad = 6
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    pen = ImageDraw.Draw(layer)
    pen.rounded_rectangle([left - pad, top - pad, right + pad, bottom + pad],
                          radius=10, outline=MARK + (235,), width=4)
    image.paste(Image.alpha_composite(image.convert("RGBA"), layer).convert("RGB"), (0, 0))


def draw_scroll_hint(image: Image.Image, progress: float) -> None:
    """A mouse-wheel glyph with chevrons: this screen was scrolled, not clicked."""
    width, height = image.size
    x, y = width - 96, height // 2
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    pen = ImageDraw.Draw(layer)
    pen.rounded_rectangle([x - 20, y - 34, x + 20, y + 34], radius=20,
                          fill=(255, 255, 255, 235), outline=CURSOR_EDGE + (255,), width=3)
    wheel = y - 20 + 16 * progress
    pen.line([(x, wheel), (x, wheel + 13)], fill=CURSOR_EDGE + (255,), width=4)
    for step in (0, 1, 2):
        drop = y + 48 + step * 17
        fade = int(230 * max(0.0, 1 - abs(progress - step / 2.0) * 1.6))
        pen.line([(x - 12, drop), (x, drop + 9), (x + 12, drop)],
                 fill=MARK + (fade,), width=5)
    image.paste(Image.alpha_composite(image.convert("RGBA"), layer).convert("RGB"), (0, 0))


def gesture_frames(screen: Image.Image, gesture: dict | None,
                   came_from: tuple[float, float] | None
                   ) -> tuple[list[tuple[Image.Image, int]], tuple[float, float] | None]:
    """Act out, on the screen that is still showing, the gesture that leaves it."""
    if not gesture:
        return [], came_from

    width, height = screen.size
    if gesture.get("kind") == "scroll":
        return ([(apply_scroll(screen, step / 2.0), HOLD_APPROACH) for step in range(3)],
                came_from)

    x, y = gesture["x"] * width, gesture["y"] * height
    box = (( gesture["x"] - gesture.get("w", 0) / 2) * width,
           ( gesture["y"] - gesture.get("h", 0) / 2) * height,
           ( gesture["x"] + gesture.get("w", 0) / 2) * width,
           ( gesture["y"] + gesture.get("h", 0) / 2) * height)

    frames: list[tuple[Image.Image, int]] = []
    start = came_from or (width * 0.62, height * 0.86)

    # The pointer travels, easing in, so the eye can follow it to the control.
    for step, ease in enumerate((0.45, 0.78, 1.0)):
        at = (start[0] + (x - start[0]) * ease, start[1] + (y - start[1]) * ease)
        frame = screen.copy()
        if ease == 1.0:
            draw_target(frame, box)
        draw_cursor(frame, at[0], at[1])
        frames.append((frame, HOLD_APPROACH))

    # Then the press itself.
    for progress in (0.0, 0.45, 0.85):
        frame = screen.copy()
        draw_target(frame, box)
        draw_ripple(frame, x, y, progress)
        draw_cursor(frame, x, y, scale=0.92 if progress == 0.0 else 1.0)
        frames.append((frame, HOLD_PRESS if progress == 0.0 else HOLD_APPROACH))

    return frames, (x, y)


def apply_scroll(screen: Image.Image, progress: float) -> Image.Image:
    frame = screen.copy()
    draw_scroll_hint(frame, progress)
    return frame


# ── Assembly ─────────────────────────────────────────────────────────────

def build(name: str, hold: int, frames: list[str], gestures: dict) -> None:
    screens = [(frame, load(frame)) for frame in frames]
    screens = [(frame, image) for frame, image in screens if image]
    if len(screens) < 2:
        print(f"  {name}: not enough frames, skipped")
        return

    timeline: list[tuple[Image.Image, int]] = []
    pointer: tuple[float, float] | None = None
    acted = 0

    for index, (frame_name, image) in enumerate(screens):
        timeline.append((image, hold))
        if index + 1 >= len(screens):
            break
        # The gesture recorded against the NEXT frame happened on THIS screen.
        gesture = gestures.get(screens[index + 1][0])
        extra, pointer = gesture_frames(image, gesture, pointer)
        acted += bool(extra)
        timeline.extend(extra)

    target = CLIPS / f"{name}.gif"
    # One shared adaptive palette keeps the chrome from shimmering frame to frame.
    quantized = [image.quantize(colors=160, method=Image.MEDIANCUT,
                                dither=Image.FLOYDSTEINBERG)
                 for image, _ in timeline]
    quantized[0].save(target, save_all=True, append_images=quantized[1:],
                      duration=[held for _, held in timeline], loop=0,
                      optimize=True, disposal=1)
    size = target.stat().st_size
    print(f"  {size:>10,}  {name}.gif  "
          f"({len(screens)} screens, {acted} acted out, {len(timeline)} frames)")


def main() -> None:
    if not SHOTS.exists():
        sys.exit(f"No screenshots in {SHOTS}. Run demo/capture_screens.py first.")
    recorded = SHOTS / "gestures.json"
    gestures = json.loads(recorded.read_text(encoding="utf-8")) if recorded.exists() else {}
    if not gestures:
        print("  ! no gestures.json — clips will cut rather than show the click")
    CLIPS.mkdir(parents=True, exist_ok=True)
    for name, (hold, frames) in CLIPS_WANTED.items():
        build(name, hold, frames, gestures)
    total = sum(f.stat().st_size for f in CLIPS.glob("*.gif"))
    print(f"\n  {total / 1024 / 1024:.1f} MB of clips in {CLIPS}")


if __name__ == "__main__":
    main()
