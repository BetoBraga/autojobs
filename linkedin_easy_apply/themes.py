from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_THEME_FILE = "themes.json"

# These defaults are also written to themes.json on first launch when that file
# is missing. Once the external file exists, users are free to add, edit or
# remove themes without rebuilding autojobs.
DEFAULT_THEMES: dict[str, Any] = {
    "version": 1,
    "default_theme": "Cadente",
    "themes": {
        "Cadente": {
            "background": "#F5F6F7",
            "surface": "#FFFFFF",
            "surface_alt": "#E9EEEE",
            "text": "#20292D",
            "muted": "#56646A",
            "primary": "#146B64",
            "primary_hover": "#0C514C",
            "border": "#C6D0D2",
            "input_bg": "#FFFFFF",
            "input_fg": "#20292D",
            "selection_bg": "#D1E9E4",
            "selection_fg": "#173B36",
            "danger": "#AF3446",
            "accent": "#9B542C"
        },
        "Ocean": {
            "background": "#F4F8FC",
            "surface": "#FFFFFF",
            "surface_alt": "#EAF2FA",
            "text": "#142033",
            "muted": "#617086",
            "primary": "#1769AA",
            "primary_hover": "#0F568E",
            "border": "#CBD9E8",
            "input_bg": "#FFFFFF",
            "input_fg": "#142033",
            "selection_bg": "#CFE7FA",
            "selection_fg": "#0B2540",
            "danger": "#B42318"
        },
        "Emerald": {
            "background": "#F2F8F5",
            "surface": "#FFFFFF",
            "surface_alt": "#E4F1EA",
            "text": "#163128",
            "muted": "#5D746B",
            "primary": "#157A55",
            "primary_hover": "#0E6244",
            "border": "#C5DCCF",
            "input_bg": "#FFFFFF",
            "input_fg": "#163128",
            "selection_bg": "#CBE9DA",
            "selection_fg": "#123C2D",
            "danger": "#B42318"
        },
        "Sunset": {
            "background": "#FFF7F0",
            "surface": "#FFFFFF",
            "surface_alt": "#FDEBDD",
            "text": "#3A251B",
            "muted": "#80675B",
            "primary": "#D45B22",
            "primary_hover": "#B94716",
            "border": "#E8D2C3",
            "input_bg": "#FFFFFF",
            "input_fg": "#3A251B",
            "selection_bg": "#FFD9C2",
            "selection_fg": "#54220F",
            "danger": "#B42318"
        },
        "Midnight": {
            "background": "#111827",
            "surface": "#182235",
            "surface_alt": "#22304A",
            "text": "#F2F6FC",
            "muted": "#A8B5C7",
            "primary": "#65A8FF",
            "primary_hover": "#83B9FF",
            "border": "#34445E",
            "input_bg": "#0F1724",
            "input_fg": "#F2F6FC",
            "selection_bg": "#315B89",
            "selection_fg": "#FFFFFF",
            "danger": "#FF7B72"
        },
        "Lavender": {
            "background": "#F8F5FC",
            "surface": "#FFFFFF",
            "surface_alt": "#EEE7F7",
            "text": "#2C2340",
            "muted": "#746986",
            "primary": "#7651B5",
            "primary_hover": "#62409D",
            "border": "#D8CEE7",
            "input_bg": "#FFFFFF",
            "input_fg": "#2C2340",
            "selection_bg": "#DDCEF2",
            "selection_fg": "#352052",
            "danger": "#B42318"
        },
        "Ctrl+Alt+Hired": {
            "background": "#EEF7FF",
            "surface": "#FFFFFF",
            "surface_alt": "#DDEEFF",
            "text": "#10243E",
            "muted": "#5C708A",
            "primary": "#0067C0",
            "primary_hover": "#00539B",
            "border": "#BCD6EE",
            "input_bg": "#FFFFFF",
            "input_fg": "#10243E",
            "selection_bg": "#B9DDFF",
            "selection_fg": "#07345E",
            "danger": "#B42318"
        },
        "Recruiter Ghosted Me": {
            "background": "#F7F7FB",
            "surface": "#FFFFFF",
            "surface_alt": "#EEEEF5",
            "text": "#29283A",
            "muted": "#77758A",
            "primary": "#7C6DAF",
            "primary_hover": "#665995",
            "border": "#D7D4E3",
            "input_bg": "#FFFFFF",
            "input_fg": "#29283A",
            "selection_bg": "#DED8F2",
            "selection_fg": "#392E62",
            "danger": "#B42318"
        },
        "Coffee Before Interviews": {
            "background": "#FBF6EF",
            "surface": "#FFFDFC",
            "surface_alt": "#EFE1D2",
            "text": "#3B2A20",
            "muted": "#7C685B",
            "primary": "#8B5E3C",
            "primary_hover": "#714A2E",
            "border": "#DDC9B7",
            "input_bg": "#FFFDFC",
            "input_fg": "#3B2A20",
            "selection_bg": "#E8C9AE",
            "selection_fg": "#4E2D19",
            "danger": "#B42318"
        },
        "Terminal Goblin": {
            "background": "#0D1510",
            "surface": "#142019",
            "surface_alt": "#1E2D23",
            "text": "#DDF9E5",
            "muted": "#8EB99A",
            "primary": "#4ADE80",
            "primary_hover": "#70E79A",
            "border": "#2C4935",
            "input_bg": "#0A110C",
            "input_fg": "#DDF9E5",
            "selection_bg": "#285E3B",
            "selection_fg": "#F0FFF4",
            "danger": "#FF7B72"
        },
        "Merge Conflict": {
            "background": "#FFF4F4",
            "surface": "#FFFFFF",
            "surface_alt": "#FCE1E1",
            "text": "#3B2025",
            "muted": "#806067",
            "primary": "#C43B5D",
            "primary_hover": "#A72D4B",
            "border": "#E7C4CB",
            "input_bg": "#FFFFFF",
            "input_fg": "#3B2025",
            "selection_bg": "#F7C5D1",
            "selection_fg": "#5B1830",
            "danger": "#B42318"
        }
    }
}

