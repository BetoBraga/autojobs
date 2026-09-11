from __future__ import annotations

import logging
import math
import queue
import sys
import threading
import time
import tkinter as tk
import webbrowser
from collections import deque
from copy import deepcopy
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from linkedin_easy_apply.bot import EasyApplyBot
from linkedin_easy_apply.browser import build_chrome_driver, deep_query_all
from linkedin_easy_apply.config import (
    AppConfig,
    DATE_FILTERS,
    EXPERIENCE_LEVELS,
    WORK_TYPES,
    RECOMMENDED_MIN_DELAY_SECONDS,
    RECOMMENDED_MAX_DELAY_SECONDS,
    app_data_dir,
    normalize_question,
    delay_is_aggressive,
    delay_warning_text,
)
from linkedin_easy_apply.models import JobInfo, RunStats
from linkedin_easy_apply.question_catalog import CATEGORIES, QUESTION_BY_KEY, QUESTION_CATALOG, QuestionDefinition
from linkedin_easy_apply.themes import load_themes, themes_file_path, executable_dir
from linkedin_easy_apply.logging_utils import CappedFileHandler, log_file_path
from linkedin_easy_apply.presentation import (
    friendly_run_message, friendly_result_reason, load_application_history, safe_application_url,
)
from linkedin_easy_apply.ui_components import ScrollablePage, wrap_labels

APP_TITLE = "Autojobs"
UI_DATE_FILTERS = {"Any time": "", "Past 24 hours": "r86400", "Past week": "r604800", "Past month": "r2592000"}
UI_EXPERIENCE_LEVELS = {1: "Internship", 2: "Entry level", 3: "Junior / associate", 4: "Mid / senior level", 5: "Director", 6: "Executive"}
UI_WORK_TYPES = {1: "On-site", 2: "Remote", 3: "Hybrid"}
SOCIAL_STRATEGY_LABELS = {
    "Prefer not to say": "prefer_not_to_say",
    "Use my general answers": "use_defaults",
}
RUN_MODE_LABELS = {
    "Guided (recommended)": "supervised",
    "Automatic": "automatic",
}


@dataclass(frozen=True)
class ScreenRect:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def center_x(self) -> int:
        return self.x + self.width // 2

    @property
    def center_y(self) -> int:
        return self.y + self.height // 2

    def contains(self, other: "ScreenRect") -> bool:
        return (
            self.x <= other.x
            and self.y <= other.y
            and self.right >= other.right
            and self.bottom >= other.bottom
        )

    def intersects(self, other: "ScreenRect") -> bool:
        return (
            self.x < other.right
            and self.right > other.x
            and self.y < other.bottom
            and self.bottom > other.y
        )

    def intersection(self, other: "ScreenRect") -> "ScreenRect | None":
        left = max(self.x, other.x)
        top = max(self.y, other.y)
        right = min(self.right, other.right)
        bottom = min(self.bottom, other.bottom)
        if right <= left or bottom <= top:
            return None
        return ScreenRect(left, top, right - left, bottom - top)

    def expanded(self, padding: int) -> "ScreenRect":
        return ScreenRect(
            self.x - padding,
            self.y - padding,
            self.width + padding * 2,
            self.height + padding * 2,
        )


