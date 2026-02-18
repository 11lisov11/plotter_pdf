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
    text: str
    text_muted: str
    border: str
    accent: str
    accent_hover: str
    success: str
    danger: str
    input_bg: str
    log_bg: str


LIGHT = ThemePaletteTokens(
    name="light",
    bg="#f3f5f8",
    panel="#ffffff",
    panel_soft="#f8fafd",
    text="#101828",
    text_muted="#667085",
    border="#d9dee7",
    accent="#2463eb",
    accent_hover="#1d4ed8",
    success="#0f9f6e",
    danger="#dc3d3d",
    input_bg="#ffffff",
    log_bg="#f8fafd",
)


DARK = ThemePaletteTokens(
    name="dark",
    bg="#11151c",
    panel="#1b222d",
    panel_soft="#232c3a",
    text="#e6ebf3",
    text_muted="#9ca9bb",
    border="#334055",
    accent="#4b8dff",
    accent_hover="#3f7df0",
    success="#19b879",
    danger="#ef5353",
    input_bg="#121923",
    log_bg="#0f151f",
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
    disabled_text = "#677489" if is_dark else "#98a2b3"

    return f"""
QWidget {{
    color: {p.text};
    background: {p.bg};
    font-family: "SF Pro Display", "Segoe UI Variable", "Segoe UI", "Inter";
    font-size: 14px;
}}
QMainWindow {{
    background: {p.bg};
}}
QScrollArea, QScrollArea > QWidget > QWidget {{
    background: transparent;
    border: none;
}}
QFrame#TopBar,
QFrame#PageCard,
QFrame#LogDrawer,
QFrame#StatusCard,
QWidget#StatusPill {{
    background: {p.panel};
    border: 1px solid {p.border};
    border-radius: 16px;
}}
QLabel#TitleLabel {{
    font-size: 26px;
    font-weight: 640;
    letter-spacing: 0.2px;
}}
QLabel#SubtitleLabel {{
    color: {p.text_muted};
    font-size: 13px;
}}
QLabel#SectionTitle {{
    font-size: 19px;
    font-weight: 620;
}}
QLabel#FieldLabel {{
    color: {p.text_muted};
    font-size: 12px;
}}
QLabel#HintLabel {{
    color: {p.text_muted};
    font-size: 13px;
}}
QComboBox,
QLineEdit,
QSpinBox,
QDoubleSpinBox {{
    background: {p.input_bg};
    border: 1px solid {p.border};
    border-radius: 10px;
    padding: 8px 10px;
    min-height: 18px;
}}
QComboBox:focus,
QLineEdit:focus,
QSpinBox:focus,
QDoubleSpinBox:focus {{
    border: 1px solid {p.accent};
}}
QPushButton {{
    background: {p.panel_soft};
    border: 1px solid {p.border};
    border-radius: 10px;
    padding: 8px 14px;
    min-height: 20px;
}}
QPushButton:hover {{
    background: {p.input_bg};
}}
QPushButton:disabled {{
    color: {disabled_text};
}}
QPushButton#GhostButton {{
    background: transparent;
}}
QPushButton#PrimaryButton {{
    background: {p.accent};
    border: 1px solid {p.accent};
    color: #ffffff;
    font-weight: 620;
}}
QPushButton#PrimaryButton:hover {{
    background: {p.accent_hover};
}}
QPushButton#DangerButton {{
    background: {p.danger};
    border: 1px solid {p.danger};
    color: #ffffff;
    font-weight: 620;
}}
QPushButton#DangerButton:hover {{
    background: #b42323;
}}
QPushButton#SuccessButton {{
    background: {p.success};
    border: 1px solid {p.success};
    color: #ffffff;
    font-weight: 620;
}}
QPushButton#SuccessButton:hover {{
    background: #0d8e61;
}}
QWidget#SegmentedControl {{
    background: {p.panel_soft};
    border: 1px solid {p.border};
    border-radius: 12px;
}}
QWidget#SegmentedControl QPushButton#SegmentButton {{
    border: 1px solid transparent;
    border-radius: 9px;
    padding: 6px 12px;
    background: transparent;
}}
QWidget#SegmentedControl QPushButton#SegmentButton:checked {{
    background: {p.accent};
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
    background: {p.input_bg};
}}
QCheckBox::indicator:checked {{
    background: {p.accent};
    border: 1px solid {p.accent};
}}
QProgressBar {{
    border: 1px solid {p.border};
    border-radius: 8px;
    text-align: center;
    background: {p.input_bg};
    min-height: 14px;
}}
QProgressBar::chunk {{
    border-radius: 7px;
    background: {p.accent};
}}
QPlainTextEdit,
QTextEdit {{
    background: {p.log_bg};
    border: 1px solid {p.border};
    border-radius: 10px;
    font-family: "JetBrains Mono", "Consolas", monospace;
    font-size: 12px;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 12px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {p.border};
    min-height: 24px;
    border-radius: 6px;
}}
QMenu {{
    background: {p.panel};
    border: 1px solid {p.border};
}}
QMenu::item:selected {{
    background: {p.accent};
    color: #ffffff;
}}
"""