_REQUIRED_COLOR_KEYS = (
    "background", "surface", "surface_alt", "text", "muted", "primary",
    "primary_hover", "border", "input_bg", "input_fg", "selection_bg",
    "selection_fg", "danger", "accent",
)


def executable_dir() -> Path:
    """Return a stable directory relative to the running app/executable.

    Frozen builds resolve to the directory containing autojobs.exe. Source runs
    resolve to the project root. This never depends on the current working
    directory, so moving the EXE together with themes.json does not break paths.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def themes_file_path() -> Path:
    return executable_dir() / DEFAULT_THEME_FILE


@dataclass(frozen=True)
class ThemeLoadResult:
    themes: dict[str, dict[str, str]]
    default_theme: str
    path: Path
    warning: str = ""


def _normalise_payload(payload: Any) -> tuple[dict[str, dict[str, str]], str]:
    if not isinstance(payload, dict):
        raise ValueError("themes.json must contain a JSON object.")
    raw_themes = payload.get("themes")
    if not isinstance(raw_themes, dict) or not raw_themes:
        raise ValueError("themes.json must contain at least one theme in 'themes'.")

    builtin_fallback = DEFAULT_THEMES["themes"]["Cadente"]
    themes: dict[str, dict[str, str]] = {}
    for raw_name, raw_palette in raw_themes.items():
        name = str(raw_name).strip()
        if not name or not isinstance(raw_palette, dict):
            continue
        palette: dict[str, str] = {}
        for key in _REQUIRED_COLOR_KEYS:
            value = str(raw_palette.get(key, builtin_fallback[key])).strip()
            if not value:
                value = builtin_fallback[key]
            palette[key] = value
        themes[name] = palette
    if not themes:
        raise ValueError("No valid themes were found in themes.json.")

    requested_default = str(payload.get("default_theme", "")).strip()
    default_theme = requested_default if requested_default in themes else next(iter(themes))
    return themes, default_theme


def ensure_default_themes_file(path: Path | None = None) -> Path:
    path = Path(path or themes_file_path())
    if path.exists():
        return path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(DEFAULT_THEMES, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        # A read-only install directory should not prevent autojobs from opening;
        # built-in themes remain available for this session.
        pass
    return path


def load_themes(path: Path | None = None) -> ThemeLoadResult:
    path = Path(path or themes_file_path())
    ensure_default_themes_file(path)
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            themes, default_theme = _normalise_payload(payload)
            return ThemeLoadResult(themes=themes, default_theme=default_theme, path=path)
        except Exception as exc:
            themes, default_theme = _normalise_payload(DEFAULT_THEMES)
            return ThemeLoadResult(
                themes=themes,
                default_theme=default_theme,
                path=path,
                warning=f"Could not load themes.json; built-in themes are being used: {exc}",
            )
    themes, default_theme = _normalise_payload(DEFAULT_THEMES)
    return ThemeLoadResult(
        themes=themes,
        default_theme=default_theme,
        path=path,
        warning="themes.json could not be created in the application folder; built-in themes are being used.",
    )
