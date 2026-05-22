"""Luca - a draggable desktop dog pet built with PyQt6.

Run:
    python luca.py                 # uses the default style
    python luca.py --style chibi
    python luca.py --style realistic

Controls:
    - Single click (tap, no drag): put Luca to sleep, or wake him up
    - Left-click + drag: pick Luca up and move him around the desktop
    - Double-click: make Luca jump with joy (excited celebration)
    - Right-click: open a menu to pick a movement, change art style,
      toggle auto-behavior, toggle always-on-top, or quit
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from enum import Enum, auto
from pathlib import Path

from PIL import Image as PILImage

from PyQt6.QtCore import QElapsedTimer, QPointF, Qt, QTimer
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QTransform,
)
from PyQt6.QtWidgets import QApplication, QMenu, QWidget

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
DEFAULT_STYLE = "chibi"

REQUIRED_SPRITES = (
    "luca_idle.png",
    "luca_walk1.png",
    "luca_walk2.png",
    "luca_sit.png",
    "luca_sleep.png",
    "luca_happy.png",
)


def discover_styles() -> dict[str, Path]:
    """Find all art styles available under assets/.

    A style is a folder under `assets/` that contains every required sprite.
    The legacy top-level sprites (if present) are exposed as the "default"
    style so old installations keep working.
    """
    styles: dict[str, Path] = {}
    if ASSETS_DIR.exists():
        for sub in sorted(p for p in ASSETS_DIR.iterdir() if p.is_dir()):
            if all((sub / name).exists() for name in REQUIRED_SPRITES):
                styles[sub.name] = sub
    if all((ASSETS_DIR / name).exists() for name in REQUIRED_SPRITES):
        styles.setdefault("default", ASSETS_DIR)
    return styles


class State(Enum):
    IDLE = auto()
    WALK = auto()
    SIT = auto()
    SLEEP = auto()
    HAPPY = auto()


# Per-state animation config: (frame filenames, ms between frames).
ANIMATIONS: dict[State, tuple[list[str], int]] = {
    State.IDLE: (["luca_idle.png"], 700),
    State.WALK: (["luca_walk1.png", "luca_walk2.png"], 220),
    State.SIT: (["luca_sit.png"], 800),
    State.SLEEP: (["luca_sleep.png"], 900),
    State.HAPPY: (["luca_happy.png", "luca_idle.png"], 170),
}


def _pil_to_qpixmap(img: PILImage.Image) -> QPixmap:
    """Convert a PIL RGBA image to a QPixmap (with its own pixel buffer)."""
    rgba = img.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimg = QImage(
        data,
        rgba.width,
        rgba.height,
        rgba.width * 4,
        QImage.Format.Format_RGBA8888,
    )
    # `copy()` detaches the QImage from the (soon-to-die) Python bytes buffer.
    return QPixmap.fromImage(qimg.copy())


def _aligned_frames_to_pixmaps(paths: list[Path]) -> list[QPixmap]:
    """Normalize a sequence of animation frames into a single coordinate system.

    Different generated sprites have very different canvas sizes and the dog
    sits in different spots inside each canvas, so naively swapping frames
    every 220 ms makes Luca jump in size and position - reading as a flash.

    This function:
      1. Tight-crops each frame to its non-transparent content (the dog).
      2. Scales every frame so its dog content has the same *height* as the
         tallest frame, preserving aspect ratio. This eliminates the "dog
         shrinks/grows between frames" pop.
      3. Pastes every frame, bottom-center anchored, onto a common canvas
         sized to fit the widest scaled frame. With identical canvas
         dimensions, the paint code applies the exact same scale and the
         exact same on-screen position to every frame in the sequence.
    """
    if len(paths) == 1:
        # Single-frame "animations" don't need any cross-frame alignment.
        pix = QPixmap(str(paths[0]))
        if pix.isNull():
            raise FileNotFoundError(f"Sprite not found: {paths[0]}")
        return [pix]

    raws = [PILImage.open(p).convert("RGBA") for p in paths]
    bboxes = [im.getbbox() for im in raws]
    crops: list[PILImage.Image] = []
    for im, bbox in zip(raws, bboxes):
        crops.append(im.crop(bbox) if bbox is not None else im)

    target_h = max(c.height for c in crops)
    scaled: list[PILImage.Image] = []
    for c in crops:
        if c.height == target_h:
            scaled.append(c)
        else:
            scale = target_h / c.height
            new_w = max(1, int(round(c.width * scale)))
            scaled.append(c.resize((new_w, target_h), PILImage.Resampling.LANCZOS))

    pad = 6
    canvas_w = max(c.width for c in scaled) + pad * 2
    canvas_h = target_h + pad * 2

    pixmaps: list[QPixmap] = []
    for c in scaled:
        canvas = PILImage.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        x = (canvas_w - c.width) // 2
        y = canvas_h - c.height - pad
        canvas.paste(c, (x, y), c)
        pixmaps.append(_pil_to_qpixmap(canvas))
    return pixmaps


class Luca(QWidget):
    """A draggable, animated desktop pet."""

    WIDGET_SIZE = 200
    WALK_SPEED = 2  # pixels per movement tick

    def __init__(self, style: str | None = None) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            # Without this, macOS draws a system shadow behind the window
            # that lags one frame behind the widget while Luca walks, which
            # looks like a black ghost/halo trailing him across the desktop.
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setWindowTitle("Luca")
        self.resize(self.WIDGET_SIZE, self.WIDGET_SIZE)

        self._styles = discover_styles()
        if not self._styles:
            raise FileNotFoundError(
                f"No sprite set found under {ASSETS_DIR}. "
                "Expected files like luca_idle.png inside a style subfolder."
            )
        if style and style in self._styles:
            self._style_name = style
        elif DEFAULT_STYLE in self._styles:
            self._style_name = DEFAULT_STYLE
        else:
            self._style_name = next(iter(self._styles))

        self._sprites: dict[State, list[QPixmap]] = {}
        self._load_sprites(self._style_name)

        self._state: State = State.IDLE
        self._frame_idx: int = 0
        self._tick: int = 0
        self._facing_left: bool = False
        self._auto_mode: bool = True

        # Continuous clock for smooth sine/parabolic animations.
        self._elapsed = QElapsedTimer()
        self._elapsed.start()
        self._state_started_at: float = 0.0

        # Click vs. drag tracking. `_drag_offset` is set when the mouse goes
        # down; `_was_dragged` flips to True only after the cursor has moved
        # past a small threshold, so a quick tap doesn't get treated as drag.
        self._drag_offset = None
        self._press_pos = None
        self._was_dragged: bool = False
        self._drag_threshold: int = 4  # pixels

        # Particle overlays:
        #   z particles  -> floating "Zz" while sleeping
        #   heart particles -> floating hearts while happy/excited
        # Stored as (spawn_time, x_offset_px) tuples.
        self._z_particles: list[tuple[float, float]] = []
        self._heart_particles: list[tuple[float, float]] = []
        self._next_z_spawn: float = 0.0
        self._next_heart_spawn: float = 0.0

        self._move_to_screen_center()

        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._on_anim_tick)
        self._restart_anim_timer()

        self._move_timer = QTimer(self)
        self._move_timer.timeout.connect(self._on_move_tick)
        self._move_timer.start(16)  # ~60 FPS

        self._brain_timer = QTimer(self)
        self._brain_timer.timeout.connect(self._think)
        self._brain_timer.start(4500)

    # ----- sprites / style -----
    def _load_sprites(self, style_name: str) -> None:
        style_dir = self._styles[style_name]
        sprites: dict[State, list[QPixmap]] = {}
        for state, (files, _) in ANIMATIONS.items():
            paths = [style_dir / name for name in files]
            for p in paths:
                if not p.exists():
                    raise FileNotFoundError(f"Sprite not found: {p}")
            sprites[state] = _aligned_frames_to_pixmaps(paths)
        self._sprites = sprites

    def set_style(self, style_name: str) -> None:
        if style_name not in self._styles:
            return
        self._style_name = style_name
        self._load_sprites(style_name)
        self.update()

    # ----- positioning -----
    def _screen_geo(self):
        screen = self.screen() or QGuiApplication.primaryScreen()
        return screen.availableGeometry()

    def _move_to_screen_center(self) -> None:
        geo = self._screen_geo()
        x = geo.x() + (geo.width() - self.width()) // 2
        y = geo.y() + (geo.height() - self.height()) // 2
        self.move(x, y)

    # ----- state machine -----
    def _t(self) -> float:
        """Seconds elapsed since the app started (float)."""
        return self._elapsed.elapsed() / 1000.0

    def _state_t(self) -> float:
        """Seconds elapsed since the current state began."""
        return self._t() - self._state_started_at

    def set_state(self, state: State, *, user_initiated: bool = False) -> None:
        self._state = state
        self._frame_idx = 0
        self._tick = 0
        self._state_started_at = self._t()
        # Drop stale particles when leaving a particle-emitting state.
        if state != State.SLEEP:
            self._z_particles.clear()
        if state != State.HAPPY:
            self._heart_particles.clear()
        self._restart_anim_timer()
        if user_initiated:
            # Give the user's choice room to breathe before the brain wanders.
            self._brain_timer.start(10_000)
        self.update()

    def _restart_anim_timer(self) -> None:
        _, duration = ANIMATIONS[self._state]
        self._anim_timer.start(duration)

    def _on_anim_tick(self) -> None:
        frames, _ = ANIMATIONS[self._state]
        # WALK's frame index is driven by the bob clock in `paintEvent` so
        # the foot-plant is always phase-locked to the bounce. Other states
        # still advance on their own timer.
        if self._state != State.WALK:
            self._frame_idx = (self._frame_idx + 1) % len(frames)
        self._tick += 1
        self.update()

    def _on_move_tick(self) -> None:
        # Walk movement only when in WALK and not being held.
        if self._state == State.WALK and self._drag_offset is None:
            geo = self._screen_geo()
            dx = -self.WALK_SPEED if self._facing_left else self.WALK_SPEED
            new_x = self.x() + dx
            if new_x < geo.x():
                new_x = geo.x()
                self._facing_left = False
            elif new_x + self.width() > geo.x() + geo.width():
                new_x = geo.x() + geo.width() - self.width()
                self._facing_left = True
            self.move(new_x, self.y())

        # Repaint every tick so smooth animations (bobbing, jumping, particles)
        # advance even when no frame swap or movement happened.
        self.update()

    def _think(self) -> None:
        """Pick a random next behavior when auto-mode is on."""
        if not self._auto_mode or self._drag_offset is not None:
            return
        next_state = random.choices(
            population=[State.IDLE, State.WALK, State.SIT, State.SLEEP, State.HAPPY],
            weights=[3, 5, 2, 1, 1],
            k=1,
        )[0]
        if next_state == State.WALK:
            self._facing_left = random.random() < 0.5
        self.set_state(next_state)

    # ----- painting -----
    WALK_STEP_FREQ = 5.0  # radians/sec; one full step cycle is 2 frames

    def paintEvent(self, _event) -> None:
        frames = self._sprites[self._state]
        # Drive the walk frame from the bob clock so legs and bounce are
        # always in lockstep; for every other state, honor the timer-driven
        # frame index.
        if self._state == State.WALK:
            phase = (self._t() * self.WALK_STEP_FREQ / math.pi) % 2.0
            frame_idx = 0 if phase < 1.0 else 1
        else:
            frame_idx = self._frame_idx % len(frames)
        pixmap = frames[frame_idx]
        if self._facing_left:
            pixmap = pixmap.transformed(
                QTransform().scale(-1, 1),
                Qt.TransformationMode.SmoothTransformation,
            )

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w, h = pixmap.width(), pixmap.height()
        if w == 0 or h == 0:
            return

        # Reserve headroom so bobs and jumps don't clip at the top.
        max_w = self.width()
        max_h = self.height() - 32
        base_scale = min(max_w / w, max_h / h)

        t = self._t()
        st = self._state_t()

        # Per-state continuous transforms.
        bob_y = 0.0
        sx = 1.0
        sy = 1.0
        rotation = 0.0

        if self._state == State.IDLE:
            # Gentle breathing: slow vertical bob and a tiny chest expansion.
            bob_y = -math.sin(t * 2.0) * 2.0
            sy = 1.0 + math.sin(t * 2.0) * 0.012

        elif self._state == State.SIT:
            bob_y = -math.sin(t * 1.5) * 1.2
            sy = 1.0 + math.sin(t * 1.5) * 0.010

        elif self._state == State.WALK:
            # One bounce per step. `sin^2` is C^1 continuous (no velocity
            # cusp at the foot-plant), so the bob doesn't read as a jolt
            # the way `abs(sin)` does.
            step_freq = 5.0
            bob_y = -(math.sin(t * step_freq) ** 2) * 4.0
            # Tiny body sway, also continuous.
            rotation = math.sin(t * step_freq * 0.5) * 1.2
            if self._facing_left:
                rotation = -rotation

        elif self._state == State.HAPPY:
            # Parabolic jump cycle: peak ~28px above ground every ~0.55s.
            cycle_len = 0.55
            phase = (st / cycle_len) % 1.0
            bob_y = -math.sin(phase * math.pi) * 28.0
            # Anticipation (squat just before launch) and squash on landing.
            if phase < 0.15:
                squash = (0.15 - phase) / 0.15
                sy = 1.0 - squash * 0.10
                sx = 1.0 + squash * 0.08
            elif phase > 0.85:
                squash = (phase - 0.85) / 0.15
                sy = 1.0 - squash * 0.10
                sx = 1.0 + squash * 0.08
            else:
                stretch = math.sin((phase - 0.15) / 0.7 * math.pi)
                sy = 1.0 + stretch * 0.05
                sx = 1.0 - stretch * 0.03

        elif self._state == State.SLEEP:
            # Slow belly-breathing: subtle vertical scale only.
            sy = 1.0 + math.sin(t * 1.4) * 0.025
            sx = 1.0 - math.sin(t * 1.4) * 0.010

        draw_w = max(1, int(w * base_scale * sx))
        draw_h = max(1, int(h * base_scale * sy))
        x = (self.width() - draw_w) // 2
        y = (self.height() - draw_h) + int(round(bob_y))

        if abs(rotation) > 0.01:
            cx = self.width() / 2.0
            cy = self.height() - draw_h / 2.0
            painter.save()
            painter.translate(cx, cy)
            painter.rotate(rotation)
            painter.translate(-cx, -cy)
            painter.drawPixmap(x, y, draw_w, draw_h, pixmap)
            painter.restore()
        else:
            painter.drawPixmap(x, y, draw_w, draw_h, pixmap)

        # Particle overlays.
        if self._state == State.SLEEP:
            self._tick_z_particles(t)
            self._draw_z_particles(painter, t)
        elif self._state == State.HAPPY:
            self._tick_heart_particles(t)
            self._draw_heart_particles(painter, t)

    # ----- particles -----
    Z_LIFETIME = 2.2  # seconds
    HEART_LIFETIME = 1.6

    def _tick_z_particles(self, t: float) -> None:
        if t >= self._next_z_spawn:
            self._z_particles.append((t, random.uniform(-6.0, 14.0)))
            self._next_z_spawn = t + random.uniform(0.8, 1.4)
        self._z_particles = [
            p for p in self._z_particles if t - p[0] < self.Z_LIFETIME
        ]

    def _draw_z_particles(self, painter: QPainter, t: float) -> None:
        if not self._z_particles:
            return
        base_x = self.width() * 0.62
        base_y = self.height() * 0.30
        for spawn_t, x_off in self._z_particles:
            age = t - spawn_t
            if age < 0:
                continue
            progress = age / self.Z_LIFETIME  # 0 -> 1
            # Rise and slight rightward drift, fade out as it grows.
            dy = -progress * 48.0
            dx = x_off + math.sin(age * 2.5) * 3.0
            size = 14 + progress * 10
            # Fade in fast, hold, fade out.
            if progress < 0.15:
                alpha = progress / 0.15
            else:
                alpha = max(0.0, 1.0 - (progress - 0.15) / 0.85)
            color = QColor(80, 140, 240, int(alpha * 220))
            painter.save()
            font = QFont("Helvetica", int(size), QFont.Weight.Bold)
            painter.setFont(font)
            painter.setPen(color)
            painter.drawText(QPointF(base_x + dx, base_y + dy), "Z")
            painter.restore()

    def _tick_heart_particles(self, t: float) -> None:
        if t >= self._next_heart_spawn:
            self._heart_particles.append((t, random.uniform(-30.0, 30.0)))
            self._next_heart_spawn = t + random.uniform(0.35, 0.6)
        self._heart_particles = [
            p for p in self._heart_particles if t - p[0] < self.HEART_LIFETIME
        ]

    def _draw_heart_particles(self, painter: QPainter, t: float) -> None:
        if not self._heart_particles:
            return
        base_x = self.width() / 2.0
        base_y = self.height() * 0.35
        for spawn_t, x_off in self._heart_particles:
            age = t - spawn_t
            if age < 0:
                continue
            progress = age / self.HEART_LIFETIME
            dy = -progress * 60.0
            dx = x_off + math.sin(age * 3.0 + x_off) * 6.0
            size = 10.0 + progress * 8.0
            if progress < 0.2:
                alpha = progress / 0.2
            else:
                alpha = max(0.0, 1.0 - (progress - 0.2) / 0.8)
            self._paint_heart(
                painter,
                QPointF(base_x + dx, base_y + dy),
                size,
                QColor(255, 105, 140, int(alpha * 230)),
            )

    @staticmethod
    def _paint_heart(
        painter: QPainter, center: QPointF, size: float, color: QColor
    ) -> None:
        """Draw a simple cartoon heart centered on the given point."""
        path = QPainterPath()
        s = size
        # Build a heart shape via two cubic curves meeting at the bottom point.
        top_dip = QPointF(center.x(), center.y() - s * 0.25)
        bottom = QPointF(center.x(), center.y() + s * 0.85)
        left_top = QPointF(center.x() - s * 1.0, center.y() - s * 0.85)
        right_top = QPointF(center.x() + s * 1.0, center.y() - s * 0.85)
        left_mid = QPointF(center.x() - s * 1.0, center.y() + s * 0.05)
        right_mid = QPointF(center.x() + s * 1.0, center.y() + s * 0.05)
        path.moveTo(top_dip)
        path.cubicTo(left_top, left_mid, bottom)
        path.cubicTo(right_mid, right_top, top_dip)
        painter.save()
        painter.setBrush(QBrush(color))
        painter.setPen(QPen(QColor(0, 0, 0, color.alpha() // 3), 1.2))
        painter.drawPath(path)
        painter.restore()

    # ----- mouse -----
    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        global_pos = event.globalPosition().toPoint()
        self._press_pos = global_pos
        self._drag_offset = global_pos - self.pos()
        self._was_dragged = False

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is None or self._press_pos is None:
            return
        global_pos = event.globalPosition().toPoint()
        if not self._was_dragged:
            moved = (global_pos - self._press_pos).manhattanLength()
            if moved < self._drag_threshold:
                return
            self._was_dragged = True
            # Picking him up: excited reaction.
            self.set_state(State.HAPPY, user_initiated=True)

        target = global_pos - self._drag_offset
        geo = self._screen_geo()
        x = max(geo.x(), min(target.x(), geo.x() + geo.width() - self.width()))
        y = max(geo.y(), min(target.y(), geo.y() + geo.height() - self.height()))
        self.move(x, y)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        was_drag = self._was_dragged
        self._drag_offset = None
        self._press_pos = None
        self._was_dragged = False
        if was_drag:
            # After a drag, settle back to idle.
            self.set_state(State.IDLE, user_initiated=True)
        else:
            self._on_tap()

    def mouseDoubleClickEvent(self, _event) -> None:
        # A double-click overrides any pending tap-to-sleep with a celebration.
        self._heart_particles.clear()
        self.set_state(State.HAPPY, user_initiated=True)

    def _on_tap(self) -> None:
        """A single tap (no drag): toggle sleep / wake."""
        if self._state == State.SLEEP:
            # Wake up gently.
            self.set_state(State.IDLE, user_initiated=True)
        else:
            # Tuck him in for a nap.
            self.set_state(State.SLEEP, user_initiated=True)

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)

        actions = [
            ("Idle", State.IDLE),
            ("Walk around", State.WALK),
            ("Sit", State.SIT),
            ("Sleep", State.SLEEP),
            ("Be excited!", State.HAPPY),
        ]
        for label, st in actions:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(self._state == st)
            action.triggered.connect(
                lambda _checked=False, s=st: self.set_state(s, user_initiated=True)
            )

        menu.addSeparator()

        if len(self._styles) > 1:
            style_menu = menu.addMenu("Art style")
            for name in self._styles:
                style_action = style_menu.addAction(name.capitalize())
                style_action.setCheckable(True)
                style_action.setChecked(name == self._style_name)
                style_action.triggered.connect(
                    lambda _checked=False, n=name: self.set_style(n)
                )

        flip_action = menu.addAction("Face the other way")
        flip_action.triggered.connect(self._flip_direction)

        auto_action = menu.addAction("Auto behavior")
        auto_action.setCheckable(True)
        auto_action.setChecked(self._auto_mode)
        auto_action.toggled.connect(self._set_auto_mode)

        top_action = menu.addAction("Always on top")
        top_action.setCheckable(True)
        top_action.setChecked(
            bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        )
        top_action.toggled.connect(self._set_always_on_top)

        menu.addSeparator()
        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(QApplication.instance().quit)

        menu.exec(event.globalPos())

    # ----- menu handlers -----
    def _flip_direction(self) -> None:
        self._facing_left = not self._facing_left
        self.update()

    def _set_auto_mode(self, on: bool) -> None:
        self._auto_mode = on
        if on:
            self._brain_timer.start(4500)

    def _set_always_on_top(self, on: bool) -> None:
        flags = self.windowFlags()
        if on:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        was_visible = self.isVisible()
        self.setWindowFlags(flags)
        if was_visible:
            self.show()


def main() -> int:
    parser = argparse.ArgumentParser(description="Luca the desktop dog pet.")
    parser.add_argument(
        "--style",
        choices=sorted(discover_styles().keys()) or None,
        default=None,
        help="Art style to load (default: chibi if available, else first found).",
    )
    args, qt_args = parser.parse_known_args()

    app = QApplication([sys.argv[0], *qt_args])
    app.setQuitOnLastWindowClosed(True)
    pet = Luca(style=args.style)
    pet.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
