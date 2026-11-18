"""The sliding switch (13.4.2): Chat | Code at the top, Ask | Cowork by Send.

One rounded track with a pill that glides to the option you pick, the way
Claude's own Chat / Code switch does.

Tk's canvas draws without anti-aliasing, so curves and diagonal lines came
out jagged. Every frame is drawn with Pillow instead, at four times the size,
and scaled down — smooth edges, crisp icons, a soft shadow under the pill —
then shown as one image on the canvas. A frame is a few hundred pixels, so
the slide stays smooth.
"""

from __future__ import annotations

import tkinter

import customtkinter as ctk

ANIMATION_MS = 180
FRAME_MS = 12
SUPERSAMPLE = 4


def _scaling(widget) -> float:
    try:
        return ctk.ScalingTracker.get_widget_scaling(widget)
    except Exception:
        return 1.0


def _ease(t: float) -> float:
    """Ease-out cubic: fast start, gentle stop."""
    return 1 - (1 - t) ** 3


_FONTS: dict = {}


def _font(size: int, bold: bool = True):
    """Segoe UI (Semibold for labels), as Windows draws its own buttons."""
    key = (size, bold)
    if key not in _FONTS:
        from PIL import ImageFont

        font = None
        for name in (("seguisb.ttf", "segoeuib.ttf", "segoeui.ttf") if bold else ("segoeui.ttf",)) + \
                ("arial.ttf", "DejaVuSans.ttf"):
            try:
                font = ImageFont.truetype(name, size)
                break
            except OSError:
                continue
        _FONTS[key] = font or ImageFont.load_default()
    return _FONTS[key]


def _hex(colour: str, alpha: int = 255) -> tuple:
    colour = (colour or "#000000").lstrip("#")
    if len(colour) == 3:
        colour = "".join(c * 2 for c in colour)
    try:
        return tuple(int(colour[i:i + 2], 16) for i in (0, 2, 4)) + (alpha,)
    except ValueError:
        return (0, 0, 0, alpha)


def draw_icon(draw, name: str, cx: float, cy: float, size: float, colour, behind) -> None:
    """Line icons with round caps. chat: a speech bubble with a small round
    bubble over its corner (the user's icon); code: </>."""
    s = size
    w = max(2, round(s * 0.09))

    def line(*points):
        draw.line(points, fill=colour, width=w, joint="curve")
        r = w / 2
        for x, y in (points[0], points[-1]):
            draw.ellipse((x - r, y - r, x + r, y + r), fill=colour)

    if name == "chat":
        draw.rounded_rectangle((cx - 0.46 * s, cy - 0.40 * s, cx + 0.26 * s, cy + 0.18 * s),
                               radius=0.20 * s, outline=colour, width=w)
        # The tail, bottom left, joined into the bubble's edge.
        draw.polygon([(cx - 0.31 * s, cy + 0.16 * s), (cx - 0.38 * s, cy + 0.40 * s),
                      (cx - 0.12 * s, cy + 0.18 * s)], fill=behind)
        line((cx - 0.31 * s, cy + 0.18 * s), (cx - 0.38 * s, cy + 0.40 * s), (cx - 0.12 * s, cy + 0.19 * s))
        # The small round bubble on top, cut out of the big one.
        draw.ellipse((cx + 0.00 * s, cy - 0.02 * s, cx + 0.44 * s, cy + 0.42 * s), fill=behind, outline=colour,
                     width=w)
    elif name == "code":
        line((cx - 0.20 * s, cy - 0.26 * s), (cx - 0.44 * s, cy), (cx - 0.20 * s, cy + 0.26 * s))
        line((cx + 0.20 * s, cy - 0.26 * s), (cx + 0.44 * s, cy), (cx + 0.20 * s, cy + 0.26 * s))
        line((cx + 0.09 * s, cy - 0.36 * s), (cx - 0.09 * s, cy + 0.36 * s))


