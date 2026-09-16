from __future__ import annotations

from pathlib import Path

from PIL import Image

from ui.resources import branding_path, resource_path


def test_official_branding_assets_are_local_and_loadable() -> None:
    expected = (
        "source/ism_logo_original.jpeg", "ism_logo_horizontal.png",
        "ism_logo_horizontal_transparente.png", "ism_simbolo.png",
        "ism_simbolo_transparente.png", "ism_app_icon.ico",
    )
    for relative in expected:
        assert branding_path(relative).is_file()
    assert resource_path("assets", "branding").is_dir()


def test_transparent_derivatives_preserve_aspect_ratio_and_alpha() -> None:
    horizontal = Image.open(branding_path("ism_logo_horizontal_transparente.png"))
    symbol = Image.open(branding_path("ism_simbolo_transparente.png"))
    assert horizontal.mode == "RGBA" and symbol.mode == "RGBA"
    assert horizontal.width > horizontal.height * 2
    assert symbol.width > symbol.height
    assert horizontal.getpixel((0, 0))[3] == 0
    assert symbol.getpixel((0, 0))[3] == 0


def test_windows_icon_contains_all_required_sizes() -> None:
    icon = Image.open(branding_path("ism_app_icon.ico"))
    assert icon.info["sizes"] == {(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)}


def test_pyinstaller_uses_local_branding_icon() -> None:
    spec = Path("PermeabilimetroSupervisorio.spec").read_text(encoding="utf-8")
    assert "ism_app_icon.ico" in spec
    assert "assets/branding" in spec
    assert "C:\\Users" not in spec
