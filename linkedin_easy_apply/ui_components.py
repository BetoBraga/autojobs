from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class ScrollablePage:
    """A viewport that also scrolls when the pointer is over its children."""

    def __init__(self, parent: ttk.Frame, *, minimum_height: int = 0):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(parent, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.content = ttk.Frame(self.canvas, padding=(2, 2, 10, 12))
        self.window = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.minimum_height = minimum_height
        self.tag = f"PageScroll:{self.canvas}"
        self.canvas.bind_class(self.tag, "<MouseWheel>", self._wheel)
        self.canvas.bind_class(self.tag, "<Button-4>", self._wheel)
        self.canvas.bind_class(self.tag, "<Button-5>", self._wheel)
        self.canvas.bind_class(self.tag, "<FocusIn>", lambda event: self.see(event.widget))
        self.content.bind("<Configure>", self._content_changed)
        self.canvas.bind("<Configure>", self._resized)
        self.install_bindings(self.canvas)

    def install_bindings(self, widget: tk.Misc) -> None:
        tags = widget.bindtags()
        if self.tag not in tags:
            widget.bindtags((self.tag,) + tags)
        for child in widget.winfo_children():
            self.install_bindings(child)

    def _content_changed(self, _event=None) -> None:
        height = max(self.canvas.winfo_height(), self.minimum_height, self.content.winfo_reqheight())
        if int(float(self.canvas.itemcget(self.window, "height") or 0)) != height:
            self.canvas.itemconfigure(self.window, height=height)
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def see(self, widget: tk.Misc) -> None:
        if not widget.winfo_ismapped() or self.content.winfo_height() <= self.canvas.winfo_height():
            return
        top = widget.winfo_rooty() - self.content.winfo_rooty()
        visible_top = self.canvas.canvasy(0)
        visible_bottom = visible_top + self.canvas.winfo_height()
        if top < visible_top:
            self.canvas.yview_moveto(max(0, top - 8) / self.content.winfo_height())
        elif top + widget.winfo_height() > visible_bottom:
            self.canvas.yview_moveto((top + min(widget.winfo_height(), self.canvas.winfo_height()) + 8 - self.canvas.winfo_height()) / self.content.winfo_height())

    def _resized(self, event) -> None:
        self.canvas.itemconfigure(
            self.window,
            width=max(1, event.width),
            height=max(event.height, self.minimum_height, self.content.winfo_reqheight()),
        )

    def reflow(self) -> None:
        self.canvas.itemconfigure(
            self.window,
            width=max(1, self.canvas.winfo_width()),
            height=max(self.canvas.winfo_height(), self.minimum_height, self.content.winfo_reqheight()),
        )
        self._content_changed()

    def _wheel(self, event):
        delta = getattr(event, "delta", 0)
        number = getattr(event, "num", None)
        if not delta and number not in (4, 5):
            return None
        direction = -1 if delta > 0 or number == 4 else 1
        widget = event.widget
        # Native lists/text scroll first; at an edge, continue through the page.
        if isinstance(widget, (tk.Text, tk.Listbox, ttk.Treeview)):
            first, last = widget.yview()
            if (direction < 0 and first > 0) or (direction > 0 and last < 1):
                return None
        first, last = self.canvas.yview()
        if last - first < 1:
            self.canvas.yview_scroll(direction * max(1, abs(delta) // 120) * 3, "units")
        return "break"


def wrap_labels(widget: tk.Misc) -> None:
    """Wrap help copy to its actual card width, not the desktop width."""
    for child in widget.winfo_children():
        if isinstance(child, ttk.Label) and int(float(child.cget("wraplength") or 0)) > 0:
            child.configure(wraplength=max(120, child.master.winfo_width() - 32))
        wrap_labels(child)