class SlidingTabs(tkinter.Canvas):
    """A segmented switch whose highlight slides between options.

    options: (value, text) pairs, or (value, text, icon) with icon "chat" or
    "code"; an empty text makes an icon-only segment (the top bar).
    command(value) runs when the user picks one. set(value) moves the pill
    without calling command; set(None) hides it (a page that is neither).
    tips: value -> a word shown on hover, for icon-only segments.
    """

    def __init__(self, master, options, command=None, colors=None, height=34, min_width=84, font_size=13,
                 bg=None, value=None, tips=None):
        self.colors = colors or {}
        self.tips = dict(tips or {})
        self._tip = None
        self._tip_job = None
        self.options = list(options)
        self.command = command
        self.scale = _scaling(master)
        self.font_px = max(9, round(font_size * self.scale))
        self.h = round(height * self.scale)
        self.pad = max(2, round(3 * self.scale))
        self.icon_size = (height - 14) * self.scale
        font = _font(self.font_px)
        widths = []
        for option in self.options:
            text, icon = option[1], option[2] if len(option) > 2 else ""
            measured = font.getlength(text) if text else 0
            if icon:
                measured += self.icon_size + (6 * self.scale if text else 0)
            widths.append(max(min_width * self.scale, measured + (24 if text else 16) * self.scale))
        self.segment = round(max(widths))
        self.w = self.segment * len(self.options) + 2 * self.pad
        super().__init__(master, width=self.w, height=self.h, highlightthickness=0, bd=0,
                         bg=bg or self._parent_bg(master), cursor="hand2")
        self.value = value if value in self._values() else None
        self._pill_x = float(self._x_for(self.value) if self.value is not None else self.pad)
        self._anim = None
        self._hover = None
        self._photo = None
        self.bind("<Button-1>", self._click)
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda e: self._set_hover(None))
        self.draw()

    @staticmethod
    def _parent_bg(master) -> str:
        from ui.pages.base import surface

        return surface(master)

    def _values(self) -> set:
        return {option[0] for option in self.options}

    def _x_for(self, value) -> float:
        index = next((i for i, option in enumerate(self.options) if option[0] == value), 0)
        return self.pad + index * self.segment

    def _index_at(self, x: float) -> int:
        return max(0, min(len(self.options) - 1, int((x - self.pad) // self.segment)))

    # --- drawing -----------------------------------------------------------------------
    def render(self):
        """This frame as a Pillow image, drawn large and scaled down smooth."""
        from PIL import Image, ImageDraw, ImageFilter

        c = self.colors
        k = SUPERSAMPLE
        W, H, pad = self.w * k, self.h * k, self.pad * k
        image = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        track = c.get("panel", "#111827")
        pill = c.get("pill") or c.get("accent_dim", "#0e7490")
        draw.rounded_rectangle((0, 0, W - 1, H - 1), radius=H / 2, fill=_hex(track))

        x = self._pill_x * k
        box = (x, pad, x + self.segment * k, H - pad)
        if self.value is not None:
            # A soft shadow under the pill, then the pill.
            shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(shadow).rounded_rectangle((box[0], box[1] + k, box[2], box[3] + k),
                                                     radius=(H - 2 * pad) / 2, fill=(0, 0, 0, 70))
            image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(1.6 * k)))
            radius = (H - 2 * pad) / 2
            if c.get("pill_line"):
                # A flat chip with a hairline (White).
                draw.rounded_rectangle(box, radius=radius, fill=_hex(pill), outline=_hex(c["pill_line"]), width=k)
            else:
                # A coloured pill with a gentle shine: lighter at the top, its own colour below.
                mask = Image.new("L", (W, H), 0)
                ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, fill=255)
                base = _hex(pill)
                top = tuple(round(v + (255 - v) * 0.16) for v in base[:3]) + (255,)
                shine = Image.new("RGBA", (1, H))
                for row in range(H):
                    t = min(1.0, max(0.0, (row - box[1]) / max(1, (box[3] - box[1]) * 0.85)))
                    shine.putpixel((0, row), tuple(round(a + (b - a) * t) for a, b in zip(top, base)))
                image.paste(shine.resize((W, H)), (0, 0), mask)
                # A hairline of light along the top edge.
                draw.rounded_rectangle(box, radius=radius, outline=top[:3] + (90,), width=max(1, k // 2))

        font = _font(self.font_px * k)
        for index, option in enumerate(self.options):
            value, text = option[0], option[1]
            icon = option[2] if len(option) > 2 else ""
            left = (self.pad + index * self.segment) * k
            centre = left + self.segment * k / 2
            chosen = value == self.value
            colour = _hex(c.get("text", "#e2e8f0") if chosen or self._hover == index else c.get("muted", "#64748b"))
            covered = self.value is not None and abs(x - left) < self.segment * k / 2
            under = _hex(pill if covered else track)
            size = self.icon_size * k
            if icon and not text:
                draw_icon(draw, icon, centre, H / 2, size, colour, under)
                continue
            text_w = font.getlength(text)
            start = centre - (text_w + (size + 6 * self.scale * k if icon else 0)) / 2
            if icon:
                draw_icon(draw, icon, start + size / 2, H / 2, size, colour, under)
                start += size + 6 * self.scale * k
            draw.text((start, H / 2), text, font=font, fill=colour, anchor="lm")
        return image.resize((self.w, self.h), Image.LANCZOS)

    def draw(self) -> None:
        try:
            from PIL import ImageTk

            self._photo = ImageTk.PhotoImage(self.render())
        except Exception:
            return
        self.delete("all")
        self.create_image(0, 0, image=self._photo, anchor="nw")

    # --- behaviour -----------------------------------------------------------------------
    def _set_hover(self, index) -> None:
        if index != self._hover:
            self._hover = index
            self.draw()
            self._hide_tip()
            if index is not None and self.tips.get(self.options[index][0]):
                self._tip_job = self.after(450, lambda i=index: self._show_tip(i))

    def _show_tip(self, index: int) -> None:
        self._tip_job = None
        text = self.tips.get(self.options[index][0], "")
        if not text or self._hover != index:
            return
        try:
            tip = tkinter.Toplevel(self)
            tip.wm_overrideredirect(True)
            tip.attributes("-topmost", True)
            tkinter.Label(tip, text=text, bg=self.colors.get("panel", "#111827"),
                          fg=self.colors.get("text", "#e2e8f0"), font=("Segoe UI", 9), padx=8, pady=3,
                          relief="solid", bd=1).pack()
            x = self.winfo_rootx() + int(self.pad + index * self.segment)
            y = self.winfo_rooty() + int(self.h) + 4
            tip.geometry(f"+{x}+{y}")
            self._tip = tip
        except tkinter.TclError:
            self._tip = None

    def _hide_tip(self) -> None:
        if self._tip_job is not None:
            try:
                self.after_cancel(self._tip_job)
            except Exception:
                pass
            self._tip_job = None
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tkinter.TclError:
                pass
            self._tip = None

    def _motion(self, event) -> None:
        self._set_hover(self._index_at(event.x))

    def _click(self, event) -> None:
        self._hide_tip()
        value = self.options[self._index_at(event.x)][0]
        changed = value != self.value
        self.set(value)
        if self.command is not None and changed:
            self.command(value)

    def get(self):
        return self.value

    def set(self, value, animate: bool = True) -> None:
        if value not in self._values():
            value = None
        if value is None:
            self.value = None
            self.draw()
            return
        start = self._pill_x if self.value is not None else self._x_for(value)
        self.value = value
        target = self._x_for(value)
        if self._anim is not None:
            try:
                self.after_cancel(self._anim)
            except Exception:
                pass
            self._anim = None
        if not animate or abs(target - start) < 1:
            self._pill_x = target
            self.draw()
            return
        steps = max(1, ANIMATION_MS // FRAME_MS)

        def frame(n: int = 1) -> None:
            self._pill_x = start + (target - start) * _ease(n / steps)
            self.draw()
            if n < steps:
                self._anim = self.after(FRAME_MS, lambda: frame(n + 1))
            else:
                self._anim = None

        frame()

    def recolor(self, colors: dict, bg: str | None = None) -> None:
        self.colors = colors
        if bg:
            self.configure(bg=bg)
        self.draw()
