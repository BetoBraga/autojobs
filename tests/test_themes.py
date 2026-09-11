import json
from pathlib import Path

from linkedin_easy_apply.themes import DEFAULT_THEMES, executable_dir, load_themes


def test_default_themes_have_distinct_primary_colors():
    themes = DEFAULT_THEMES["themes"]
    assert "Cadente" in themes
    assert len(themes) == 11
    assert len({palette["primary"] for palette in themes.values()}) == 11


def test_cadente_is_default_and_external_palette_matches(tmp_path):
    from linkedin_easy_apply.config import AppConfig

    result = load_themes(tmp_path / "themes.json")
    shipped = load_themes(Path(__file__).resolve().parents[1] / "themes.json")
    assert result.default_theme == shipped.default_theme == AppConfig().theme_name == "Cadente"
    assert result.themes["Cadente"] == shipped.themes["Cadente"]
    assert AppConfig(theme_name="Ocean").normalized().theme_name == "Ocean"


def test_cadente_text_contrast():
    def luminance(color):
        channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
        return sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722)))

    palette = DEFAULT_THEMES["themes"]["Cadente"]
    for foreground, background in (("text", "background"), ("muted", "background"), ("surface", "primary"), ("selection_fg", "selection_bg")):
        light, dark = sorted((luminance(palette[foreground]), luminance(palette[background])), reverse=True)
        assert (light + 0.05) / (dark + 0.05) >= 4.5


def test_external_themes_can_be_added_removed_and_edited(tmp_path):
    path = tmp_path / "themes.json"
    payload = json.loads(json.dumps(DEFAULT_THEMES))
    payload["themes"].pop("Sunset")
    payload["themes"]["Ocean"]["primary"] = "#123456"
    payload["themes"]["Custom"] = dict(payload["themes"]["Ocean"], primary="#ABCDEF")
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = load_themes(path)
    assert "Sunset" not in result.themes
    assert result.themes["Ocean"]["primary"] == "#123456"
    assert result.themes["Custom"]["primary"] == "#ABCDEF"


def test_invalid_theme_json_falls_back_without_crashing(tmp_path):
    path = tmp_path / "themes.json"
    path.write_text("{not valid json", encoding="utf-8")
    result = load_themes(path)
    assert len(result.themes) == 11
    assert result.warning


def test_frozen_theme_path_is_relative_to_executable(monkeypatch, tmp_path):
    import linkedin_easy_apply.themes as theme_module

    fake_exe = tmp_path / "some" / "moved" / "autojobs.exe"
    fake_exe.parent.mkdir(parents=True)
    monkeypatch.setattr(theme_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(theme_module.sys, "executable", str(fake_exe))
    assert executable_dir() == fake_exe.parent.resolve()
    assert theme_module.themes_file_path() == fake_exe.parent.resolve() / "themes.json"