def find_onboarding_position(
    screen: ScreenRect,
    focus: ScreenRect | None,
    width: int,
    height: int,
    *,
    margin: int = 24,
) -> ScreenRect | None:
    """Return a screen position for the guide that leaves the focused area clear."""
    usable = ScreenRect(
        screen.x + margin,
        screen.y + margin,
        max(0, screen.width - margin * 2),
        max(0, screen.height - margin * 2),
    )
    if width <= 0 or height <= 0 or width > usable.width or height > usable.height:
        return None

    if focus is None:
        return ScreenRect(
            usable.x + (usable.width - width) // 2,
            usable.y + (usable.height - height) // 2,
            width,
            height,
        )

    def clamp(value: int, lower: int, upper: int) -> int:
        return max(lower, min(value, upper))

    max_x = usable.right - width
    max_y = usable.bottom - height
    candidates = (
        ScreenRect(
            focus.right + margin,
            clamp(focus.center_y - height // 2, usable.y, max_y),
            width,
            height,
        ),
        ScreenRect(
            focus.x - margin - width,
            clamp(focus.center_y - height // 2, usable.y, max_y),
            width,
            height,
        ),
        ScreenRect(
            clamp(focus.center_x - width // 2, usable.x, max_x),
            focus.bottom + margin,
            width,
            height,
        ),
        ScreenRect(
            clamp(focus.center_x - width // 2, usable.x, max_x),
            focus.y - margin - height,
            width,
            height,
        ),
    )
    visible = [candidate for candidate in candidates if usable.contains(candidate) and not candidate.intersects(focus)]
    if not visible:
        return None
    return min(
        visible,
        key=lambda candidate: abs(candidate.center_x - focus.center_x) + abs(candidate.center_y - focus.center_y),
    )


def application_asset_path(filename: str) -> Path:
    bundle_dir = Path(getattr(sys, "_MEIPASS", executable_dir()))
    bundled_path = bundle_dir / "assets" / filename
    if bundled_path.is_file():
        return bundled_path
    return executable_dir() / "assets" / filename


def load_application_logo(master: tk.Misc, max_dimension: int) -> tk.PhotoImage | None:
    try:
        image = tk.PhotoImage(master=master, file=str(application_asset_path("logo-autojobs.png")))
    except tk.TclError:
        return None
    scale = max(1, (max(image.width(), image.height()) + max_dimension - 1) // max_dimension)
    return image.subsample(scale, scale)


def apply_application_icon(window: tk.Tk | tk.Toplevel) -> None:
    icon_path = application_asset_path("favicon-autojobs.ico")
    if not icon_path.is_file():
        return
    try:
        window.iconbitmap(default=str(icon_path))
    except tk.TclError:
        pass


@dataclass
class QuestionRequest:
    question: str
    choices: list[str]
    default: str
    done: threading.Event
    answer: str | None = None


@dataclass
class ConfirmRequest:
    job: JobInfo
    done: threading.Event
    approved: bool = False


class QueueLogHandler(logging.Handler):
    def __init__(self, ui_queue: queue.Queue):
        super().__init__()
        self.ui_queue = ui_queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.ui_queue.put(("log", record.getMessage(), record.levelno))
        except Exception:
            self.handleError(record)


class ChoiceDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, question: str, choices: list[str], default: str = ""):
        super().__init__(parent)
        self.title("An answer is needed — Easy Apply")
        self.resizable(True, False)
        self.transient(parent)
        self.grab_set()
        self.result: str | None = None
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        body = ttk.Frame(self, padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="We need an answer from you", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(
            body,
            text="The search is paused. Answer below to continue. We will reuse your answer during this search and save it on this computer when the search ends.",
            wraplength=690,
        ).pack(anchor="w", pady=(4, 14))
        ttk.Separator(body).pack(fill="x", pady=(0, 14))
        ttk.Label(body, text=question, wraplength=700, justify="left", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 10))

        self.value = tk.StringVar(value=default)
        if choices:
            widget = ttk.Combobox(body, textvariable=self.value, values=choices, state="normal", width=80)
            if default in choices:
                widget.set(default)
        else:
            widget = ttk.Entry(body, textvariable=self.value, width=82)
        widget.pack(fill="x")
        widget.focus_set()

        ttk.Label(
            body,
            text="If choices are available, use the same wording as LinkedIn.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(8, 16))

        buttons = ttk.Frame(body)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Skip this application", command=self._cancel).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="Use this answer", command=self._ok).pack(side="right")
        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self._cancel())
        self.update_idletasks()
        width = max(760, self.winfo_reqwidth())
        height = self.winfo_reqheight()
        x = max(0, (self.winfo_screenwidth() - width) // 2)
        y = max(0, (self.winfo_screenheight() - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.lift()
        self.attributes("-topmost", True)
        self.after(250, lambda: self.attributes("-topmost", False))
        self.wait_window(self)

    def _ok(self) -> None:
        value = self.value.get().strip()
        if not value:
            messagebox.showwarning("An answer is needed", "Choose or type an answer. You can also skip this application.", parent=self)
            return
        self.result = value
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


class CatalogAnswerDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, definition: QuestionDefinition, current: str = ""):
        super().__init__(parent)
        self.title("Configure optional answer")
        self.transient(parent)
        self.grab_set()
        self.resizable(True, False)
        self.result: str | None = None
        self.definition = definition

        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=definition.label, font=("Segoe UI", 11, "bold"), wraplength=620).pack(anchor="w")
        ttk.Label(body, text=definition.category, style="Muted.TLabel").pack(anchor="w", pady=(2, 10))
        if definition.help_text:
            ttk.Label(body, text=definition.help_text, wraplength=620).pack(anchor="w", pady=(0, 10))

        self.value = tk.StringVar(value=current)
        if definition.choices:
            self.widget = ttk.Combobox(body, textvariable=self.value, values=list(definition.choices), state="normal", width=70)
        else:
            self.widget = ttk.Entry(body, textvariable=self.value, width=72)
        self.widget.pack(fill="x")
        self.widget.focus_set()

        if definition.social:
            ttk.Label(
                body,
                text="Sensitive/social field: this application never infers an answer. Configure only what you want to disclose.",
                style="Muted.TLabel",
                wraplength=620,
            ).pack(anchor="w", pady=(8, 0))

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(16, 0))
        ttk.Button(buttons, text="Cancel", command=self._cancel).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="Save", command=self._ok).pack(side="right")
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Return>", lambda _e: self._ok())
        self.update_idletasks()
        self.geometry(f"{max(680, self.winfo_reqwidth())}x{self.winfo_reqheight()}")
        self.wait_window(self)

    def _ok(self) -> None:
        self.result = self.value.get().strip()
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()



class HoverTooltip:
    def __init__(self, widget: tk.Misc, text: str, *, width: int = 520):
        self.widget = widget
        self.text = text
        self.width = width
        self.tip: tk.Toplevel | None = None
        self.after_id = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")

    def _schedule(self, _event=None) -> None:
        self.hide()
        try:
            self.after_id = self.widget.after(450, self.show)
        except Exception:
            pass

    def show(self) -> None:
        if self.tip is not None:
            return
        try:
            x = self.widget.winfo_rootx() + 10
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        except Exception:
            return
        tip = tk.Toplevel(self.widget)
        self.tip = tip
        tip.overrideredirect(True)
        try:
            tip.attributes("-topmost", True)
        except Exception:
            pass
        frame = ttk.Frame(tip, padding=12, style="Tooltip.TFrame")
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=self.text, justify="left", wraplength=self.width, style="Tooltip.TLabel").pack(anchor="w")
        tip.geometry(f"+{x}+{y}")

    def hide(self, _event=None) -> None:
        if self.after_id is not None:
            try:
                self.widget.after_cancel(self.after_id)
            except Exception:
                pass
            self.after_id = None
        if self.tip is not None:
            try:
                self.tip.destroy()
            except Exception:
                pass
            self.tip = None


class CustomAnswerDialog(tk.Toplevel):
    """One reliable editor for custom/learned question answers."""
    def __init__(self, parent: tk.Misc, *, question: str = "", answer: str = ""):
        super().__init__(parent)
        self.title("Add a question")
        self.transient(parent)
        self.grab_set()
        self.resizable(True, False)
        self.result: tuple[str, str] | None = None
        body = ttk.Frame(self, padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Which question would you like to prepare?", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(
            body,
            text="Copy the question as it appears on LinkedIn and add your answer. This answer takes priority over general answers.",
            style="Muted.TLabel", wraplength=650, justify="left",
        ).pack(anchor="w", pady=(3, 14))
        ttk.Label(body, text="Question", style="Section.TLabel").pack(anchor="w")
        self.question_var = tk.StringVar(value=question)
        q = ttk.Entry(body, textvariable=self.question_var)
        q.pack(fill="x", pady=(3, 10))
        ttk.Label(body, text="Answer", style="Section.TLabel").pack(anchor="w")
        self.answer_var = tk.StringVar(value=answer)
        a = ttk.Entry(body, textvariable=self.answer_var)
        a.pack(fill="x", pady=(3, 5))
        ttk.Label(body, text="For questions with choices, use the same wording as LinkedIn.", style="Muted.TLabel").pack(anchor="w")
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(18, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="Done", style="Accent.TButton", command=self._save).pack(side="right")
        q.focus_set()
        self.bind("<Return>", lambda _e: self._save())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.update_idletasks()
        self.geometry(f"{max(700, self.winfo_reqwidth())}x{self.winfo_reqheight()}")
        self.wait_window(self)

    def _save(self) -> None:
        q = self.question_var.get().strip()
        a = self.answer_var.get().strip()
        if not q or not a:
            messagebox.showwarning("Question and answer required", "Enter both the recruiter question and the answer to remember.", parent=self)
            return
        self.result = (q, a)
        self.destroy()


class HighlightOverlay:
    PADDING = 5
    THICKNESS = 3

    def __init__(self, parent: tk.Misc):
        self.parent = parent
        self.frames: list[tk.Frame] = []

    def clear(self) -> None:
        for frame in self.frames:
            try:
                frame.destroy()
            except Exception:
                pass
        self.frames = []

    def _visible_widget_rect(self, widget: tk.Misc) -> ScreenRect | None:
        try:
            widget.update_idletasks()
            if not widget.winfo_viewable():
                return None
            rect = ScreenRect(
                widget.winfo_rootx(),
                widget.winfo_rooty(),
                widget.winfo_width(),
                widget.winfo_height(),
            )
            clips = [
                ScreenRect(
                    self.parent.winfo_rootx(),
                    self.parent.winfo_rooty(),
                    self.parent.winfo_width(),
                    self.parent.winfo_height(),
                )
            ]
            ancestor = widget.master
            while ancestor is not None:
                if isinstance(ancestor, tk.Canvas):
                    clips.append(
                        ScreenRect(
                            ancestor.winfo_rootx(),
                            ancestor.winfo_rooty(),
                            ancestor.winfo_width(),
                            ancestor.winfo_height(),
                        )
                    )
                if ancestor is self.parent:
                    break
                ancestor = getattr(ancestor, "master", None)
        except Exception:
            return None

        visible = rect.expanded(self.PADDING)
        for clip in clips:
            visible = visible.intersection(clip)
            if visible is None:
                return None
        if visible.width < self.THICKNESS * 2 or visible.height < self.THICKNESS * 2:
            return None
        return visible

    @staticmethod
    def _combined_rect(rectangles: list[ScreenRect]) -> ScreenRect | None:
        if not rectangles:
            return None
        left = min(rect.x for rect in rectangles)
        top = min(rect.y for rect in rectangles)
        right = max(rect.right for rect in rectangles)
        bottom = max(rect.bottom for rect in rectangles)
        return ScreenRect(left, top, right - left, bottom - top)

    def show(self, targets: tk.Misc | tuple[tk.Misc | None, ...], color: str = "#2F80ED") -> ScreenRect | None:
        self.clear()
        widgets = targets if isinstance(targets, tuple) else (targets,)
        rectangles: list[ScreenRect] = []
        for widget in widgets:
            if widget is None:
                continue
            rect = self._visible_widget_rect(widget)
            if rect is not None:
                rectangles.append(rect)
        try:
            parent_x = self.parent.winfo_rootx()
            parent_y = self.parent.winfo_rooty()
        except Exception:
            return self._combined_rect(rectangles)
        for rect in rectangles:
            specs = [
                (rect.x, rect.y, rect.width, self.THICKNESS),
                (rect.x, rect.bottom - self.THICKNESS, rect.width, self.THICKNESS),
                (rect.x, rect.y, self.THICKNESS, rect.height),
                (rect.right - self.THICKNESS, rect.y, self.THICKNESS, rect.height),
            ]
            for bx, by, bw, bh in specs:
                frame = tk.Frame(self.parent, background=color, borderwidth=0, highlightthickness=0)
                frame.place(x=bx - parent_x, y=by - parent_y, width=bw, height=bh)
                try:
                    frame.lift()
                except tk.TclError:
                    pass
                self.frames.append(frame)
        return self._combined_rect(rectangles)


class HelpCenterDialog(tk.Toplevel):
    TOPICS = {
        "Start here": (
            "1. Open LinkedIn login and finish login/2FA in the visible Chrome window.\n"
            "2. In 1. Search & Browser, configure job titles, exact locations, CV and run settings.\n"
            "3. In 2. Answer Rules, fill as many answers as possible.\n"
            "4. Start with Supervised mode and visible Chrome. Only switch to Automatic/headless after a successful test."
        ),
        "Jobs outside my location": (
            "Keep one location per line. The location is sent to LinkedIn as a SEARCH SCOPE, not a hard application gate. By default autojobs will continue every job LinkedIn returns, even when the opened page says Remote, Ireland, another place, or has no usable location metadata. "
            "The optional post-open conflict checkbox is off by default and Expand my search turns it off. Enable it only if you intentionally want an extra location rejection layer."
        ),
        "A question is not being answered": (
            "Use Supervised mode first. autojobs should bring this window to the front and ask you. Save the answer and it becomes a Learned Answer. "
            "You can also use Add custom exact question in Answer Rules. For dropdown/radio fields, use the exact choice text shown by LinkedIn."
        ),
        "Supervised mode does not prompt": (
            "Check that Run mode says Supervised before Start. Do not close autojobs while Chrome is running. If a field remains unanswered, open the persistent log from the Run tab and look for 'Answer field' or 'Answer choice'."
        ),
        "Headless mode": (
            "Login is never headless. Use Open LinkedIn login first. Headless only hides Chrome during applications. If LinkedIn expires the session, turn headless off, sign in visibly again, then retry."
        ),
        "Generate answers with ChatGPT": (
            "No JSON knowledge is needed. Attach prompt.txt, answer-profile-template.json and your CV PDF to ChatGPT. Ask it to follow prompt.txt. "
            "It should return a ready file named import_me_on_autojobs.json. Then hover/click Import AI answers in Answer Rules and select that file."
        ),
        "Very low delay warning": (
            "Very small delays can make long unattended runs look unusually fast and may increase the chance of LinkedIn throttling, challenge prompts, or temporary restrictions. LinkedIn does not publish a guaranteed safe delay. "
            "autojobs warns when the configured range is aggressive and recommends roughly 3-7 seconds or slower as a conservative baseline. The warning is advisory, not a guarantee against account limits."
        ),
        "Failsafe alert": (
            "Failsafe means no run activity was seen for the configured time. Choose Restart visible + Supervised to inspect the exact form. "
            "A diagnostic report is saved under your autojobs data folder."
        ),
        "Chrome closed or crashed": (
            "Do not close the application Chrome window while a visible run is active. autojobs attempts to recover a lost WebDriver session. "
            "If recovery fails, sign in again using Open LinkedIn login and start a new Supervised run."
        ),
        "Where are logs?": (
            "autojobs writes a persistent autojobs.log in its local data folder. The file automatically resets at 100 MB. "
            "Use Open log file in the Run tab when reporting a bug."
        ),
        "Move autojobs to another PC": (
            "The finished portable build does not require Python on the destination computer. Zip/copy the contents of the dist folder together: autojobs.exe, themes.json, README.txt, prompt.txt, answer-profile-template.json and BUILD_INFO.txt. Google Chrome must be installed, and first-time ChromeDriver resolution may require internet access."
        ),
    }

    def __init__(self, parent: tk.Misc, open_log_callback=None):
        super().__init__(parent)
        self.title(f"{APP_TITLE} help")
        self.transient(parent)
        self.resizable(True, True)
        self.geometry("900x580")
        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(1, weight=1)
        ttk.Label(body, text="Help & troubleshooting", font=("Segoe UI", 15, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        self.listbox = tk.Listbox(body, width=30, exportselection=False)
        self.listbox.grid(row=1, column=0, sticky="nsw", padx=(0, 12))
        for topic in self.TOPICS:
            self.listbox.insert("end", topic)
        self.text = ScrolledText(body, wrap="word", state="disabled", font=("Segoe UI", 10))
        self.text.grid(row=1, column=1, sticky="nsew")
        buttons = ttk.Frame(body)
        buttons.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        if callable(open_log_callback):
            ttk.Button(buttons, text="Open log file", command=open_log_callback).pack(side="left")
        ttk.Button(buttons, text="Close", command=self.destroy).pack(side="right")
        self.listbox.bind("<<ListboxSelect>>", self._select)
        self.listbox.selection_set(0)
        self._select()

    def _select(self, _event=None) -> None:
        sel = self.listbox.curselection()
        if not sel:
            return
        topic = self.listbox.get(sel[0])
        content = self.TOPICS.get(topic, "")
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", f"{topic}\n\n{content}")
        self.text.configure(state="disabled")


class ImportModeDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc):
        super().__init__(parent)
        self.title("Import answer profile")
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        self.result: str | None = None
        self.mode = tk.StringVar(value="merge")

        body = ttk.Frame(self, padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="How should imported answers be applied?", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(
            body,
            text="The JSON contains answer rules only. Job searches, CV paths, Chrome profile data and application history are not imported.",
            wraplength=560,
        ).pack(anchor="w", pady=(4, 14))

        merge = ttk.Radiobutton(body, variable=self.mode, value="merge", text="Merge with my current answers")
        merge.pack(anchor="w", pady=(2, 0))
        ttk.Label(body, text="Imported answers win only when the same question already exists.", style="Muted.TLabel").pack(anchor="w", padx=(24, 0))
        replace = ttk.Radiobutton(body, variable=self.mode, value="replace", text="Replace my configured and learned answers")
        replace.pack(anchor="w", pady=(12, 0))
        ttk.Label(body, text="Clears existing explicit/learned answers before loading the JSON.", style="Muted.TLabel").pack(anchor="w", padx=(24, 0))

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(18, 0))
        ttk.Button(buttons, text="Cancel", command=self._cancel).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="Import", style="Accent.TButton", command=self._ok).pack(side="right")
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.wait_window(self)

    def _ok(self) -> None:
        self.result = self.mode.get()
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


class FailsafeDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, seconds: int, report_path: str, repeat_count: int = 1):
        super().__init__(parent)
        self.title(f"{APP_TITLE} failsafe")
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        self.result: str | None = None
        self.protocol("WM_DELETE_WINDOW", self._wait)

        body = ttk.Frame(self, padding=22)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="The automation looks stuck", font=("Segoe UI", 13, "bold")).pack(anchor="w")
        ttk.Label(
            body,
            text=(
                f"No run activity was recorded for about {seconds} seconds. autojobs stopped trusting the current browser state "
                "so it does not keep looping silently."
            ),
            wraplength=650,
        ).pack(anchor="w", pady=(6, 10))
        if repeat_count > 1:
            ttk.Label(
                body,
                text=f"This is failsafe alert #{repeat_count} in this run. Restarting visibly in Supervised mode is recommended.",
                style="Muted.TLabel",
                wraplength=650,
            ).pack(anchor="w", pady=(0, 10))
        ttk.Label(
            body,
            text=(
                "Recommended: restart in Supervised mode with a visible browser. This makes the failing field/page visible so you can answer it manually and the diagnostic report is kept for review."
            ),
            wraplength=650,
        ).pack(anchor="w", pady=(0, 10))
        ttk.Label(body, text=f"Diagnostic report: {report_path}", style="Muted.TLabel", wraplength=650).pack(anchor="w", pady=(0, 16))

        buttons = ttk.Frame(body)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Stop run", command=self._stop).pack(side="right")
        ttk.Button(buttons, text="Keep waiting", command=self._wait).pack(side="right", padx=6)
        ttk.Button(buttons, text="Try browser recovery", command=self._recover).pack(side="right", padx=6)
        ttk.Button(buttons, text="Restart visible + Supervised", style="Accent.TButton", command=self._manual).pack(side="right", padx=6)

        self.update_idletasks()
        width = max(720, self.winfo_reqwidth())
        height = self.winfo_reqheight()
        x = max(0, (self.winfo_screenwidth() - width) // 2)
        y = max(0, (self.winfo_screenheight() - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.lift()
        self.attributes("-topmost", True)
        self.after(500, lambda: self.attributes("-topmost", False))
        self.wait_window(self)

    def _manual(self) -> None:
        self.result = "restart_supervised"
        self.destroy()

    def _recover(self) -> None:
        self.result = "recover"
        self.destroy()

    def _wait(self) -> None:
        self.result = "wait"
        self.destroy()

    def _stop(self) -> None:
        self.result = "stop"
        self.destroy()


class OnboardingWizard(tk.Toplevel):
    PAGES = (
        (
            "disclaimer",
            "Welcome to Autojobs",
            "Before automating anything, configure the app carefully. The warning highlighted behind this guide is intentional: incomplete answer rules are the most common reason for skipped applications. Start with a small Supervised test before Automatic mode.",
        ),
        (
            "account",
            "1. Sign in and choose your CV",
            "Use Open LinkedIn login. Login always opens in a visible Chrome window so you can complete password, 2FA, CAPTCHA or any challenge yourself. Choose the CV you want LinkedIn to upload. Headless affects only the application run, never login.",
        ),
        (
            "search",
            "2. Tell autojobs exactly what to search",
            "Add one job title and one location per line. The location is sent to LinkedIn to scope the search, but it is not a hard application gate. By default autojobs continues every job LinkedIn returns, even if the opened page later shows broader, remote, missing, or conflicting location metadata. The optional post-open conflict guard is off by default and should stay off when maximizing coverage.",
        ),
        (
            "behavior",
            "3. Choose a safe run mode",
            "Supervised is the recommended first run. When an unresolved form question appears, autojobs pauses and asks you in the desktop app, even if LinkedIn forgot to mark that control as HTML-required. Automatic uses your explicit answers and typed fallbacks without asking.",
        ),
        (
            "answer_defaults",
            "4. Configure the fallback rules",
            "Fallbacks are the last resort for questions that are not already mapped. Configure separate defaults for numeric, free-text and Yes/No questions. For social/diversity questions, the privacy strategy can prefer 'Prefer not to say' when LinkedIn actually offers that choice.",
        ),
        (
            "question_library",
            "5. Fill the Answer Rules library",
            "This is the most important configuration area. Select questions on the left and save your answers on the right. Fill as many as you can before running automatically. Add custom exact questions for recruiter wording that is not in the built-in catalog.",
        ),
        (
            "import_answers",
            "6. Generate an answer profile with ChatGPT",
            "You do not need to understand JSON. Hover Import AI answers for the exact workflow. In short: send prompt.txt + answer-profile-template.json + your CV PDF to ChatGPT. It should return import_me_on_autojobs.json, ready for this app to import.",
        ),
        (
            "run",
            "7. Start small and watch the run",
            "Open 3. Run and start with visible Chrome + Supervised mode. Watch the current job, counters, status and logs. Stop requests a safe stop. Successful applications are counted only after LinkedIn confirms submission.",
        ),
        (
            "help",
            "8. If something looks wrong",
            "Use the ? help button for non-technical troubleshooting. The persistent autojobs.log is also available from the Run tab and automatically resets at 100 MB. If the run becomes silent, Failsafe can restart visibly in Supervised mode and writes a diagnostic report.",
        ),
    )

    def __init__(self, parent: tk.Misc, *, first_run: bool = False, on_complete=None):
        super().__init__(parent)
        self.withdraw()
        self.title(f"{APP_TITLE} setup & onboarding")
        apply_application_icon(self)
        self.transient(parent)
        self.resizable(False, False)
        self.first_run = first_run
        self.on_complete = on_complete
        self.index = 0
        self._focus_rect: ScreenRect | None = None
        self._refresh_after_id: str | None = None
        self._parent_configure_binding = self.master.bind("<Configure>", self._on_parent_configure, add="+")

        body = ttk.Frame(self, padding=(20, 18))
        body.pack(fill="both", expand=True)
        self.progress_var = tk.StringVar()
        self.title_var = tk.StringVar()
        self.text_var = tk.StringVar()
        self.focus_hint_var = tk.StringVar(value="The matching control is outlined in the main Autojobs window.")
        ttk.Label(body, textvariable=self.progress_var, style="Muted.TLabel").pack(anchor="w")
        ttk.Label(body, textvariable=self.title_var, font=("Segoe UI", 16, "bold")).pack(anchor="w", pady=(5, 12))
        ttk.Label(body, textvariable=self.text_var, wraplength=620, justify="left").pack(anchor="w")
        ttk.Label(body, textvariable=self.focus_hint_var, style="Muted.TLabel", wraplength=620).pack(anchor="w", pady=(12, 16))

        buttons = ttk.Frame(body)
        buttons.pack(fill="x")
        self.back_button = ttk.Button(buttons, text="Back", command=self._back)
        self.back_button.pack(side="left")
        ttk.Button(buttons, text="Close", command=self._close).pack(side="right")
        self.next_button = ttk.Button(buttons, text="Next", style="Accent.TButton", command=self._next)
        self.next_button.pack(side="right", padx=(0, 8))

        self.protocol("WM_DELETE_WINDOW", self._close)
        self._render()
        self.deiconify()
        self.lift()
        self.wait_window(self)

    def _schedule_highlight_refresh(self) -> None:
        if self._refresh_after_id is not None:
            try:
                self.after_cancel(self._refresh_after_id)
            except Exception:
                pass
        self._refresh_after_id = self.after(80, self._refresh_highlight)

    def _on_parent_configure(self, _event=None) -> None:
        self._schedule_highlight_refresh()

    def _refresh_highlight(self) -> None:
        self._refresh_after_id = None
        target, _title, _text = self.PAGES[self.index]
        try:
            self._focus_rect = self.master._highlight_onboarding_target(target)
        except Exception:
            self._focus_rect = None
        self._position_next_to_focus()

    def _screen_rect(self) -> ScreenRect:
        if sys.platform == "win32":
            try:
                import ctypes
                from ctypes import wintypes

                class MonitorInfo(ctypes.Structure):
                    _fields_ = [
                        ("cbSize", wintypes.DWORD),
                        ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT),
                        ("dwFlags", wintypes.DWORD),
                    ]

                center = wintypes.POINT(
                    self.master.winfo_rootx() + self.master.winfo_width() // 2,
                    self.master.winfo_rooty() + self.master.winfo_height() // 2,
                )
                monitor = ctypes.windll.user32.MonitorFromPoint(center, 2)
                info = MonitorInfo()
                info.cbSize = ctypes.sizeof(MonitorInfo)
                if monitor and ctypes.windll.user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                    work_area = info.rcWork
                    return ScreenRect(
                        work_area.left,
                        work_area.top,
                        work_area.right - work_area.left,
                        work_area.bottom - work_area.top,
                    )
            except Exception:
                pass
        try:
            return ScreenRect(
                self.master.winfo_vrootx(),
                self.master.winfo_vrooty(),
                self.master.winfo_vrootwidth(),
                self.master.winfo_vrootheight(),
            )
        except Exception:
            return ScreenRect(0, 0, self.winfo_screenwidth(), self.winfo_screenheight())

    def _position_next_to_focus(self) -> None:
        self.update_idletasks()
        width = max(660, min(760, self.winfo_reqwidth()))
        height = max(240, self.winfo_reqheight())
        outer_width = width + 20
        outer_height = height + 44
        screen = self._screen_rect()
        placement = find_onboarding_position(screen, self._focus_rect, outer_width, outer_height, margin=28)
        if placement is None and self._focus_rect is not None:
            try:
                self.master._clear_onboarding_highlight()
            except Exception:
                pass
            self._focus_rect = None
            self.focus_hint_var.set("The relevant tab is open in the main Autojobs window.")
            self.update_idletasks()
            height = max(240, self.winfo_reqheight())
            outer_height = height + 44
            placement = find_onboarding_position(screen, None, outer_width, outer_height, margin=28)
        if placement is None:
            placement = ScreenRect(
                max(0, screen.x + (screen.width - outer_width) // 2),
                max(0, screen.y + (screen.height - outer_height) // 2),
                outer_width,
                outer_height,
            )
        self.geometry(f"{width}x{height}+{placement.x}+{placement.y}")
        try:
            self.lift()
        except tk.TclError:
            pass

    def _render(self) -> None:
        target, title, text = self.PAGES[self.index]
        self.progress_var.set(f"Setup guide  {self.index + 1} / {len(self.PAGES)}")
        self.title_var.set(title)
        self.text_var.set(text)
        self.focus_hint_var.set("The matching control is outlined in the main Autojobs window.")
        self.back_button.configure(state="normal" if self.index else "disabled")
        self.next_button.configure(text="Finish" if self.index == len(self.PAGES) - 1 else "Next")
        try:
            self._focus_rect = self.master._highlight_onboarding_target(target)
        except Exception:
            self._focus_rect = None
        self._position_next_to_focus()
        self._schedule_highlight_refresh()

    def _back(self) -> None:
        if self.index:
            self.index -= 1
            self._render()

    def _next(self) -> None:
        if self.index < len(self.PAGES) - 1:
            self.index += 1
            self._render()
            return
        self._complete()

    def _complete(self) -> None:
        self._release_bindings()
        try:
            self.master._clear_onboarding_highlight()
        except Exception:
            pass
        if callable(self.on_complete):
            try:
                self.on_complete()
            except Exception:
                pass
        self.destroy()

    def _close(self) -> None:
        self._release_bindings()
        try:
            self.master._clear_onboarding_highlight()
        except Exception:
            pass
        if self.first_run and callable(self.on_complete):
            try:
                self.on_complete()
            except Exception:
                pass
        self.destroy()

    def _release_bindings(self) -> None:
        if self._refresh_after_id is not None:
            try:
                self.after_cancel(self._refresh_after_id)
            except Exception:
                pass
            self._refresh_after_id = None
        if self._parent_configure_binding:
            try:
                self.master.unbind("<Configure>", self._parent_configure_binding)
            except Exception:
                pass
            self._parent_configure_binding = None


class CreditsDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc):
        super().__init__(parent)
        self.title(f"credits | {APP_TITLE}")
        self.transient(parent)
        self.grab_set()
        self.resizable(True, False)

        body = ttk.Frame(self, padding=26)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="a small note", font=("Segoe UI", 13, "bold")).pack(anchor="w")
        message = (
            "This tool is for everyone who was impacted by layoffs and suddenly had to start searching again. "
            "Job hunting can be exhausting, repetitive and sometimes unfair. I hope Autojobs can take a little of that repetitive work off your shoulders and help you get closer to a good opportunity."
        )
        ttk.Label(body, text=message, wraplength=650, justify="left").pack(anchor="w", pady=(0, 12))
        origin = (
            "Autojobs was built on top of nicolomantini's project, then changed with a little extra care for special people."
        )
        ttk.Label(body, text=origin, wraplength=650, justify="left").pack(anchor="w", pady=(0, 12))
        ending = (
            "I really hope this helps you find something good soon. I'm praying for you, for kind people to cross your path, for open doors and for better days ahead. Good luck, and please take care of yourself. ♥"
        )
        ttk.Label(body, text=ending, wraplength=650, justify="left").pack(anchor="w", pady=(0, 18))
        signature = ttk.Label(body, text="by roberto", style="Signature.TLabel", cursor="hand2")
        signature.pack(anchor="e", pady=(0, 14))
        signature.bind("<Button-1>", lambda _e: webbrowser.open("https://borerto.com"))
        ttk.Button(body, text="Close", command=self.destroy).pack(anchor="e")
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.update_idletasks()
        width = max(700, self.winfo_reqwidth())
        height = self.winfo_reqheight()
        x = max(0, (self.winfo_screenwidth() - width) // 2)
        y = max(0, (self.winfo_screenheight() - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.wait_window(self)


class AIBalloon:
    def __init__(self, parent: tk.Misc, palette_getter=None):
        self.parent = parent
        self.palette_getter = palette_getter
        self.window: tk.Toplevel | None = None

    def show(self, x: int, y: int) -> None:
        if self.window is not None:
            try:
                self.window.geometry(f"+{x}+{y}")
            except Exception:
                pass
            return
        win = tk.Toplevel(self.parent)
        self.window = win
        win.overrideredirect(True)
        try:
            win.attributes("-topmost", True)
            win.attributes("-alpha", 0.96)
        except Exception:
            pass
        palette = self.palette_getter() if self.palette_getter else {
            "surface": "#ffffff", "text": "#202020", "muted": "#b0b0b0", "border": "#202020"
        }
        outer = tk.Frame(win, background=palette["border"], bd=0, padx=1, pady=1)
        outer.pack()
        card = tk.Frame(outer, background=palette["surface"], padx=15, pady=10)
        card.pack()
        tk.Label(card, text="Coming soon", font=("Segoe UI", 11, "bold"), background=palette["surface"], foreground=palette["text"]).pack()
        tk.Label(card, text="by borerto", font=("Segoe UI", 8, "italic"), background=palette["surface"], foreground=palette["muted"]).pack(pady=(2, 0))
        win.geometry(f"+{x}+{y}")

    def hide(self) -> None:
        if self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                pass
            self.window = None


class EasyApplyApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        apply_application_icon(self)
        self.brand_logo = load_application_logo(self, 64)
        self.geometry("1240x830")
        self.minsize(640, 480)
        self.config_data = AppConfig.load()
        self.theme_result = load_themes()
        self.themes = self.theme_result.themes
        self.current_theme_name = (
            self.config_data.theme_name
            if self.config_data.theme_name in self.themes
            else self.theme_result.default_theme
        )
        self.current_palette = self.themes[self.current_theme_name]
        self.ui_queue: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.login_worker: threading.Thread | None = None
        self.current_stats = RunStats()
        self.ai_balloon = AIBalloon(self, lambda: self.current_palette)
        self.current_bot: EasyApplyBot | None = None
        self.last_run_activity = time.monotonic()
        self.recent_logs = deque(maxlen=60)
        self.failsafe_suspended = False
        self.failsafe_dialog_open = False
        self.failsafe_count = 0
        self.restart_after_stop = False
        self._restart_pending_started = False
        self.onboarding_highlight = HighlightOverlay(self)
        self._responsive_after_id = None
        self._autosave_after_id = None
        self._autosave_loading = True
        self._settings_dirty = False
        self._run_active = False
        self._locked_widgets = []
        self._question_drafts: dict[str, str] = {}
        self._editing_question_key: str | None = None
        self._loading_question = False
        self._question_search_after_id = None
        self._last_friendly_log = ""
        self._pages: list[ScrollablePage] = []
        self._history_rows = []
        self._history_loading = False
        self._history_page = 0
        self._history_search_after_id = None
        self._history_signature = None

        self._configure_logging()
        self._configure_style()
        self._build_ui()
        self._apply_theme_to_native_widgets(self)
        self._load_config_into_ui()
        self._install_autosave()
        self._autosave_loading = False
        self._refresh_applied()
        if self.theme_result.warning:
            self.after(250, lambda: messagebox.showwarning("Theme file", self.theme_result.warning, parent=self))
        self.after(100, self._process_ui_queue)
        self.after(1000, self._failsafe_tick)
        if not self.config_data.onboarding_completed:
            self.after(500, lambda: self._show_onboarding(first_run=True))
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_logging(self) -> None:
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        formatter = logging.Formatter("%(asctime)s  %(levelname)s  %(name)s  %(message)s", "%Y-%m-%d %H:%M:%S")
        if not any(isinstance(h, QueueLogHandler) for h in root.handlers):
            handler = QueueLogHandler(self.ui_queue)
            handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)s  %(message)s", "%H:%M:%S"))
            root.addHandler(handler)
        if not any(getattr(h, "_autojobs_persistent_handler", False) for h in root.handlers):
            file_handler = CappedFileHandler(log_file_path())
            file_handler.setLevel(logging.INFO)
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        logging.getLogger(__name__).info("autojobs desktop started; persistent log=%s", log_file_path())

    def _configure_style(self) -> None:
        p = self.current_palette
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        try:
            self.configure(background=p["background"])
        except Exception:
            pass

        style.configure(".", background=p["background"], foreground=p["text"], font=("Segoe UI", 10))
        style.configure("TFrame", background=p["background"])
        style.configure("TLabel", background=p["background"], foreground=p["text"])
        style.configure("Title.TLabel", background=p["background"], foreground=p["text"], font=("Segoe UI", 18, "bold"))
        style.configure("Subtitle.TLabel", background=p["background"], foreground=p["muted"], font=("Segoe UI", 10))
        style.configure("Section.TLabel", background=p["background"], foreground=p["text"], font=("Segoe UI", 11, "bold"))
        style.configure("Muted.TLabel", background=p["background"], foreground=p["muted"])
        style.configure("Warning.TLabel", background=p["background"], foreground=p.get("danger", "#B42318"), font=("Segoe UI", 9, "bold"))
        style.configure("Credits.TLabel", background=p["background"], foreground=p["muted"], font=("Segoe UI", 8, "underline"))
        style.configure("Signature.TLabel", background=p["background"], foreground=p["muted"], font=("Segoe UI", 8, "italic underline"))
        style.configure("Disclaimer.TFrame", background=p["surface_alt"], relief="solid", borderwidth=1)
        style.configure("Disclaimer.TLabel", background=p["surface_alt"], foreground=p["text"], font=("Segoe UI", 9, "bold"))
        style.configure("Tooltip.TFrame", background=p["surface"], relief="solid", borderwidth=1)
        style.configure("Tooltip.TLabel", background=p["surface"], foreground=p["text"])
        style.configure("TButton", background=p["surface_alt"], foreground=p["text"], bordercolor=p["border"], padding=(10, 7))
        style.map("TButton", background=[("active", p["surface"]), ("pressed", p["surface_alt"])])
        style.configure("Accent.TButton", background=p["primary"], foreground="#FFFFFF", bordercolor=p["primary"], font=("Segoe UI", 9, "bold"), padding=(12, 7))
        style.map("Accent.TButton", background=[("active", p["primary_hover"]), ("pressed", p["primary_hover"])], foreground=[("disabled", p["muted"]), ("!disabled", "#FFFFFF")])
        style.configure("TCheckbutton", background=p["background"], foreground=p["text"])
        style.configure("TRadiobutton", background=p["background"], foreground=p["text"])
        style.configure("TLabelframe", background=p["background"], bordercolor=p["border"], relief="solid")
        style.configure("TLabelframe.Label", background=p["background"], foreground=p["text"], font=("Segoe UI", 10, "bold"))
        style.configure("Card.TLabelframe", background=p["background"], bordercolor=p["border"], padding=10)
        style.configure("Card.TLabelframe.Label", background=p["background"], foreground=p["text"], font=("Segoe UI", 10, "bold"))
        style.configure("TEntry", fieldbackground=p["input_bg"], foreground=p["input_fg"], insertcolor=p["input_fg"], bordercolor=p["border"])
        style.configure("TCombobox", fieldbackground=p["input_bg"], foreground=p["input_fg"], background=p["surface_alt"], arrowcolor=p["text"], bordercolor=p["border"])
        style.map("TCombobox", fieldbackground=[("readonly", p["input_bg"])], foreground=[("readonly", p["input_fg"])])
        style.configure("TSpinbox", fieldbackground=p["input_bg"], foreground=p["input_fg"], arrowcolor=p["text"], bordercolor=p["border"])
        style.configure("Treeview", background=p["surface"], fieldbackground=p["surface"], foreground=p["text"], bordercolor=p["border"], rowheight=34)
        style.configure("Treeview.Heading", background=p["surface_alt"], foreground=p["text"], bordercolor=p["border"], font=("Segoe UI", 9, "bold"))
        style.map("Treeview", background=[("selected", p["selection_bg"])], foreground=[("selected", p["selection_fg"])])
        style.configure("TNotebook", background=p["background"], bordercolor=p["border"])
        style.configure("TNotebook.Tab", background=p["surface_alt"], foreground=p["text"], padding=(11, 7))
        style.map("TNotebook.Tab", background=[("selected", p["surface"]), ("active", p["surface"])], foreground=[("disabled", p["muted"]), ("selected", p["primary"])])
        style.configure("Horizontal.TProgressbar", background=p["primary"], troughcolor=p["surface_alt"], bordercolor=p["border"])
        style.configure("Cadente.TLabel", foreground=p.get("accent", p["primary"]), font=("Segoe UI", 10, "bold"))

    def _apply_theme_to_native_widgets(self, widget: tk.Misc) -> None:
        p = self.current_palette
        try:
            if isinstance(widget, (tk.Text, ScrolledText)):
                widget.configure(
                    background=p["input_bg"], foreground=p["input_fg"], insertbackground=p["input_fg"],
                    selectbackground=p["selection_bg"], selectforeground=p["selection_fg"],
                    highlightbackground=p["border"], highlightcolor=p["primary"],
                )
            elif isinstance(widget, tk.Listbox):
                widget.configure(
                    background=p["input_bg"], foreground=p["input_fg"],
                    selectbackground=p["selection_bg"], selectforeground=p["selection_fg"],
                )
            elif isinstance(widget, tk.Canvas):
                widget.configure(background=p["background"])
            elif isinstance(widget, tk.PanedWindow):
                widget.configure(background=p["background"])
        except Exception:
            pass
        try:
            children = widget.winfo_children()
        except Exception:
            children = []
        for child in children:
            self._apply_theme_to_native_widgets(child)

    def _apply_selected_theme(self, name: str, *, save: bool = True) -> None:
        if name not in self.themes:
            name = next(iter(self.themes))
        self.current_theme_name = name
        self.current_palette = self.themes[name]
        self._configure_style()
        self._apply_theme_to_native_widgets(self)
        if hasattr(self, "theme_var"):
            self.theme_var.set(name)
        if save:
            self._schedule_autosave()

    def _on_theme_selected(self, _event=None) -> None:
        self._apply_selected_theme(self.theme_var.get())

    def _reload_themes(self) -> None:
        result = load_themes()
        self.theme_result = result
        self.themes = result.themes
        if hasattr(self, "theme_combo"):
            self.theme_combo.configure(values=tuple(self.themes.keys()))
        requested = self.current_theme_name if self.current_theme_name in self.themes else result.default_theme
        self._apply_selected_theme(requested)
        if result.warning:
            messagebox.showwarning("Theme file", result.warning, parent=self)
        else:
            messagebox.showinfo(
                "Themes reloaded",
                f"Loaded {len(self.themes)} theme(s) from:\n{themes_file_path()}\n\nYou can add, edit or remove themes in that JSON file and reload them here.",
                parent=self,
            )

    def _complete_onboarding(self) -> None:
        if self._settings_locked():
            return
        self.config_data.onboarding_completed = True
        try:
            self.config_data.save()
        except Exception:
            pass

    def _show_onboarding(self, first_run: bool = False) -> None:
        try:
            OnboardingWizard(self, first_run=first_run, on_complete=self._complete_onboarding)
        except Exception as exc:
            logging.getLogger(__name__).exception("Onboarding could not open")
            if not first_run:
                messagebox.showerror("Setup & onboarding", str(exc), parent=self)

    def _mark_run_activity(self) -> None:
        self.last_run_activity = time.monotonic()

    def _flash_notification(self) -> None:
        try:
            self.bell()
        except Exception:
            pass
        try:
            import ctypes
            if hasattr(ctypes, "windll"):
                class FLASHWINFO(ctypes.Structure):
                    _fields_ = [
                        ("cbSize", ctypes.c_uint),
                        ("hwnd", ctypes.c_void_p),
                        ("dwFlags", ctypes.c_uint),
                        ("uCount", ctypes.c_uint),
                        ("dwTimeout", ctypes.c_uint),
                    ]
                info = FLASHWINFO(
                    ctypes.sizeof(FLASHWINFO),
                    self.winfo_id(),
                    0x0000000C,  # FLASHW_ALL | FLASHW_TIMERNOFG
                    8,
                    0,
                )
                ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
        except Exception:
            pass

    def _write_failsafe_report(self, elapsed: int) -> Path:
        folder = app_data_dir() / "failsafe-reports"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"failsafe-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
        lines = [
            "autojobs failsafe diagnostic report",
            f"created: {datetime.now().isoformat(timespec='seconds')}",
            f"silence_seconds: {elapsed}",
            f"failsafe_threshold: {self.config_data.failsafe_seconds}",
            f"run_mode: {self.config_data.run_mode}",
            f"headless_browser: {self.config_data.headless_browser}",
            f"status: {self.status_var.get() if hasattr(self, 'status_var') else ''}",
            f"current_job: {self.current_job_var.get() if hasattr(self, 'current_job_var') else ''}",
            "",
            "recent logs:",
        ]
        lines.extend(list(self.recent_logs) or ["(no recent log lines captured)"])
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def _force_current_browser_close(self, *, request_recovery: bool = False) -> None:
        bot = self.current_bot
        if bot is None:
            return
        def close_worker():
            try:
                if request_recovery:
                    bot.request_browser_recovery()
                else:
                    bot.interrupt_browser()
            except Exception:
                pass
        threading.Thread(target=close_worker, daemon=True).start()

    def _failsafe_tick(self) -> None:
        try:
            running = bool(self.worker and self.worker.is_alive())
            if running and not self.failsafe_suspended and not self.failsafe_dialog_open:
                threshold = max(15, int(self.config_data.failsafe_seconds or 60))
                elapsed = int(time.monotonic() - self.last_run_activity)
                if elapsed >= threshold:
                    self.failsafe_dialog_open = True
                    self.failsafe_suspended = True
                    self.failsafe_count += 1
                    self._flash_notification()
                    report = self._write_failsafe_report(elapsed)
                    self.status_var.set("Failsafe triggered: the run stopped producing activity")
                    self._append_log(f"FAILSAFE: no activity for {elapsed}s. Diagnostic report: {report}")
                    dialog = FailsafeDialog(self, elapsed, str(report), self.failsafe_count)
                    action = dialog.result or "wait"
                    self._mark_run_activity()
                    if action == "restart_supervised":
                        self.restart_after_stop = True
                        self._restart_pending_started = False
                        supervised_label = next(k for k, v in RUN_MODE_LABELS.items() if v == "supervised")
                        self.run_mode_label_var.set(supervised_label)
                        self.headless_var.set(False)
                        self.config_data.run_mode = "supervised"
                        self.config_data.headless_browser = False
                        self._settings_dirty = True
                        self.status_var.set("Restarting with guidance and a visible Chrome window…")
                        self._stop_run()
                        self._force_current_browser_close()
                    elif action == "recover":
                        self.status_var.set("Failsafe: forcing a browser reset and attempting recovery…")
                        self._force_current_browser_close(request_recovery=True)
                    elif action == "stop":
                        self._stop_run()
                    else:
                        self.status_var.set("Failsafe dismissed. Continuing to wait for activity…")
                    self.failsafe_suspended = False
                    self.failsafe_dialog_open = False
        except Exception:
            logging.getLogger(__name__).exception("Failsafe watchdog error")
            self.failsafe_suspended = False
            self.failsafe_dialog_open = False
        finally:
            self.after(1000, self._failsafe_tick)

    def _start_run_when_idle(self) -> None:
        if not self.restart_after_stop:
            return
        if self.worker and self.worker.is_alive():
            self.after(300, self._start_run_when_idle)
            return
        if self._restart_pending_started:
            return
        self._restart_pending_started = True
        self.restart_after_stop = False
        self.stop_event.clear()
        self.status_var.set("Failsafe recovery: starting visible Supervised run…")
        self.after(150, self._start_run)

    def _scroll_setup_targets_into_view(self, widgets: tuple[tk.Misc | None, ...]) -> None:
        canvas = getattr(self, "setup_canvas", None)
        content = getattr(self, "setup_content", None)
        if canvas is None or content is None:
            return

        def is_descendant(widget: tk.Misc, ancestor: tk.Misc) -> bool:
            current = widget
            while current is not None:
                if current is ancestor:
                    return True
                current = getattr(current, "master", None)
            return False

        setup_widgets = [widget for widget in widgets if widget is not None and is_descendant(widget, content)]
        if not setup_widgets:
            return
        try:
            self.update_idletasks()
            bounds = canvas.bbox("all")
            if not bounds:
                return
            content_top = content.winfo_rooty()
            target_top = min(widget.winfo_rooty() - content_top for widget in setup_widgets)
            target_bottom = max(widget.winfo_rooty() - content_top + widget.winfo_height() for widget in setup_widgets)
            viewport_height = canvas.winfo_height()
            content_height = bounds[3] - bounds[1]
            max_scroll = max(bounds[1], bounds[3] - viewport_height)
            target_height = target_bottom - target_top
            if target_height >= viewport_height - 32:
                scroll_top = target_top - 16
            else:
                scroll_top = target_top - (viewport_height - target_height) // 2
            scroll_top = max(bounds[1], min(scroll_top, max_scroll))
            scrollable_height = content_height - viewport_height
            canvas.yview_moveto(0 if scrollable_height <= 0 else (scroll_top - bounds[1]) / scrollable_height)
        except Exception:
            pass

    def _highlight_onboarding_target(self, key: str) -> ScreenRect | None:
        mapping = {
            "disclaimer": getattr(self, "disclaimer_frame", None),
            "account": (getattr(self, "login_setup_button", None), getattr(self, "resume_entry", None)),
            "search": (getattr(self, "positions_text", None), getattr(self, "locations_text", None)),
            "behavior": getattr(self, "run_mode_combo", None),
            "answer_defaults": (
                getattr(self, "default_numeric_entry", None),
                getattr(self, "default_text_entry", None),
                getattr(self, "default_boolean_combo", None),
                getattr(self, "social_strategy_combo", None),
            ),
            "question_library": getattr(self, "question_tree", None),
            "import_answers": getattr(self, "import_ai_button", None),
            "run": getattr(self, "start_button", None),
            "help": getattr(self, "help_button", None),
        }
        if key in {"account", "search", "behavior"}:
            try: self.notebook.select(self.setup_tab)
            except Exception: pass
        elif key in {"answer_defaults", "question_library", "import_answers"}:
            try: self.notebook.select(self.questions_tab)
            except Exception: pass
        elif key == "run":
            try: self.notebook.select(self.run_tab)
            except Exception: pass
        self.update_idletasks()
        target = mapping.get(key)
        widgets = target if isinstance(target, tuple) else (target,)
        self._scroll_setup_targets_into_view(widgets)
        self.update_idletasks()
        return self.onboarding_highlight.show(widgets, self.current_palette.get("primary", "#2F80ED"))

    def _clear_onboarding_highlight(self) -> None:
        self.onboarding_highlight.clear()

    def _show_help(self) -> None:
        HelpCenterDialog(self, open_log_callback=self._open_log_file)

    def _schedule_responsive_layout(self, _event=None) -> None:
        if _event is not None and _event.widget is not self:
            return
        if self._responsive_after_id is not None:
            try: self.after_cancel(self._responsive_after_id)
            except Exception: pass
        self._responsive_after_id = self.after(80, self._apply_responsive_layout)

    def _apply_responsive_layout(self) -> None:
        self._responsive_after_id = None
        width = self.winfo_width()
        narrow = width < 1100
        self.appearance_frame.grid_forget()
        self.appearance_frame.grid(
            row=2 if narrow else 1, column=0 if narrow else 2,
            columnspan=3 if narrow else 1, sticky="w" if narrow else "e", pady=(6, 0),
        )
        self.header_mode_label.grid_remove()
        self.header_subtitle.configure(wraplength=max(240, width - (140 if narrow else 680)))
        self.search_card.grid_forget()
        self.behavior_card.grid_forget()
        self.setup_actions.grid_forget()
        self.search_card.grid(row=1, column=0, columnspan=2 if narrow else 1, sticky="nsew", pady=6, padx=(0, 6))
        self.behavior_card.grid(row=2 if narrow else 1, column=0 if narrow else 1,
                                columnspan=2 if narrow else 1, sticky="nsew", pady=6)
        self.setup_actions.grid(row=3 if narrow else 2, column=0, columnspan=2, sticky="ew", pady=8)
        self.question_workspace.configure(orient="vertical" if narrow else "horizontal", height=660 if narrow else 390)
        self.question_tree.column("category", width=120, minwidth=90)
        self.question_tree.column("question", width=300, minwidth=180)
        self.question_tree.column("answer", width=150, minwidth=100)
        for index, card in enumerate(self.default_cards):
            cols = 2 if narrow else 4
            card.grid(row=index // cols, column=index % cols, sticky="nsew", padx=4, pady=4)
        self.default_autonomous.grid(row=2 if narrow else 1, column=0, columnspan=4, sticky="ew", pady=8)
        for col in range(4):
            self.answer_defaults_frame.columnconfigure(col, weight=1 if col < (2 if narrow else 4) else 0)
        cols = 7 if width >= 1180 else (4 if width >= 800 else 2)
        for index, box in enumerate(self.stat_boxes):
            box.grid(row=index // cols, column=index % cols, sticky="ew", padx=3, pady=3)
        for col in range(7):
            self.stats_frame.columnconfigure(col, weight=1 if col < cols else 0)
        self.disclaimer_label.configure(wraplength=max(280, width - 255))
        self.update_idletasks()
        wrap_labels(self)
        for page in self._pages:
            page.reflow()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        header = ttk.Frame(self, padding=(16, 12, 16, 4))
        self.header_frame = header
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        if self.brand_logo:
            ttk.Label(header, image=self.brand_logo).grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 10))
        ttk.Label(header, text=APP_TITLE, style="Title.TLabel").grid(row=0, column=1, sticky="w")
        self.header_subtitle = ttk.Label(
            header,
            text="Cadente • a little clarity for your next opportunity.",
            style="Subtitle.TLabel",
            wraplength=420,
        )
        self.header_subtitle.grid(row=1, column=1, sticky="w", pady=(2, 0))
        self.header_mode_var = tk.StringVar(value="Supervised • Visible browser")
        self.header_mode_label = ttk.Label(header, textvariable=self.header_mode_var, style="Subtitle.TLabel")
        self.header_mode_label.grid(row=0, column=2, sticky="e")
        appearance = ttk.Frame(header)
        self.appearance_frame = appearance
        appearance.grid(row=1, column=2, sticky="e", pady=(2, 0))
        self.help_button = ttk.Button(appearance, text="?", width=3, command=self._show_help)
        self.help_button.pack(side="left", padx=(0, 8))
        ttk.Button(appearance, text="Quick guide", command=self._show_onboarding).pack(side="left", padx=(0, 10))
        ttk.Label(appearance, text="Theme", style="Muted.TLabel").pack(side="left", padx=(0, 5))
        self.theme_var = tk.StringVar(value=self.current_theme_name)
        self.theme_combo = ttk.Combobox(appearance, textvariable=self.theme_var, values=tuple(self.themes.keys()), state="readonly", width=14)
        self.theme_combo.pack(side="left")
        self.theme_combo.bind("<<ComboboxSelected>>", self._on_theme_selected)
        ttk.Button(appearance, text="Reload", command=self._reload_themes).pack(side="left", padx=(5, 0))

        self.disclaimer_frame = ttk.Frame(self, padding=(12, 8), style="Disclaimer.TFrame")
        self.disclaimer_frame.grid(row=1, column=0, sticky="ew", padx=14, pady=(4, 2))
        self.disclaimer_frame.columnconfigure(0, weight=1)
        self.disclaimer_frame.columnconfigure(1, weight=0)
        self.disclaimer_label = ttk.Label(
            self.disclaimer_frame,
            text=(
                "First time? Choose your jobs, prepare your answers, and start with guidance. "
                "You stay in control of each application."
            ),
            style="Disclaimer.TLabel", justify="left", wraplength=1120,
        )
        self.disclaimer_label.grid(row=0, column=0, sticky="w")
        self.dismiss_disclaimer_button = ttk.Button(
            self.disclaimer_frame, text="Don't show this again", command=self._hide_run_disclaimer
        )
        self.dismiss_disclaimer_button.grid(row=0, column=1, sticky="e", padx=(12, 0))
        if not self.config_data.show_run_disclaimer:
            self.disclaimer_frame.grid_remove()

        notebook = ttk.Notebook(self)
        notebook.grid(row=2, column=0, sticky="nsew", padx=12, pady=(6, 10))
        self.setup_tab = ttk.Frame(notebook, padding=12)
        self.questions_tab = ttk.Frame(notebook, padding=12)
        self.run_tab = ttk.Frame(notebook, padding=12)
        self.answers_tab = ttk.Frame(notebook, padding=12)
        self.applied_tab = ttk.Frame(notebook, padding=12)
        self.ai_tab = ttk.Frame(notebook, padding=12)
        notebook.add(self.setup_tab, text="1. Search")
        notebook.add(self.questions_tab, text="2. Answer Rules")
        notebook.add(self.run_tab, text="3. Run")
        notebook.add(self.applied_tab, text="Applied")
        notebook.add(self.answers_tab, text="Custom answers")
        notebook.add(self.ai_tab, text="AI  🔒")
        self.notebook = notebook
        self.ai_tab_index = notebook.index(self.ai_tab)
        notebook.tab(self.ai_tab, state="disabled")
        notebook.bind("<Motion>", self._notebook_motion, add="+")
        notebook.bind("<Leave>", lambda _e: self.ai_balloon.hide(), add="+")
        notebook.bind("<<NotebookTabChanged>>", self._tab_changed, add="+")

        self._build_setup_tab()
        self._build_questions_tab()
        self._build_run_tab()
        self._build_answers_tab()
        self._build_applied_tab()
        self._build_ai_tab()

        footer = ttk.Frame(self)
        footer.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 10))
        self.save_status_var = tk.StringVar(value="All changes saved on this computer")
        ttk.Label(footer, textvariable=self.save_status_var, style="Muted.TLabel", wraplength=480).pack(side="left")
        credits = ttk.Label(footer, text="credits", style="Credits.TLabel", cursor="hand2")
        credits.pack(side="right")
        credits.bind("<Button-1>", lambda _e: self._show_credits())
        self.bind("<Configure>", self._schedule_responsive_layout, add="+")
        self.after(120, self._apply_responsive_layout)

    def _build_setup_tab(self) -> None:
        # Keep the entire setup usable when the window is narrow or short.
        # The notebook tab stays the stable navigation target; the content lives
        # inside a vertically scrollable canvas whose width follows the viewport.
        page = ScrollablePage(self.setup_tab)
        self._pages.append(page)
        tab = page.content
        self.setup_canvas = page.canvas
        self.setup_content = tab
        tab.columnconfigure(0, weight=1)
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(1, weight=1)

        account = ttk.LabelFrame(tab, text="Your account and documents", style="Card.TLabelframe")
        self.account_card = account
        account.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        account.columnconfigure(1, weight=1)
        self.login_status_var = tk.StringVar(value="Sign in to get started")
        self.login_setup_button = ttk.Button(account, text="Open LinkedIn login", style="Accent.TButton", command=self._start_login_setup)
        self.login_setup_button.grid(row=0, column=0, sticky="w")
        ttk.Label(account, textvariable=self.login_status_var).grid(row=0, column=1, sticky="w", padx=10)
        ttk.Label(account, text="Sign in once in Chrome. We will reuse your session for future searches.", style="Muted.TLabel", wraplength=600).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 8))

        self.resume_var = tk.StringVar()
        self.cover_var = tk.StringVar()
        self.phone_var = tk.StringVar()
        self.salary_var = tk.StringVar()
        self.rate_var = tk.StringVar()
        self.resume_entry = self._file_row(account, 2, "Resume", self.resume_var, [("PDF/DOCX", "*.pdf *.docx"), ("All files", "*.*")])
        self._file_row(account, 3, "Cover letter (optional)", self.cover_var, [("PDF/DOCX", "*.pdf *.docx"), ("All files", "*.*")])
        ttk.Label(account, text="Phone number with country code").grid(row=4, column=0, sticky="w", pady=4)
        ttk.Entry(account, textvariable=self.phone_var).grid(row=4, column=1, sticky="ew", pady=4)
        ttk.Label(account, text="Salary expectation").grid(row=5, column=0, sticky="w", pady=4)
        ttk.Entry(account, textvariable=self.salary_var).grid(row=5, column=1, sticky="ew", pady=4)
        ttk.Label(account, text="Hourly / daily rate (optional)").grid(row=6, column=0, sticky="w", pady=4)
        ttk.Entry(account, textvariable=self.rate_var).grid(row=6, column=1, sticky="ew", pady=4)

        search = ttk.LabelFrame(tab, text="What opportunity are you looking for?", style="Card.TLabelframe")
        self.search_card = search
        search.grid(row=1, column=0, sticky="nsew", padx=(0, 5))
        search.columnconfigure(0, weight=1)
        ttk.Label(search, text="Job titles", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(search, text="One title per line. For example: Data Analyst", style="Muted.TLabel").grid(row=1, column=0, sticky="w")
        self.positions_text = tk.Text(search, height=4, width=24, font=("Segoe UI", 10), padx=8, pady=6)
        self.positions_text.grid(row=2, column=0, sticky="nsew", pady=(3, 9))
        ttk.Label(search, text="Where would you like to work?", style="Section.TLabel").grid(row=3, column=0, sticky="w")
        ttk.Label(search, text="One location per line: a city, country, or Worldwide. For remote jobs, select Remote below.", style="Muted.TLabel", wraplength=440).grid(row=4, column=0, sticky="w")
        self.locations_text = tk.Text(search, height=3, width=24, font=("Segoe UI", 10), padx=8, pady=6)
        self.locations_text.grid(row=5, column=0, sticky="nsew", pady=(3, 6))
        self.post_open_location_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            search,
            text="Skip jobs confirmed to be outside my chosen locations",
            variable=self.post_open_location_var,
        ).grid(row=6, column=0, sticky="w", pady=(0, 8))

        filters = ttk.Frame(search)
        filters.grid(row=7, column=0, sticky="ew")
        filters.columnconfigure(1, weight=1)
        ttk.Label(filters, text="Date posted").grid(row=0, column=0, sticky="w")
        self.date_label_var = tk.StringVar()
        ttk.Combobox(filters, textvariable=self.date_label_var, values=list(UI_DATE_FILTERS.keys()), state="readonly", width=18).grid(row=0, column=1, sticky="w", padx=(8, 0))

        exp_frame = ttk.LabelFrame(search, text="Experience")
        exp_frame.grid(row=8, column=0, sticky="ew", pady=(8, 4))
        self.exp_vars: dict[int, tk.BooleanVar] = {}
        for idx, (code, label) in enumerate(UI_EXPERIENCE_LEVELS.items()):
            var = tk.BooleanVar()
            self.exp_vars[code] = var
            ttk.Checkbutton(exp_frame, text=label, variable=var).grid(row=idx // 2, column=idx % 2, sticky="w", padx=6, pady=2)

        work_frame = ttk.LabelFrame(search, text="Work model")
        work_frame.grid(row=9, column=0, sticky="ew", pady=4)
        self.work_vars: dict[int, tk.BooleanVar] = {}
        for idx, (code, label) in enumerate(UI_WORK_TYPES.items()):
            var = tk.BooleanVar()
            self.work_vars[code] = var
            ttk.Checkbutton(work_frame, text=label, variable=var).grid(row=0, column=idx, sticky="w", padx=6, pady=2)

        behavior = ttk.LabelFrame(tab, text="How would you like to start?", style="Card.TLabelframe")
        self.behavior_card = behavior
        behavior.grid(row=1, column=1, sticky="nsew", padx=(5, 0))
        behavior.columnconfigure(1, weight=1)
        self.max_apps_var = tk.IntVar(value=10)
        self.max_pages_var = tk.IntVar(value=3)
        self.min_delay_var = tk.DoubleVar(value=RECOMMENDED_MIN_DELAY_SECONDS)
        self.max_delay_var = tk.DoubleVar(value=RECOMMENDED_MAX_DELAY_SECONDS)
        self.failsafe_seconds_var = tk.IntVar(value=60)
        self.review_var = tk.BooleanVar(value=True)
        self.follow_var = tk.BooleanVar(value=False)
        self.headless_var = tk.BooleanVar(value=False)
        self.run_mode_label_var = tk.StringVar(value=list(RUN_MODE_LABELS.keys())[0])
        self.browser_mode_hint_var = tk.StringVar()

        ttk.Label(behavior, text="Search mode", style="Section.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        self.run_mode_combo = ttk.Combobox(behavior, textvariable=self.run_mode_label_var, values=list(RUN_MODE_LABELS.keys()), state="readonly", width=28)
        self.run_mode_combo.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(3, 10))
        self.run_mode_combo.bind("<<ComboboxSelected>>", lambda _e: self._sync_run_mode_label())

        browser_box = ttk.LabelFrame(behavior, text="LinkedIn window")
        browser_box.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        ttk.Checkbutton(browser_box, text="Search without showing Chrome", variable=self.headless_var, command=self._sync_browser_mode_hint).pack(anchor="w", padx=6, pady=(5, 0))
        ttk.Label(browser_box, textvariable=self.browser_mode_hint_var, style="Muted.TLabel", wraplength=500).pack(anchor="w", padx=26, pady=(2, 6))

        rows = [
            ("Application limit (0 = no limit)", self.max_apps_var, 0, 10000),
            ("Pages per search (0 = all)", self.max_pages_var, 0, 100),
        ]
        for offset, (label, var, lo, hi) in enumerate(rows, start=3):
            ttk.Label(behavior, text=label).grid(row=offset, column=0, sticky="w", pady=4)
            ttk.Spinbox(behavior, from_=lo, to=hi, textvariable=var, width=9).grid(row=offset, column=1, sticky="w", pady=4)

        ttk.Label(behavior, text="Pause between actions").grid(row=5, column=0, sticky="w", pady=4)
        delay_row = ttk.Frame(behavior)
        delay_row.grid(row=5, column=1, sticky="w")
        self.min_delay_spin = ttk.Spinbox(delay_row, from_=0, to=30, increment=0.5, textvariable=self.min_delay_var, width=6)
        self.min_delay_spin.pack(side="left")
        ttk.Label(delay_row, text=" to ").pack(side="left")
        self.max_delay_spin = ttk.Spinbox(delay_row, from_=0, to=60, increment=0.5, textvariable=self.max_delay_var, width=6)
        self.max_delay_spin.pack(side="left")
        ttk.Label(delay_row, text=" s", style="Muted.TLabel").pack(side="left")
        self.delay_warning_var = tk.StringVar(value="")
        self.delay_warning_label = ttk.Label(behavior, textvariable=self.delay_warning_var, style="Warning.TLabel", wraplength=500)
        self.delay_warning_label.grid(row=6, column=0, columnspan=2, sticky="w", pady=(1, 4))
        self.min_delay_var.trace_add("write", lambda *_: self._sync_delay_warning())
        self.max_delay_var.trace_add("write", lambda *_: self._sync_delay_warning())

        ttk.Label(behavior, text="Waiting reminder").grid(row=7, column=0, sticky="w", pady=4)
        failsafe_row = ttk.Frame(behavior)
        failsafe_row.grid(row=7, column=1, sticky="w")
        ttk.Spinbox(failsafe_row, from_=15, to=900, increment=15, textvariable=self.failsafe_seconds_var, width=7).pack(side="left")
        ttk.Label(failsafe_row, text=" seconds without progress", style="Muted.TLabel").pack(side="left", padx=(5, 0))
        ttk.Label(behavior, text="If the search takes longer than this, we will let you know and help you continue.", style="Muted.TLabel", wraplength=500).grid(row=8, column=0, columnspan=2, sticky="w", pady=(0, 5))

        ttk.Checkbutton(behavior, text="Ask me before sending each application", variable=self.review_var).grid(row=9, column=0, columnspan=2, sticky="w", pady=(8, 3))
        ttk.Checkbutton(behavior, text="Follow the company when offered", variable=self.follow_var).grid(row=10, column=0, columnspan=2, sticky="w", pady=3)

        ttk.Label(behavior, text="Companies to skip", style="Section.TLabel").grid(row=11, column=0, columnspan=2, sticky="w", pady=(12, 2))
        self.company_blacklist_text = tk.Text(behavior, height=3, width=24, font=("Segoe UI", 10), padx=8, pady=6)
        self.company_blacklist_text.grid(row=12, column=0, columnspan=2, sticky="ew")
        ttk.Label(behavior, text="Words to skip in job titles", style="Section.TLabel").grid(row=13, column=0, columnspan=2, sticky="w", pady=(10, 2))
        self.title_blacklist_text = tk.Text(behavior, height=3, width=24, font=("Segoe UI", 10), padx=8, pady=6)
        self.title_blacklist_text.grid(row=14, column=0, columnspan=2, sticky="ew")

        actions = ttk.Frame(tab)
        self.setup_actions = actions
        actions.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        self.maximize_coverage_button = ttk.Button(actions, text="Expand my search", command=self._maximize_coverage)
        self.maximize_coverage_button.pack(side="left")
        HoverTooltip(
            self.maximize_coverage_button,
            "Removes the autojobs success/page caps, searches Any time, clears experience filters, switches to Automatic, disables manual review and post-open location rejection, enables the deterministic last-resort choice fallback, and raises overly aggressive delays to about 3-7 seconds. Your positions, search locations, work-type filters and blacklists are preserved, so Remote-only or country-specific campaigns stay Remote-only/country-specific. Configure truthful work-eligibility answers before long unattended runs.",
            width=560,
        )
        ttk.Button(actions, text="Continue to answers →", style="Accent.TButton", command=self._save_and_questions_tab).pack(side="right", padx=8)

    def _build_questions_tab(self) -> None:
        page = ScrollablePage(self.questions_tab)
        self._pages.append(page)
        self.questions_page = page
        tab = page.content
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)

        intro = ttk.Frame(tab)
        intro.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        intro.columnconfigure(0, weight=1)
        ttk.Label(intro, text="Your answers, your way", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            intro, text="1. Find a question   2. Add your answer   3. We save it for you.\nUse accurate information. You can review everything before starting.",
            style="Subtitle.TLabel", wraplength=700,
        ).grid(row=1, column=0, sticky="ew", pady=4)
        self.answer_count_var = tk.StringVar(value="No answers yet")
        ttk.Label(intro, textvariable=self.answer_count_var, style="Muted.TLabel").grid(row=2, column=0, sticky="w")
        self.defaults_toggle = ttk.Button(tab, text="Show options for unanswered questions", command=self._toggle_answer_defaults)
        self.defaults_toggle.grid(row=3, column=0, sticky="w", pady=8)
        self._defaults_visible = False
        defaults = ttk.LabelFrame(tab, text="When I do not have an answer yet • automatic mode", style="Card.TLabelframe")
        self.answer_defaults_frame = defaults
        defaults.grid(row=4, column=0, sticky="ew", pady=(0, 10))
        defaults.grid_remove()
        for col in range(4):
            defaults.columnconfigure(col, weight=1)
        self.default_numeric_var = tk.StringVar(value="0")
        self.default_text_var = tk.StringVar(value="N/A")
        self.default_boolean_var = tk.StringVar(value="No")
        self.social_strategy_label_var = tk.StringVar(value=list(SOCIAL_STRATEGY_LABELS.keys())[0])
        self.autonomous_choice_var = tk.BooleanVar(value=True)

        numeric = ttk.LabelFrame(defaults, text="Numbers")
        numeric.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        ttk.Label(numeric, text="When asked for a number", style="Muted.TLabel").pack(anchor="w", padx=8, pady=(6, 2))
        self.default_numeric_entry = ttk.Entry(numeric, textvariable=self.default_numeric_var)
        self.default_numeric_entry.pack(fill="x", padx=8)
        ttk.Label(numeric, text="For example: years of experience", style="Muted.TLabel").pack(anchor="w", padx=8, pady=(2, 6))

        text = ttk.LabelFrame(defaults, text="Free text")
        text.grid(row=0, column=1, sticky="nsew", padx=5)
        ttk.Label(text, text="When asked for text", style="Muted.TLabel").pack(anchor="w", padx=8, pady=(6, 2))
        self.default_text_entry = ttk.Entry(text, textvariable=self.default_text_var)
        self.default_text_entry.pack(fill="x", padx=8)
        ttk.Label(text, text="Use an accurate answer", style="Muted.TLabel").pack(anchor="w", padx=8, pady=(2, 6))

        boolean = ttk.LabelFrame(defaults, text="Yes / No")
        boolean.grid(row=0, column=2, sticky="nsew", padx=5)
        ttk.Label(boolean, text="When asked yes or no", style="Muted.TLabel").pack(anchor="w", padx=8, pady=(6, 2))
        self.default_boolean_combo = ttk.Combobox(boolean, textvariable=self.default_boolean_var, values=("Yes", "No"), state="readonly")
        self.default_boolean_combo.pack(fill="x", padx=8)
        ttk.Label(boolean, text="Available choices are checked before use", style="Muted.TLabel").pack(anchor="w", padx=8, pady=(2, 6))

        social = ttk.LabelFrame(defaults, text="Diversity")
        social.grid(row=0, column=3, sticky="nsew", padx=(5, 0))
        ttk.Label(social, text="When you have not answered", style="Muted.TLabel").pack(anchor="w", padx=8, pady=(6, 2))
        self.social_strategy_combo = ttk.Combobox(social, textvariable=self.social_strategy_label_var, values=list(SOCIAL_STRATEGY_LABELS.keys()), state="readonly", width=31)
        self.social_strategy_combo.pack(fill="x", padx=8)
        ttk.Label(social, text="We never guess personal information", style="Muted.TLabel").pack(anchor="w", padx=8, pady=(2, 6))


        self.default_cards = [numeric, text, boolean, social]
        autonomous = ttk.Frame(defaults)
        self.default_autonomous = autonomous
        autonomous.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        ttk.Checkbutton(
            autonomous,
            text="Allow choosing the first available option when no answer matches", 
            variable=self.autonomous_choice_var,
        ).pack(side="left", fill="x", expand=True)
        HoverTooltip(
            autonomous,
            "Language-agnostic last resort. autojobs first tries learned answers, profile data, HTML semantics, existing LinkedIn autofill and your typed defaults. Only if none can map to the available options will it pick the first concrete option. Disable this if you prefer ambiguous applications to be skipped.",
            width=560,
        )

        ttk.Label(autonomous, text="This may choose an answer that does not represent you. Turn it off to skip unclear questions. Guided mode asks you instead.", style="Muted.TLabel", wraplength=650).pack(fill="x", pady=6)
        profile_tools = ttk.Frame(tab)
        profile_tools.grid(row=1, column=0, sticky="ew", pady=(4, 10))
        profile_tools.columnconfigure(0, weight=1)
        profile_tools.columnconfigure(1, weight=1)
        self.import_ai_button = ttk.Button(profile_tools, text="Import answers…", command=self._import_answer_profile)
        self.import_ai_button.grid(row=0, column=0, sticky="ew", padx=(0, 4), pady=3)
        self.where_ai_files_button = ttk.Button(
            profile_tools, text="How do I prepare my answers?", command=self._open_portable_files_folder
        )
        self.where_ai_files_button.grid(row=1, column=0, sticky="ew", padx=(0, 4), pady=3)
        HoverTooltip(
            self.where_ai_files_button,
            "Opens the folder containing prompt.txt, answer-profile-template.json, themes.json and autojobs.exe. "
            "Those are the files referenced by the AI answer workflow.",
            width=460,
        )
        HoverTooltip(
            self.import_ai_button,
            "NO JSON KNOWLEDGE NEEDED\n\n1. Find prompt.txt and answer-profile-template.json beside autojobs.exe.\n2. Open ChatGPT and attach those two files + your CV/resume PDF.\n3. Tell ChatGPT to follow prompt.txt and generate your factual answer profile.\n4. ChatGPT should give you a ready file named import_me_on_autojobs.json.\n5. Click Import AI answers… and select that file.\n6. Review the imported answers here before running.\n\nStart with Supervised mode after importing.",
            width=540,
        )
        ttk.Button(profile_tools, text="Export my answers…", command=self._export_answer_profile).grid(row=1, column=1, sticky="ew", padx=(4, 0), pady=3)
        ttk.Button(profile_tools, text="Continue to Run →", style="Accent.TButton", command=lambda: self.notebook.select(self.run_tab)).grid(row=0, column=1, sticky="ew", padx=(4, 0), pady=3)

        workspace = tk.PanedWindow(
            tab, orient="horizontal", sashwidth=6, relief="flat", borderwidth=0,
            background=self.current_palette["background"],
        )
        self.question_workspace = workspace
        workspace.grid(row=2, column=0, sticky="nsew")

        left = ttk.LabelFrame(workspace, text="Find a question", style="Card.TLabelframe")
        right = ttk.LabelFrame(workspace, text="Your answer", style="Card.TLabelframe")
        workspace.add(left, stretch="always", minsize=220)
        workspace.add(right, stretch="always", minsize=260)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(2, weight=1)
        right.columnconfigure(0, weight=1)

        filterbar = ttk.Frame(left)
        filterbar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 5))
        self.question_search_var = tk.StringVar()
        self.question_scope_var = tk.StringVar(value="All questions")
        self.question_category_var = tk.StringVar(value="All categories")
        filterbar.columnconfigure(0, weight=1)
        filterbar.columnconfigure(1, weight=1)
        ttk.Label(filterbar, text="Search questions", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        search_entry = ttk.Entry(filterbar, textvariable=self.question_search_var, width=20)
        search_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 6))
        self.question_search_var.trace_add("write", self._schedule_question_search)
        scope = ttk.Combobox(
            filterbar, textvariable=self.question_scope_var,
            values=("All questions", "Dublin essentials", "Answered", "Diversity and inclusion"),
            state="readonly", width=18,
        )
        scope.grid(row=2, column=0, sticky="ew", padx=(0, 4))
        scope.bind("<<ComboboxSelected>>", self._schedule_question_search)
        category = ttk.Combobox(filterbar, textvariable=self.question_category_var, values=("All categories",) + CATEGORIES, state="readonly", width=18)
        category.grid(row=2, column=1, sticky="ew")
        category.bind("<<ComboboxSelected>>", self._schedule_question_search)

        self.question_results_var = tk.StringVar()
        ttk.Label(left, textvariable=self.question_results_var, style="Muted.TLabel", wraplength=420).grid(row=1, column=0, sticky="w", pady=5)
        columns = ("category", "question", "answer")
        self.question_tree = ttk.Treeview(left, columns=columns, show="headings", selectmode="browse")
        self.question_tree.heading("category", text="Category")
        self.question_tree.heading("question", text="Question")
        self.question_tree.heading("answer", text="Answer")
        self.question_tree.column("category", width=160, anchor="w")
        self.question_tree.column("question", width=500, anchor="w")
        self.question_tree.column("answer", width=190, anchor="w")
        self.question_tree.grid(row=2, column=0, sticky="nsew")
        qscroll = ttk.Scrollbar(left, orient="vertical", command=self.question_tree.yview)
        qscroll.grid(row=2, column=1, sticky="ns")
        qhorizontal = ttk.Scrollbar(left, orient="horizontal", command=self.question_tree.xview)
        qhorizontal.grid(row=3, column=0, sticky="ew")
        self.question_tree.configure(yscrollcommand=qscroll.set, xscrollcommand=qhorizontal.set)
        self.question_tree.bind("<<TreeviewSelect>>", lambda _e: self._load_question_editor())
        self.question_tree.bind("<Double-1>", lambda _e: self._focus_question_editor())

        left_actions = ttk.Frame(left)
        left_actions.grid(row=4, column=0, sticky="ew", pady=(7, 0))
        ttk.Button(left_actions, text="Add another question…", command=self._add_answer).pack(side="left")

        self.question_editor_title_var = tk.StringVar(value="Select a question")
        self.question_editor_meta_var = tk.StringVar(value="")
        self.question_editor_help_var = tk.StringVar(value="Choose a question and add your answer. We save it automatically.")
        ttk.Label(right, textvariable=self.question_editor_title_var, font=("Segoe UI", 11, "bold"), wraplength=410, justify="left").grid(row=0, column=0, sticky="w")
        ttk.Label(right, textvariable=self.question_editor_meta_var, style="Muted.TLabel", wraplength=410).grid(row=1, column=0, sticky="w", pady=(3, 8))
        ttk.Label(right, textvariable=self.question_editor_help_var, wraplength=410, justify="left").grid(row=2, column=0, sticky="w", pady=(0, 12))
        ttk.Separator(right).grid(row=3, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(right, text="Your answer", style="Section.TLabel").grid(row=4, column=0, sticky="w")
        self.question_editor_value_var = tk.StringVar()
        self.question_editor_host = ttk.Frame(right)
        self.question_editor_host.grid(row=5, column=0, sticky="ew", pady=(4, 4))
        self.question_editor_host.columnconfigure(0, weight=1)
        self.question_editor_widget: tk.Widget | None = None
        self._rebuild_question_editor_widget([])
        self.question_editor_note_var = tk.StringVar(value="Your specific answers take priority over general answers.")
        ttk.Label(right, textvariable=self.question_editor_note_var, style="Muted.TLabel", wraplength=410).grid(row=6, column=0, sticky="w", pady=(0, 12))
        editor_buttons = ttk.Frame(right)
        editor_buttons.grid(row=7, column=0, sticky="ew")
        self.question_save_button = ttk.Button(editor_buttons, text="Done editing", command=self._save_question_editor, state="disabled")
        self.question_save_button.pack(side="left")
        self.question_clear_button = ttk.Button(editor_buttons, text="Clear answer", command=self._clear_catalog_answer, state="disabled")
        self.question_clear_button.pack(side="left", padx=6)

    def _build_run_tab(self) -> None:
        page = ScrollablePage(self.run_tab, minimum_height=600)
        self._pages.append(page)
        tab = page.content
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(4, weight=1)

        mode_box = ttk.LabelFrame(tab, text="Ready for your next step", padding=10)
        mode_box.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.run_mode_summary_var = tk.StringVar(value="Guided")
        ttk.Label(mode_box, textvariable=self.run_mode_summary_var, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(mode_box, text="Guided mode asks you when an answer is missing. Automatic mode uses your answers and preferences. Your settings stay protected while the search is running.", wraplength=850, style="Muted.TLabel").pack(fill="x", pady=4)

        top = ttk.Frame(tab)
        self.run_controls = top
        top.grid(row=1, column=0, sticky="ew")
        self.start_button = ttk.Button(top, text="Start with guidance", style="Accent.TButton", command=self._start_run)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(top, text="Stop", command=self._stop_run, state="disabled")
        self.stop_button.pack(side="left", padx=8)
        ttk.Button(top, text="View applications →", command=lambda: self.notebook.select(self.applied_tab)).pack(side="right")

        self.status_var = tk.StringVar(value="Ready whenever you are.")
        self.current_job_var = tk.StringVar(value="")
        ttk.Label(tab, textvariable=self.status_var, font=("Segoe UI", 11, "bold"), wraplength=850).grid(row=2, column=0, sticky="ew", pady=(12, 2))
        ttk.Label(tab, textvariable=self.current_job_var, wraplength=850).grid(row=3, column=0, sticky="ew", pady=(0, 8))

        run_area = ttk.Frame(tab)
        self.run_area = run_area
        run_area.grid(row=4, column=0, sticky="nsew")
        run_area.columnconfigure(0, weight=1)
        run_area.rowconfigure(3, weight=1)
        stats_frame = ttk.Frame(run_area)
        self.stats_frame = stats_frame
        self.stat_boxes = []
        stats_frame.grid(row=0, column=0, sticky="ew")
        stat_names = ("discovered", "processed", "filtered", "attempted", "applied", "skipped", "failed")
        self.stat_vars = {name: tk.StringVar(value="0") for name in stat_names}
        stat_labels = ("Found", "Checked", "Not a match", "Started", "Sent", "Skipped", "Needs attention")
        for idx, name in enumerate(stat_names):
            box = ttk.LabelFrame(stats_frame, text=stat_labels[idx], padding=8)
            self.stat_boxes.append(box)
            box.grid(row=0, column=idx, sticky="ew", padx=(0 if idx == 0 else 4, 0))
            ttk.Label(box, textvariable=self.stat_vars[name], font=("Segoe UI", 15, "bold")).pack()
            stats_frame.columnconfigure(idx, weight=1)
        self.coverage_var = tk.StringVar(value="Easy Apply completion: —")
        ttk.Label(run_area, textvariable=self.coverage_var, style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.progress = ttk.Progressbar(run_area, mode="determinate", maximum=10)
        self.progress.grid(row=2, column=0, sticky="ew", pady=8)
        self.log_text = ScrolledText(run_area, height=10, width=30, state="disabled", font=("Segoe UI", 10), wrap="word", padx=12, pady=10)
        self.log_text.grid(row=3, column=0, sticky="nsew")
        ttk.Button(run_area, text="Details for support…", command=self._open_log_file).grid(row=4, column=0, sticky="e", pady=(6, 0))

    def _build_answers_tab(self) -> None:
        page = ScrollablePage(self.answers_tab, minimum_height=450)
        self._pages.append(page)
        tab = page.content
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)
        ttk.Label(
            tab,
            text="Questions you added or answered during a guided search. These answers take priority over your profile and general answers.",
            wraplength=980,
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        columns = ("question", "answer")
        self.answers_tree = ttk.Treeview(tab, columns=columns, show="headings", height=8, selectmode="browse")
        self.answers_tree.heading("question", text="Question")
        self.answers_tree.heading("answer", text="Saved answer")
        self.answers_tree.column("question", width=720, anchor="w")
        self.answers_tree.column("answer", width=300, anchor="w")
        self.answers_tree.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(tab, orient="vertical", command=self.answers_tree.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(tab, orient="horizontal", command=self.answers_tree.xview)
        horizontal.grid(row=2, column=0, sticky="ew")
        self.answers_tree.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        buttons = ttk.Frame(tab)
        buttons.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        for column in range(3):
            buttons.columnconfigure(column, weight=1)
        ttk.Button(buttons, text="Add", command=self._add_answer).grid(row=0, column=0, sticky="ew", padx=3, pady=3)
        ttk.Button(buttons, text="Edit", command=self._edit_answer).grid(row=0, column=1, sticky="ew", padx=3, pady=3)
        ttk.Button(buttons, text="Delete", command=self._delete_answer).grid(row=0, column=2, sticky="ew", padx=3, pady=3)
        ttk.Button(buttons, text="Import AI answers…", command=self._import_answer_profile).grid(row=1, column=0, sticky="ew", padx=3, pady=3)
        ttk.Button(buttons, text="Export answer template…", command=self._export_answer_profile).grid(row=1, column=1, columnspan=2, sticky="ew", padx=3, pady=3)

    def _build_applied_tab(self) -> None:
        page = ScrollablePage(self.applied_tab, minimum_height=560)
        self._pages.append(page)
        tab = page.content
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(4, weight=1)
        ttk.Label(tab, text="Applied • your applications", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(tab, text="See what was sent and what needs attention. An application is marked as sent only when its submission was confirmed.", style="Muted.TLabel", wraplength=800).grid(row=1, column=0, sticky="ew", pady=(4, 12))
        filters = ttk.Frame(tab)
        filters.grid(row=2, column=0, sticky="ew")
        filters.columnconfigure(0, weight=1)
        ttk.Label(filters, text="Search job title, company, or location").grid(row=0, column=0, sticky="w")
        self.history_search_var = tk.StringVar()
        self.history_filter_var = tk.StringVar(value="Sent")
        ttk.Entry(filters, textvariable=self.history_search_var).grid(row=1, column=0, sticky="ew", padx=(0, 8))
        ttk.Label(filters, text="Show").grid(row=0, column=1, sticky="w")
        selection = ttk.Combobox(filters, textvariable=self.history_filter_var, values=("Sent", "All", "Not sent", "Needs attention"), state="readonly", width=21)
        selection.grid(row=1, column=1, sticky="ew")
        self.history_search_var.trace_add("write", self._schedule_history_search)
        self.history_filter_var.trace_add("write", self._schedule_history_search)
        self.history_status_var = tk.StringVar(value="Loading your history…")
        ttk.Label(tab, textvariable=self.history_status_var, style="Muted.TLabel", wraplength=800).grid(row=3, column=0, sticky="ew", pady=8)
        table = ttk.Frame(tab)
        table.grid(row=4, column=0, sticky="nsew")
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        self.applied_tree = ttk.Treeview(table, columns=("date", "title", "company", "location", "status"), show="headings", selectmode="browse", height=8)
        for key, title, width in (("date", "When", 150), ("title", "Job title", 240), ("company", "Company", 160), ("location", "Location", 150), ("status", "Status", 150)):
            self.applied_tree.heading(key, text=title)
            self.applied_tree.column(key, width=width, minwidth=100)
        self.applied_tree.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(table, orient="vertical", command=self.applied_tree.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(table, orient="horizontal", command=self.applied_tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.applied_tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.applied_tree.bind("<<TreeviewSelect>>", self._show_application_details)
        details = ttk.LabelFrame(tab, text="Application details", style="Card.TLabelframe")
        details.grid(row=5, column=0, sticky="ew", pady=8)
        self.history_detail_var = tk.StringVar(value="Select an application to see its details.")
        ttk.Label(details, textvariable=self.history_detail_var, wraplength=800, justify="left").pack(fill="x", pady=4)
        self.history_open_button = ttk.Button(details, text="View job on LinkedIn ↗", command=self._open_application, state="disabled")
        self.history_open_button.pack(anchor="w", pady=4)
        actions = ttk.Frame(tab)
        actions.grid(row=6, column=0, sticky="ew")
        ttk.Button(actions, text="Refresh", command=lambda: self._refresh_applied(force=True)).pack(side="left")
        self.history_prev_button = ttk.Button(actions, text="← Previous", command=lambda: self._change_history_page(-1))
        self.history_prev_button.pack(side="left", padx=6)
        self.history_next_button = ttk.Button(actions, text="Next →", command=lambda: self._change_history_page(1))
        self.history_next_button.pack(side="left")
        ttk.Button(actions, text="History folder", command=self._open_results_folder).pack(side="right")

    def _refresh_applied(self, *, force: bool = False) -> None:
        if self._history_loading:
            return
        path = Path(self.config_data.output_csv).expanduser()
        try:
            stat = path.stat()
            signature = (str(path), stat.st_mtime_ns, stat.st_size)
        except OSError:
            signature = (str(path), None, None)
        if not force and signature == self._history_signature:
            return
        self._history_loading = True
        self.history_status_var.set("Loading your history…")
        def load():
            try:
                rows = load_application_history(path)
                self.ui_queue.put(("history", rows, signature))
            except Exception:
                logging.getLogger(__name__).exception("Could not read application history")
                self.ui_queue.put(("history_error",))
        threading.Thread(target=load, daemon=True).start()

    def _schedule_history_search(self, *_args) -> None:
        if self._history_search_after_id is not None:
            self.after_cancel(self._history_search_after_id)
        self._history_page = 0
        self._history_search_after_id = self.after(180, self._render_history)

    def _change_history_page(self, direction: int) -> None:
        self._history_page = max(0, self._history_page + direction)
        self._render_history()

    def _render_history(self) -> None:
        self._history_search_after_id = None
        query = normalize_question(self.history_search_var.get())
        scope = self.history_filter_var.get()
        rows = [row for row in self._history_rows
                if (scope == "All" or (scope == "Sent" and row["status"] == "submitted")
                    or (scope == "Not sent" and row["status"] != "submitted")
                    or (scope == "Needs attention" and row["status"] in ("failed", "unknown")))
                and (not query or query in normalize_question(" ".join(row.get(key, "") for key in ("title", "company", "location"))))]
        page_size = 50
        self._history_page = min(self._history_page, max(0, (len(rows) - 1) // page_size))
        start = self._history_page * page_size
        self._visible_history = rows[start:start + page_size]
        children = self.applied_tree.get_children()
        if children:
            self.applied_tree.delete(*children)
        labels = {"submitted": "Sent", "skipped": "Not sent", "failed": "Needs attention", "unknown": "Not confirmed"}
        for index, row in enumerate(self._visible_history):
            self.applied_tree.insert("", "end", iid=str(index), values=(row.get("timestamp", ""), row.get("title") or "Job title not provided", row.get("company") or "Not provided", row.get("location") or "Not provided", labels.get(row["status"], "Not confirmed")))
        self.history_prev_button.configure(state="normal" if start else "disabled")
        self.history_next_button.configure(state="normal" if start + page_size < len(rows) else "disabled")
        sent = sum(row["status"] == "submitted" for row in self._history_rows)
        self.history_status_var.set(f"{sent} sent in your history • showing {start + 1}–{min(start + page_size, len(rows))} of {len(rows)}" if rows else
                                   ("No applications match this filter. Try another search or choose All." if self._history_rows else "Your history starts here. Applications will appear after you begin in 3. Run."))
        self._show_application_details()

    def _selected_application(self):
        selected = self.applied_tree.selection()
        return self._visible_history[int(selected[0])] if selected else None

    def _show_application_details(self, _event=None) -> None:
        row = self._selected_application()
        if row is None:
            self.history_detail_var.set("Select an application to see its details.")
            self.history_open_button.configure(state="disabled")
            return
        self.history_detail_var.set(f"{row.get('title') or 'Job title not provided'} • {row.get('company') or 'Company not provided'}\n{row.get('location') or 'Location not provided'} • {row.get('timestamp') or 'Date not provided'}\n{friendly_result_reason(row.get('result', ''))}")
        self.history_open_button.configure(state="normal" if safe_application_url(row.get("url", "")) else "disabled")

    def _open_application(self) -> None:
        row = self._selected_application()
        url = safe_application_url(row.get("url", "")) if row else ""
        if url:
            webbrowser.open(url)

    def _build_ai_tab(self) -> None:
        self.ai_tab.columnconfigure(0, weight=1)
        self.ai_tab.rowconfigure(0, weight=1)
        card = ttk.LabelFrame(self.ai_tab, text="AI", padding=24)
        card.grid(row=0, column=0)
        ttk.Label(card, text="Coming soon", font=("Segoe UI", 18, "bold")).pack()
        ttk.Label(card, text="by borerto", font=("Segoe UI", 9, "italic"), style="Muted.TLabel").pack(pady=(5, 0))

    def _show_credits(self) -> None:
        CreditsDialog(self)

    def _notebook_motion(self, event) -> None:
        try:
            index = self.notebook.index(f"@{event.x},{event.y}")
        except Exception:
            self.ai_balloon.hide()
            return
        if index == self.ai_tab_index:
            self.ai_balloon.show(self.winfo_pointerx() + 12, self.winfo_pointery() + 16)
        else:
            self.ai_balloon.hide()

    def _file_row(self, parent, row: int, label: str, variable: tk.StringVar, filetypes) -> ttk.Entry:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=1, sticky="ew", pady=4)
        frame.columnconfigure(0, weight=1)
        entry = ttk.Entry(frame, textvariable=variable)
        entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(frame, text="Browse…", command=lambda: self._browse_file(variable, filetypes)).grid(row=0, column=1, padx=(6, 0))
        return entry

    def _load_config_into_ui(self) -> None:
        was_loading = self._autosave_loading
        self._autosave_loading = True
        try:
            self._populate_config_ui()
        finally:
            self._autosave_loading = was_loading

    def _populate_config_ui(self) -> None:
        c = self.config_data
        self._set_text(self.positions_text, c.positions)
        self._set_text(self.locations_text, c.locations)
        self._set_text(self.company_blacklist_text, c.blacklist_companies)
        self._set_text(self.title_blacklist_text, c.blacklist_titles)
        self.resume_var.set(c.resume_path)
        self.cover_var.set(c.cover_letter_path)
        self.phone_var.set(c.phone_number)
        self.salary_var.set(c.salary)
        self.rate_var.set(c.hourly_rate)
        self.max_apps_var.set(c.max_applications)
        self.max_pages_var.set(c.max_pages_per_search)
        self.min_delay_var.set(c.min_delay_seconds)
        self.max_delay_var.set(c.max_delay_seconds)
        self.failsafe_seconds_var.set(c.failsafe_seconds)
        self.review_var.set(c.review_before_submit)
        self.follow_var.set(c.follow_company)
        self.headless_var.set(c.headless_browser)
        self.post_open_location_var.set(c.post_open_location_filter)
        self.run_mode_label_var.set(next((k for k, v in RUN_MODE_LABELS.items() if v == c.run_mode), list(RUN_MODE_LABELS.keys())[0]))
        self.default_numeric_var.set(c.default_numeric_answer)
        self.default_text_var.set(c.default_text_answer)
        self.default_boolean_var.set(c.default_boolean_answer)
        self.social_strategy_label_var.set(next((k for k, v in SOCIAL_STRATEGY_LABELS.items() if v == c.social_question_strategy), list(SOCIAL_STRATEGY_LABELS.keys())[0]))
        self.autonomous_choice_var.set(c.automatic_choice_strategy == "first_valid")
        label = next((k for k, v in UI_DATE_FILTERS.items() if v == c.date_posted), "Past 24 hours")
        self.date_label_var.set(label)
        for code, var in self.exp_vars.items():
            var.set(code in c.experience_levels)
        for code, var in self.work_vars.items():
            var.set(code in c.work_types)
        self._refresh_answers_tree()
        self._refresh_question_library()
        self._sync_run_mode_label()
        self._sync_browser_mode_hint()
        self._sync_delay_warning()
        self.progress.configure(maximum=max(1, c.max_applications if c.max_applications > 0 else 1))

    def _install_autosave(self) -> None:
        names = (
            "resume", "cover", "phone", "salary", "rate", "max_apps", "max_pages",
            "min_delay", "max_delay", "failsafe_seconds", "review", "follow", "headless",
            "post_open_location", "run_mode_label", "default_numeric", "default_text",
            "default_boolean", "social_strategy_label", "autonomous_choice", "date_label", "theme",
        )
        for name in names:
            getattr(self, name + "_var").trace_add("write", self._schedule_autosave)
        for var in (*self.exp_vars.values(), *self.work_vars.values()):
            var.trace_add("write", self._schedule_autosave)
        for widget in (self.positions_text, self.locations_text, self.company_blacklist_text, self.title_blacklist_text):
            widget.edit_modified(False)
            widget.bind("<<Modified>>", self._text_changed, add="+")
        self.question_editor_value_var.trace_add("write", self._question_edited)
        for page in self._pages:
            page.install_bindings(page.content)

    def _text_changed(self, event) -> None:
        if event.widget.edit_modified():
            event.widget.edit_modified(False)
            self._schedule_autosave()

    def _settings_locked(self) -> bool:
        return self._run_active or bool(self.worker and self.worker.is_alive())

    def _schedule_autosave(self, *_args) -> None:
        if self._autosave_loading:
            return
        self._settings_dirty = True
        if self._autosave_after_id is not None:
            self.after_cancel(self._autosave_after_id)
            self._autosave_after_id = None
        if self._settings_locked():
            self.save_status_var.set("Saving paused while applications are in progress")
            return
        self.save_status_var.set("Saving your changes…")
        self._autosave_after_id = self.after(650, self._autosave)

    def _autosave(self) -> None:
        self._autosave_after_id = None
        if self._settings_dirty:
            self._save_from_ui(show_message=False)

    def _question_edited(self, *_args) -> None:
        if self._loading_question or self._autosave_loading or not self._editing_question_key or self._settings_locked():
            return
        self._question_drafts[self._editing_question_key] = self.question_editor_value_var.get()
        self._schedule_autosave()

    def _set_settings_locked(self, locked: bool) -> None:
        if locked:
            self._locked_widgets = []
            def lock(widget):
                if isinstance(widget, (ttk.Entry, ttk.Combobox, ttk.Spinbox, ttk.Checkbutton, ttk.Button, tk.Text)):
                    state = str(widget.cget("state"))
                    self._locked_widgets.append((widget, state))
                    widget.configure(state="disabled")
                for child in widget.winfo_children():
                    lock(child)
            for tab in (self.setup_tab, self.questions_tab, self.answers_tab, self.appearance_frame):
                lock(tab)
            lock(self.dismiss_disclaimer_button)
            self.save_status_var.set("Saving paused during Run • stop the search to edit your preferences")
        else:
            for widget, state in self._locked_widgets:
                if widget.winfo_exists():
                    widget.configure(state=state)
            self._locked_widgets = []
            self._load_question_editor()

    def _tab_changed(self, _event=None) -> None:
        if not hasattr(self, "save_status_var"):
            return
        if self._settings_dirty and not self._settings_locked():
            self._save_from_ui(show_message=False)
        if self.notebook.select() == str(self.applied_tab):
            self._refresh_applied()
        self._schedule_responsive_layout()

    def _save_from_ui(self, show_message: bool = True) -> bool:
        if self._settings_locked():
            self.save_status_var.set("Saving paused during Run • stop the search to edit your preferences")
            return False
        if self._autosave_after_id is not None:
            self.after_cancel(self._autosave_after_id)
            self._autosave_after_id = None
        try:
            # Validate a copy so an incomplete field never alters the active settings.
            c = deepcopy(self.config_data)
            c.positions = self._get_lines(self.positions_text)
            c.locations = self._get_lines(self.locations_text)
            if not c.positions:
                raise ValueError("Add at least one job title in 1. Search.")
            if not c.locations:
                c.locations = ["Worldwide"]
            c.blacklist_companies = self._get_lines(self.company_blacklist_text)
            c.blacklist_titles = self._get_lines(self.title_blacklist_text)
            c.resume_path = self.resume_var.get().strip()
            c.cover_letter_path = self.cover_var.get().strip()
            c.phone_number = self.phone_var.get().strip()
            c.salary = self.salary_var.get().strip()
            c.hourly_rate = self.rate_var.get().strip()
            c.experience_levels = [code for code, var in self.exp_vars.items() if var.get()]
            c.work_types = [code for code, var in self.work_vars.items() if var.get()]
            c.date_posted = UI_DATE_FILTERS.get(self.date_label_var.get(), "r86400")
            c.max_applications = int(self.max_apps_var.get())
            c.max_pages_per_search = int(self.max_pages_var.get())
            c.min_delay_seconds = float(self.min_delay_var.get())
            c.max_delay_seconds = float(self.max_delay_var.get())
            c.failsafe_seconds = int(self.failsafe_seconds_var.get())
            if c.max_applications < 0 or c.max_pages_per_search < 0:
                raise ValueError("Use zero for no limit, or a positive number.")
            if not all(math.isfinite(value) for value in (c.min_delay_seconds, c.max_delay_seconds)) or not 0 <= c.min_delay_seconds <= c.max_delay_seconds:
                raise ValueError("The pause must start at zero or more, and end at the same or a higher value.")
            if not 15 <= c.failsafe_seconds <= 900:
                raise ValueError("The waiting reminder must be between 15 and 900 seconds.")
            c.review_before_submit = bool(self.review_var.get())
            c.follow_company = bool(self.follow_var.get())
            c.headless_browser = bool(self.headless_var.get())
            c.post_open_location_filter = bool(self.post_open_location_var.get())
            c.run_mode = RUN_MODE_LABELS.get(self.run_mode_label_var.get(), "supervised")
            numeric_default = self.default_numeric_var.get().strip() or "0"
            try:
                float(numeric_default.replace(",", "."))
            except ValueError as exc:
                raise ValueError("Use a number for the general answer, such as 0, 1, or 3.5.") from exc
            c.default_numeric_answer = numeric_default.replace(",", ".")
            c.default_text_answer = self.default_text_var.get().strip() or "N/A"
            c.default_boolean_answer = self.default_boolean_var.get().strip() or "No"
            c.social_question_strategy = SOCIAL_STRATEGY_LABELS.get(self.social_strategy_label_var.get(), "prefer_not_to_say")
            c.automatic_choice_strategy = "first_valid" if self.autonomous_choice_var.get() else "skip"
            c.theme_name = self.current_theme_name
            for key, draft in self._question_drafts.items():
                value = draft.strip()
                definition = QUESTION_BY_KEY.get(key)
                if value and definition and definition.answer_type == "numeric":
                    value = value.replace(",", ".")
                    try:
                        if not math.isfinite(float(value)):
                            raise ValueError
                    except ValueError:
                        raise ValueError(f"Use a number for: {definition.label}") from None
                if value:
                    c.profile_answers[key] = value
                else:
                    c.profile_answers.pop(key, None)
            if not math.isfinite(float(c.default_numeric_answer)):
                raise ValueError("Use a valid number for the general answer.")
            c.save()
            self.config_data = c
            self._question_drafts.clear()
            self._settings_dirty = False
            self.save_status_var.set("All changes saved on this computer")
            self.progress.configure(maximum=max(1, c.max_applications if c.max_applications > 0 else 1))
            self._sync_run_mode_label()
            self._sync_browser_mode_hint()
            self._update_question_rows()
            return True
        except (ValueError, tk.TclError) as exc:
            self._settings_dirty = True
            detail = str(exc) if isinstance(exc, ValueError) else "Finish entering the numbers before continuing."
            if "invalid literal" in detail or "could not convert" in detail:
                detail = "Check the limits and pauses: use numbers only."
            self.save_status_var.set("Not saved yet • " + detail)
            if show_message:
                messagebox.showwarning("Vamos conferir um campo", detail, parent=self)
            return False
        except Exception:
            self._settings_dirty = True
            self.save_status_var.set("Your changes could not be saved. Check that the folder is writable and has space, then try again.")
            logging.getLogger(__name__).exception("Could not save settings")
            if show_message:
                messagebox.showerror("Could not save", self.save_status_var.get(), parent=self)
            return False

    def _save_and_questions_tab(self) -> None:
        if self._save_from_ui(show_message=False):
            self.notebook.select(self.questions_tab)

    def _maximize_coverage(self) -> None:
        """Apply a transparent preset for the widest unattended search/run coverage."""
        self.max_apps_var.set(0)
        self.max_pages_var.set(0)
        self.date_label_var.set(next(iter(UI_DATE_FILTERS)))
        for var in self.exp_vars.values():
            var.set(False)
        # Preserve work-model filters. If the user intentionally selected Remote,
        # Hybrid, or On-site, Maximum Coverage should maximize execution coverage
        # inside that intent instead of broadening the search against the user's goal.
        automatic_label = next((label for label, value in RUN_MODE_LABELS.items() if value == "automatic"), None)
        if automatic_label:
            self.run_mode_label_var.set(automatic_label)
        self.review_var.set(False)
        self.autonomous_choice_var.set(True)
        self.post_open_location_var.set(False)
        try:
            if float(self.min_delay_var.get()) < RECOMMENDED_MIN_DELAY_SECONDS:
                self.min_delay_var.set(RECOMMENDED_MIN_DELAY_SECONDS)
            if float(self.max_delay_var.get()) < RECOMMENDED_MAX_DELAY_SECONDS:
                self.max_delay_var.set(RECOMMENDED_MAX_DELAY_SECONDS)
        except Exception:
            self.min_delay_var.set(RECOMMENDED_MIN_DELAY_SECONDS)
            self.max_delay_var.set(RECOMMENDED_MAX_DELAY_SECONDS)
        self._sync_run_mode_label()
        self._sync_browser_mode_hint()
        if self._save_from_ui(show_message=False):
            messagebox.showinfo(
                "Coverage preset enabled",
                "autojobs will now run without its own application/page cap and will search all posting ages and work/experience filters.\n\n"
                "Your positions and blacklists were not changed. Location still scopes the LinkedIn search, but post-open location rejection is disabled so location metadata cannot block returned jobs. Delays are kept at 3-7 seconds or slower for a more conservative long-run cadence. For the highest Easy Apply completion rate, configure factual work-authorisation/visa answers in Answer Rules; autojobs will not invent those claims.",
                parent=self,
            )

    def _sync_delay_warning(self) -> None:
        if not hasattr(self, "delay_warning_var"):
            return
        try:
            minimum = float(self.min_delay_var.get())
            maximum = float(self.max_delay_var.get())
        except Exception:
            self.delay_warning_var.set("")
            return
        if delay_is_aggressive(minimum, maximum):
            self.delay_warning_var.set(
                "⚠ Aggressive delay. Very fast unattended activity can increase throttling, challenge, or temporary-restriction (soft ban) risk; "
                f"consider about {RECOMMENDED_MIN_DELAY_SECONDS:g}-{RECOMMENDED_MAX_DELAY_SECONDS:g} sec or slower."
            )
        else:
            self.delay_warning_var.set("")

    def _confirm_aggressive_delay(self) -> bool:
        try:
            minimum = float(self.config_data.min_delay_seconds)
            maximum = float(self.config_data.max_delay_seconds)
        except Exception:
            return True
        if not delay_is_aggressive(minimum, maximum):
            return True
        logging.getLogger(__name__).warning("Aggressive action delay configured: %.2f-%.2f sec", minimum, maximum)
        return messagebox.askyesno(
            "Very low action delay",
            delay_warning_text(minimum, maximum)
            + "\n\nContinue this run anyway?",
            parent=self,
        )

    def _sync_run_mode_label(self) -> None:
        mode = RUN_MODE_LABELS.get(self.run_mode_label_var.get(), self.config_data.run_mode)
        if hasattr(self, "run_mode_summary_var"):
            self.run_mode_summary_var.set("Guided" if mode == "supervised" else "Automatic")
        if hasattr(self, "start_button"):
            self.start_button.configure(text="Start with guidance" if mode == "supervised" else "Start automatically")
        self._update_header_mode()

    def _sync_browser_mode_hint(self) -> None:
        if not hasattr(self, "headless_var"):
            return
        if self.headless_var.get():
            text = "Chrome works without showing a window. First, use Open LinkedIn login to connect your account."
        else:
            text = "You can watch Chrome while we look for jobs."
        if hasattr(self, "browser_mode_hint_var"):
            self.browser_mode_hint_var.set(text)
        self._update_header_mode()

    def _update_header_mode(self) -> None:
        if not hasattr(self, "header_mode_var") or not hasattr(self, "run_mode_label_var"):
            return
        mode = RUN_MODE_LABELS.get(self.run_mode_label_var.get(), self.config_data.run_mode)
        headless = self.headless_var.get() if hasattr(self, "headless_var") else False
        browser = "Headless browser" if headless else "Visible browser"
        self.header_mode_var.set(f"{'Supervised' if mode == 'supervised' else 'Automatic'} • {browser}")

    def _toggle_answer_defaults(self) -> None:
        self._defaults_visible = not self._defaults_visible
        if self._defaults_visible:
            self.answer_defaults_frame.grid()
        else:
            self.answer_defaults_frame.grid_remove()
        self.defaults_toggle.configure(text=("Hide" if self._defaults_visible else "Show") + " options for unanswered questions")
        self._schedule_responsive_layout()

    def _schedule_question_search(self, *_args) -> None:
        if self._question_search_after_id is not None:
            self.after_cancel(self._question_search_after_id)
        self._question_search_after_id = self.after(180, self._refresh_question_library)

    def _update_question_rows(self) -> None:
        if not hasattr(self, "question_tree"):
            return
        configured = dict(self.config_data.profile_answers)
        configured.update(self._question_drafts)
        for key in self.question_tree.get_children():
            definition = QUESTION_BY_KEY[key]
            self.question_tree.item(key, values=(definition.category, definition.label, configured.get(key, "") or "Not answered yet"))
        self.answer_count_var.set(f"{sum(bool(v.strip()) for v in configured.values())} profile answers • {len(self.config_data.answers)} custom answers")

    def _refresh_question_library(self) -> None:
        self._question_search_after_id = None
        if not hasattr(self, "question_tree"):
            return
        selected_key = self._editing_question_key
        query = normalize_question(self.question_search_var.get())
        category = self.question_category_var.get()
        scope = self.question_scope_var.get()
        configured = dict(self.config_data.profile_answers)
        configured.update(self._question_drafts)
        self._loading_question = True
        try:
            children = self.question_tree.get_children()
            if children:
                self.question_tree.delete(*children)
            for definition in QUESTION_CATALOG:
                if category != "All categories" and definition.category != category:
                    continue
                if query and query not in normalize_question(f"{definition.label} {definition.category} {definition.key} {definition.help_text}"):
                    continue
                if scope == "Dublin essentials" and not definition.dublin_recommended and not configured.get(definition.key):
                    continue
                if scope == "Answered" and not configured.get(definition.key, "").strip():
                    continue
                if scope == "Diversity and inclusion" and not definition.social:
                    continue
                answer = configured.get(definition.key, "")
                self.question_tree.insert("", "end", iid=definition.key, values=(definition.category, definition.label, answer or "Not answered yet"))
            if selected_key and self.question_tree.exists(selected_key):
                self.question_tree.selection_set(selected_key)
            else:
                self._editing_question_key = None
                self.question_editor_value_var.set("")
                self.question_editor_title_var.set("Select a question")
                self.question_editor_help_var.set("Choose from the list. Your answers are saved automatically.")
                self.question_editor_meta_var.set("")
                self.question_editor_widget.configure(state="disabled")
                self.question_save_button.configure(state="disabled")
                self.question_clear_button.configure(state="disabled")
            count = len(self.question_tree.get_children())
            self.question_results_var.set(f"{count} questions • select one to answer" if count else "No questions found. Try another search or category.")
            self._update_question_rows()
        finally:
            self._loading_question = False

    def _rebuild_question_editor_widget(self, choices: list[str]) -> None:
        if not hasattr(self, "question_editor_host"):
            return
        if self.question_editor_widget is not None:
            try:
                self.question_editor_widget.destroy()
            except Exception:
                pass
        if choices:
            widget = ttk.Combobox(
                self.question_editor_host,
                textvariable=self.question_editor_value_var,
                values=choices,
                state="normal",
            )
        else:
            widget = ttk.Entry(self.question_editor_host, textvariable=self.question_editor_value_var)
        widget.grid(row=0, column=0, sticky="ew")
        self.question_editor_widget = widget

    def _load_question_editor(self) -> None:
        if self._loading_question:
            return
        selected = self.question_tree.selection()
        if not selected:
            return
        definition = QUESTION_BY_KEY.get(selected[0])
        if not definition:
            return
        self._loading_question = True
        try:
            changed = self._editing_question_key != definition.key
            self._editing_question_key = definition.key
            self.question_editor_title_var.set(definition.label)
            self.question_editor_meta_var.set(definition.category + (" • Optional personal information" if definition.social else ""))
            self.question_editor_help_var.set(definition.help_text or "Only enter information that applies to you. Leave this blank if you prefer to answer later.")
            self.question_editor_value_var.set(self._question_drafts.get(definition.key, self.config_data.profile_answers.get(definition.key, "")))
            if changed:
                self._rebuild_question_editor_widget(list(definition.choices))
            self.question_editor_note_var.set(
                "We never guess personal information. You choose what to share." if definition.social else
                "A custom answer for the same question takes priority over your profile. LinkedIn choices are still checked."
            )
            state = "disabled" if self._settings_locked() else "normal"
            self.question_editor_widget.configure(state=state)
            self.question_save_button.configure(state=state)
            self.question_clear_button.configure(state=state)
            self.questions_page.install_bindings(self.question_editor_host)
        finally:
            self._loading_question = False

    def _focus_question_editor(self) -> None:
        self._load_question_editor()
        if self.question_editor_widget is not None:
            try:
                self.question_editor_widget.focus_set()
            except Exception:
                pass

    def _save_question_editor(self) -> None:
        if self._settings_locked() or not self._editing_question_key:
            return
        self._question_edited()
        self._save_from_ui(show_message=True)

    def _configure_catalog_answer(self) -> None:
        if not self.question_tree.selection():
            messagebox.showinfo("Question library", "Select a question first.", parent=self)
            return
        self._focus_question_editor()

    def _clear_catalog_answer(self) -> None:
        if self._settings_locked() or not self._editing_question_key:
            return
        self.question_editor_value_var.set("")

    def _show_question_help(self) -> None:
        self._load_question_editor()

    def _start_login_setup(self) -> None:
        if self.login_worker and self.login_worker.is_alive():
            messagebox.showinfo("Login", "A LinkedIn login window is already open.", parent=self)
            return
        if not self._save_from_ui(show_message=False):
            return
        self.login_status_var.set("Opening Chrome…")
        self.login_worker = threading.Thread(target=self._login_setup_worker, daemon=True)
        self.login_worker.start()

    def _login_setup_worker(self) -> None:
        driver = None
        try:
            driver = build_chrome_driver(self.config_data.chrome_profile_dir, headless=False)
            driver.get("https://www.linkedin.com/feed/")
            self.ui_queue.put(("login_status", "Complete sign-in in Chrome…"))
            while True:
                try:
                    url = (driver.current_url or "").lower()
                    login_fields = deep_query_all(driver, "input#username, input#password")
                    logged_in_path = any(path in url for path in ("/feed", "/jobs", "/mynetwork", "/in/"))
                    if "linkedin.com" in url and logged_in_path and "/login" not in url and "/checkpoint/" not in url and not login_fields:
                        self.ui_queue.put(("login_status", "Session saved — ready"))
                        time.sleep(1)
                        return
                except Exception:
                    return
                time.sleep(1)
        except Exception as exc:
            self.ui_queue.put(("login_status", "Chrome could not open. Close other search windows and try again."))
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

    def _start_run(self) -> None:
        if self._settings_locked():
            return
        if not self._save_from_ui(show_message=False):
            self.notebook.select(self.setup_tab)
            return
        if not self._confirm_aggressive_delay():
            self.notebook.select(self.setup_tab)
            return
        if self.login_worker and self.login_worker.is_alive():
            messagebox.showwarning("Login window open", "Finish the LinkedIn login setup before starting the automation.", parent=self)
            return
        self.stop_event.clear()
        self._mark_run_activity()
        self.failsafe_count = 0
        self.failsafe_suspended = False
        self.failsafe_dialog_open = False
        self.current_stats = RunStats()
        self._update_stats(self.current_stats, None)
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status_var.set("Getting ready. Preparing your search…")
        self._last_friendly_log = ""
        self._run_config = deepcopy(self.config_data)
        self._run_active = True
        self._set_settings_locked(True)
        self.worker = threading.Thread(target=self._run_worker, daemon=True)
        try:
            self.worker.start()
        except Exception:
            self._run_active = False
            self._set_settings_locked(False)
            self.start_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
            self.status_var.set("The search could not start. Please try again.")
            logging.getLogger(__name__).exception("Could not start run worker")

    def _run_worker(self) -> None:
        bot = None
        try:
            bot = EasyApplyBot(
                self._run_config,
                on_status=lambda m: self.ui_queue.put(("status", m)),
                on_progress=lambda s, j: self.ui_queue.put(("progress", deepcopy(s), j)),
                ask_question=self._ask_question_threadsafe,
                confirm_submit=self._confirm_submit_threadsafe,
                should_stop=self.stop_event.is_set,
                persist_answers=False,
            )
            self.current_bot = bot
            stats = bot.run()
            self.ui_queue.put(("done", stats))
        except Exception as exc:
            logging.getLogger(__name__).exception("Run failed")
            self.ui_queue.put(("error", str(exc)))
        finally:
            if self.current_bot is bot:
                self.current_bot = None

    def _finish_run(self) -> None:
        if self.worker and self.worker.is_alive():
            self.after(50, self._finish_run)
            return
        self._run_active = False
        if hasattr(self, "_run_config"):
            self.config_data.answers.update(self._run_config.answers)
            self.config_data.answer_labels.update(self._run_config.answer_labels)
            self.config_data.answer_signatures.update(self._run_config.answer_signatures)
        self._set_settings_locked(False)
        self._settings_dirty = True
        self._save_from_ui(show_message=False)
        self._refresh_answers_tree()
        self._refresh_applied(force=True)
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        if self.restart_after_stop:
            self.after(100, self._start_run_when_idle)

    def _stop_run(self) -> None:
        self.stop_event.set()
        self.status_var.set("Stopping after the current browser action…")
        self.stop_button.configure(state="disabled")

    def _ask_question_threadsafe(self, question: str, choices: list[str], default: str) -> str | None:
        # Resolver should only call this in supervised mode. The guard makes this
        # callback safe even if an external/custom bot call reaches it unexpectedly.
        if self.config_data.run_mode == "automatic":
            return self.config_data.default_text_answer
        request = QuestionRequest(question=question, choices=choices, default=default, done=threading.Event())
        self.ui_queue.put(("question", request))
        while not request.done.wait(0.25):
            if self.stop_event.is_set():
                return None
        return request.answer

    def _confirm_submit_threadsafe(self, job: JobInfo) -> bool:
        request = ConfirmRequest(job=job, done=threading.Event())
        self.ui_queue.put(("confirm", request))
        while not request.done.wait(0.25):
            if self.stop_event.is_set():
                return False
        return request.approved

    def _maximize_for_question(self) -> None:
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except Exception:
            pass
        try:
            self.state("zoomed")
            return
        except Exception:
            pass
        try:
            self.attributes("-zoomed", True)
        except Exception:
            try:
                self.geometry(f"{self.winfo_screenwidth()}x{self.winfo_screenheight()}+0+0")
            except Exception:
                pass

    def _process_ui_queue(self) -> None:
        try:
            for _ in range(100):
                item = self.ui_queue.get_nowait()
                kind = item[0]
                try:
                    if kind == "log":
                        self._mark_run_activity()
                        self._append_log(item[1])
                    elif kind == "status":
                        self._mark_run_activity()
                        message = friendly_run_message(item[1])
                        if message:
                            self.status_var.set(message)
                    elif kind == "history":
                        self._history_loading = False
                        self._history_rows = item[1]
                        self._history_signature = item[2]
                        self._render_history()
                    elif kind == "history_error":
                        self._history_loading = False
                        self.history_status_var.set("Your history could not be opened. Check its folder and choose Refresh.")
                    elif kind == "login_status":
                        self.login_status_var.set(item[1])
                    elif kind == "progress":
                        self._mark_run_activity()
                        self._update_stats(item[1], item[2])
                    elif kind == "question":
                        request: QuestionRequest = item[1]
                        try:
                            self.failsafe_suspended = True
                            self._maximize_for_question()
                            self.notebook.select(self.run_tab)
                            self.status_var.set("Paused — answer required in the desktop app")
                            dialog = ChoiceDialog(self, request.question, request.choices, request.default)
                            request.answer = dialog.result
                            if dialog.result:
                                self._run_config.remember_answer(request.question, dialog.result)
                        except Exception as exc:
                            logging.getLogger(__name__).exception("Question dialog failed")
                            request.answer = None
                            self.status_var.set("We could not open the question. This application will be skipped.")
                        finally:
                            self._mark_run_activity()
                            self.failsafe_suspended = False
                            request.done.set()
                    elif kind == "confirm":
                        request: ConfirmRequest = item[1]
                        try:
                            self.failsafe_suspended = True
                            request.approved = messagebox.askyesno(
                                "Send application?",
                                f"Send this application now?\n\n{request.job.title}\n{request.job.company}",
                                parent=self,
                            )
                        finally:
                            self._mark_run_activity()
                            self.failsafe_suspended = False
                            request.done.set()
                    elif kind == "done":
                        stats: RunStats = item[1]
                        self._update_stats(stats, None)
                        self.status_var.set("Search stopped. Your history is in Applied." if self.stop_event.is_set() else "Search complete. View your applications in Applied.")
                        self._finish_run()
                    elif kind == "error":
                        self.status_var.set("The search stopped. Your earlier applications are still in your history.")
                        self._append_log("ERROR Run failed")
                        self._finish_run()
                except Exception:
                    # UI event failures should never tear down Tk's event loop.
                    logging.getLogger(__name__).exception("UI queue event failed: %s", kind)
        except queue.Empty:
            pass
        finally:
            self.after(100, self._process_ui_queue)

    def _update_stats(self, stats: RunStats, job: JobInfo | None) -> None:
        self.current_stats = stats
        for name, value in stats.as_dict().items():
            if name in self.stat_vars:
                self.stat_vars[name].set(str(value))
        if stats.attempted > 0:
            rate = (100.0 * stats.applied / stats.attempted)
            self.coverage_var.set(
                f"{stats.applied} of {stats.attempted} started applications were sent ({rate:.0f}%)."
            )
        else:
            self.coverage_var.set("Sent applications will appear here and in Applied.")
        limit = int(getattr(self.config_data, "max_applications", 0) or 0)
        if limit > 0:
            self.progress.configure(maximum=max(1, limit))
            self.progress["value"] = min(stats.applied, limit)
        else:
            self.progress.configure(maximum=max(1, stats.attempted))
            self.progress["value"] = min(stats.applied, max(1, stats.attempted))
        if job:
            self.current_job_var.set(f"Current job: {job.title or 'Untitled job'} • {job.company}")
        else:
            self.current_job_var.set("")

    def _append_log(self, line: str) -> None:
        try:
            self.recent_logs.append(str(line))
        except Exception:
            pass
        message = friendly_run_message(line)
        if not message or message == self._last_friendly_log:
            return
        self._last_friendly_log = message
        try:
            follow = self.log_text.yview()[1] >= 0.99
            self.log_text.configure(state="normal")
            self.log_text.insert("end", datetime.now().strftime("%H:%M") + "  •  " + message + "\n")
            lines = int(self.log_text.index("end-1c").split(".")[0])
            if lines > 400:
                self.log_text.delete("1.0", f"{lines - 400}.0")
            if follow:
                self.log_text.see("end")
        finally:
            self.log_text.configure(state="disabled")

    def _refresh_answers_tree(self) -> None:
        if not hasattr(self, "answers_tree"):
            return
        for item in self.answers_tree.get_children():
            self.answers_tree.delete(item)
        for key, answer in sorted(self.config_data.answers.items()):
            display = self.config_data.answer_labels.get(key, key)
            try:
                self.answers_tree.insert("", "end", iid=key, values=(display, answer))
            except tk.TclError:
                self.answers_tree.insert("", "end", values=(display, answer))
        if hasattr(self, "answer_count_var"):
            self.answer_count_var.set(f"{len(self.config_data.profile_answers)} profile answers • {len(self.config_data.answers)} custom answers")

    def _add_answer(self) -> None:
        if self._settings_locked():
            return
        dialog = CustomAnswerDialog(self)
        if not dialog.result:
            return
        question, answer = dialog.result
        self.config_data.remember_answer(question, answer)
        self._schedule_autosave()
        self._refresh_answers_tree()
        self._refresh_question_library()
        self.status_var.set("Answer ready for your next applications.") if hasattr(self, "status_var") else None

    def _selected_learned_key(self) -> str | None:
        selected = self.answers_tree.selection() if hasattr(self, "answers_tree") else ()
        if not selected:
            return None
        item_id = selected[0]
        if item_id in self.config_data.answers:
            return item_id
        values = self.answers_tree.item(item_id, "values")
        if not values:
            return None
        return normalize_question(str(values[0]))

    def _edit_answer(self) -> None:
        if self._settings_locked():
            return
        key = self._selected_learned_key()
        if not key:
            return
        display = self.config_data.answer_labels.get(key, key)
        old = self.config_data.answers.get(key, "")
        dialog = CustomAnswerDialog(self, question=display, answer=old)
        if not dialog.result:
            return
        question, answer = dialog.result
        # If the user edited the question wording, remove the old canonical key.
        self.config_data.answers.pop(key, None)
        self.config_data.answer_labels.pop(key, None)
        self.config_data.remember_answer(question, answer)
        self._schedule_autosave()
        self._refresh_answers_tree()
        self._refresh_question_library()

    def _delete_answer(self) -> None:
        if self._settings_locked():
            return
        key = self._selected_learned_key()
        if not key:
            return
        self.config_data.answers.pop(key, None)
        self.config_data.answer_labels.pop(key, None)
        self._schedule_autosave()
        self._refresh_answers_tree()
        self._refresh_question_library()

    def _hide_run_disclaimer(self) -> None:
        if self._settings_locked():
            return
        self.config_data.show_run_disclaimer = False
        try:
            self.config_data.save()
        except Exception:
            logging.getLogger(__name__).exception("Could not persist disclaimer preference")
        try:
            self.disclaimer_frame.grid_remove()
        except Exception:
            pass

    def _open_portable_files_folder(self) -> None:
        import os
        import subprocess
        import sys
        folder = executable_dir().resolve()
        try:
            if sys.platform.startswith("win"):
                os.startfile(folder)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as exc:
            messagebox.showinfo(
                "autojobs files",
                f"The files are located here:\n{folder}\n\n"
                "Look for prompt.txt and answer-profile-template.json in this folder.\n\n"
                f"The folder could not be opened automatically: {exc}",
                parent=self,
            )

    def _export_answer_profile(self) -> None:
        if not self._save_from_ui(show_message=False):
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Export answer profile",
            defaultextension=".json",
            initialfile="answer-profile-template.json",
            filetypes=[("JSON", "*.json")],
        )
        if not path:
            return
        try:
            exported = self.config_data.export_answer_profile(Path(path))
            messagebox.showinfo(
                "Answer profile exported",
                f"Saved to:\n{exported}\n\nThe JSON includes the complete question catalog, including unanswered questions as empty strings. "
                "Browser/session and application history are excluded. The file may contain sensitive/social answers you explicitly configured, so store it appropriately.",
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc), parent=self)

    def _import_answer_profile(self) -> None:
        if self._settings_locked() or not self._save_from_ui(show_message=True):
            return
        path = filedialog.askopenfilename(
            parent=self,
            title="Import AI answers / answer profile",
            initialfile="import_me_on_autojobs.json",
            filetypes=[("autojobs answer file", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        dialog = ImportModeDialog(self)
        if dialog.result is None:
            return
        try:
            imported = deepcopy(self.config_data)
            summary = imported.import_answer_profile(Path(path), replace=dialog.result == "replace")
            self.config_data = imported
            self._question_drafts.clear()
            self._load_config_into_ui()
            self.save_status_var.set("Answers imported and saved on this computer")
            messagebox.showinfo(
                "Answer profile imported",
                "Import complete.\n\n"
                f"Configured answers: {summary['profile_answers']}\n"
                f"Learned answers: {summary['learned_answers']}\n"
                f"Fallback settings: {'imported' if summary['defaults_imported'] else 'unchanged'}\n"
                f"Mode: {summary['mode']}",
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror("Import failed", str(exc), parent=self)

    def _browse_file(self, variable: tk.StringVar, filetypes) -> None:
        path = filedialog.askopenfilename(parent=self, filetypes=filetypes)
        if path:
            variable.set(path)

    def _open_log_file(self) -> None:
        import os
        import subprocess
        import sys
        path = log_file_path().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("autojobs persistent log\n", encoding="utf-8")
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception:
            try:
                if sys.platform.startswith("win"):
                    os.startfile(path.parent)  # type: ignore[attr-defined]
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(path.parent)])
                else:
                    subprocess.Popen(["xdg-open", str(path.parent)])
            except Exception as exc:
                messagebox.showerror("Open log", f"Log file:\n{path}\n\n{exc}", parent=self)

    def _open_results_folder(self) -> None:
        import os
        import subprocess
        import sys

        path = Path(self.config_data.output_csv).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform.startswith("win"):
                os.startfile(path.parent)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path.parent)])
            else:
                subprocess.Popen(["xdg-open", str(path.parent)])
        except Exception as exc:
            messagebox.showerror("Open folder", str(exc), parent=self)

    @staticmethod
    def _set_text(widget: tk.Text, lines: list[str]) -> None:
        widget.delete("1.0", "end")
        widget.insert("1.0", "\n".join(lines))

    @staticmethod
    def _get_lines(widget: tk.Text) -> list[str]:
        return [line.strip() for line in widget.get("1.0", "end").splitlines() if line.strip()]

    def _on_close(self) -> None:
        self.ai_balloon.hide()
        if self._settings_locked():
            if not messagebox.askyesno("End search", "Stop the search and close? We will wait for the current action so your answers can be saved.", parent=self):
                return
            self._stop_run()
            self.after(100, self._close_when_idle)
            return
        self._close_when_idle()

    def _close_when_idle(self) -> None:
        if self._settings_locked():
            self.after(100, self._close_when_idle)
            return
        if self._settings_dirty and not self._save_from_ui(show_message=False):
            messagebox.showwarning("Some changes are not saved", self.save_status_var.get() + "\nPlease correct the highlighted field before closing.", parent=self)
            return
        for callback in (self._autosave_after_id, self._responsive_after_id, self._question_search_after_id, self._history_search_after_id):
            if callback is not None:
                self.after_cancel(callback)
        self.destroy()


def main() -> None:
    app = EasyApplyApp()
    app.mainloop()


if __name__ == "__main__":
    main()
