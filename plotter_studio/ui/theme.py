from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class ThemePaletteTokens:
    name: str
    bg: str
    panel: str
    panel_soft: str
    panel_elevated: str
    text: str
    text_muted: str
    border: str
    border_soft: str
    accent: str
    accent_hover: str
    success: str
    danger: str
    input_bg: str
    log_bg: str


LIGHT = ThemePaletteTokens(
    name="light",
    bg="#edf1f7",
    panel="#ffffff",
    panel_soft="#f7f9fd",
    panel_elevated="#ffffff",
    text="#101828",
    text_muted="#667085",
    border="#d0d7e5",
    border_soft="#e2e8f2",
    accent="#2463eb",
    accent_hover="#1d4ed8",
    success="#0f9f6e",
    danger="#dc3d3d",
    input_bg="#ffffff",
    log_bg="#f8fafd",
)


DARK = ThemePaletteTokens(
    name="dark",
    bg="#0b111b",
    panel="#111a28",
    panel_soft="#172234",
    panel_elevated="#1b2a40",
    text="#ecf2ff",
    text_muted="#9db0cc",
    border="#24354e",
    border_soft="#1e2d42",
    accent="#4f8fff",
    accent_hover="#3f7df0",
    success="#19b879",
    danger="#ef5353",
    input_bg="#0f1827",
    log_bg="#0a1320",
)


def _lightness(color_hex: str) -> float:
    return QColor(color_hex).lightnessF()


def detect_system_dark(app: QApplication) -> bool:
    window = app.palette().color(QPalette.Window)
    return window.lightnessF() < 0.5


def resolve_palette(mode: str, app: QApplication) -> ThemePaletteTokens:
    mode_l = (mode or "auto").strip().lower()
    if mode_l == "light":
        return LIGHT
    if mode_l == "dark":
        return DARK
    return DARK if detect_system_dark(app) else LIGHT


def build_stylesheet(p: ThemePaletteTokens) -> str:
    is_dark = _lightness(p.bg) < 0.5
    disabled_text = "#6e7f97" if is_dark else "#98a2b3"

    return f"""
QWidget {{
    color: {p.text};
    font-family: "Segoe UI Variable", "Segoe UI", "Inter";
    font-size: 14px;
}}
QMainWindow,
QWidget#AppRoot,
QWidget#ContentRoot {{
    background-color: {p.bg};
}}
QScrollArea,
QScrollArea > QWidget > QWidget {{
    background-color: transparent;
    border: none;
}}
QLabel,
QLabel#TitleLabel,
QLabel#SubtitleLabel,
QLabel#SectionTitle,
QLabel#FieldLabel,
QLabel#HintLabel {{
    background-color: transparent;
    border: none;
}}
QFrame#TopBar,
QFrame#LogDrawer,
QFrame#StatusCard,
QFrame#PageCard,
QWidget#StatusPill {{
    background-color: {p.panel};
    border: 1px solid {p.border};
    border-radius: 16px;
}}
QFrame#PageSubCard {{
    background-color: {p.panel_soft};
    border: 1px solid {p.border_soft};
    border-radius: 12px;
}}
QLabel#TitleLabel {{
    font-size: 26px;
    font-weight: 650;
    letter-spacing: 0.2px;
}}
QLabel#SubtitleLabel {{
    color: {p.text_muted};
    font-size: 13px;
}}
QLabel#SectionTitle {{
    font-size: 22px;
    font-weight: 620;
}}
QLabel#FieldLabel {{
    color: {p.text_muted};
    font-size: 13px;
    font-weight: 560;
}}
QLabel#HintLabel {{
    color: {p.text_muted};
    font-size: 14px;
}}
QComboBox,
QLineEdit,
QSpinBox,
QDoubleSpinBox {{
    background-color: {p.input_bg};
    border: 1px solid {p.border};
    border-radius: 10px;
    padding: 9px 10px;
    min-height: 22px;
}}
QComboBox:focus,
QLineEdit:focus,
QSpinBox:focus,
QDoubleSpinBox:focus {{
    border: 1px solid {p.accent};
}}
QPushButton {{
    background-color: {p.panel_soft};
    border: 1px solid {p.border};
    border-radius: 10px;
    padding: 10px 14px;
    min-height: 24px;
    font-weight: 560;
}}
QPushButton:hover {{
    background-color: {p.panel_elevated};
}}
QPushButton:disabled {{
    color: {disabled_text};
}}
QPushButton#GhostButton {{
    background-color: transparent;
    border: 1px solid {p.border_soft};
}}
QPushButton#GhostButton:hover {{
    background-color: {p.panel_soft};
}}
QPushButton#PrimaryButton {{
    background-color: {p.accent};
    border: 1px solid {p.accent};
    color: #ffffff;
    font-weight: 620;
}}
QPushButton#PrimaryButton:hover {{
    background-color: {p.accent_hover};
}}
QPushButton#DangerButton {{
    background-color: {p.danger};
    border: 1px solid {p.danger};
    color: #ffffff;
    font-weight: 620;
}}
QPushButton#DangerButton:hover {{
    background-color: #b42323;
}}
QPushButton#SuccessButton {{
    background-color: {p.success};
    border: 1px solid {p.success};
    color: #ffffff;
    font-weight: 620;
}}
QPushButton#SuccessButton:hover {{
    background-color: #0d8e61;
}}
QPushButton#ToggleButton {{
    border: 1px solid {p.border_soft};
    background-color: transparent;
    padding: 7px 10px;
    border-radius: 8px;
    color: {p.text_muted};
}}
QPushButton#ToggleButton:checked {{
    background-color: {p.panel_soft};
    color: {p.text};
}}
QWidget#SegmentedControl {{
    background-color: {p.panel_soft};
    border: 1px solid {p.border_soft};
    border-radius: 11px;
}}
QWidget#SegmentedControl QPushButton#SegmentButton {{
    border: 1px solid transparent;
    border-radius: 9px;
    padding: 7px 14px;
    background-color: transparent;
}}
QWidget#SegmentedControl QPushButton#SegmentButton:checked {{
    background-color: {p.accent};
    border: 1px solid {p.accent};
    color: #ffffff;
    font-weight: 620;
}}
QCheckBox {{
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 1px solid {p.border};
    background-color: {p.input_bg};
}}
QCheckBox::indicator:checked {{
    background-color: {p.accent};
    border: 1px solid {p.accent};
}}
QProgressBar {{
    border: 1px solid {p.border_soft};
    border-radius: 8px;
    text-align: center;
    background-color: {p.input_bg};
    min-height: 14px;
}}
QProgressBar::chunk {{
    border-radius: 7px;
    background-color: {p.accent};
}}
QPlainTextEdit,
QTextEdit {{
    background-color: {p.log_bg};
    border: 1px solid {p.border};
    border-radius: 11px;
    font-family: "JetBrains Mono", "Consolas", monospace;
    font-size: 12px;
}}
QScrollBar:vertical {{
    background-color: transparent;
    width: 12px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background-color: {p.border};
    min-height: 24px;
    border-radius: 6px;
}}
QMenu {{
    background-color: {p.panel};
    border: 1px solid {p.border};
}}
QMenu::item:selected {{
    background-color: {p.accent};
    color: #ffffff;
}}
"""
