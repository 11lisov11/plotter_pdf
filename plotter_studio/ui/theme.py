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
    shadow: str


LIGHT = ThemePaletteTokens(
    name="light",
    bg="#f5f7fb",
    panel="#ffffff",
    panel_soft="#f7f8fc",
    text="#0f172a",
    text_muted="#475569",
    border="#dbe2ec",
    accent="#2563eb",
    accent_hover="#1d4ed8",
    success="#059669",
    danger="#dc2626",
    input_bg="#ffffff",
    log_bg="#f8fafc",
    shadow="rgba(2, 6, 23, 0.08)",
)


DARK = ThemePaletteTokens(
    name="dark",
    bg="#16181d",
    panel="#20242c",
    panel_soft="#1b1f27",
    text="#e5e7eb",
    text_muted="#94a3b8",
    border="#323846",
    accent="#3b82f6",
    accent_hover="#2563eb",
    success="#10b981",
    danger="#ef4444",
    input_bg="#111827",
    log_bg="#0f131a",
    shadow="rgba(0, 0, 0, 0.25)",
)


def _lightness(color_hex: str) -> float:
    color = QColor(color_hex)
    return color.lightnessF()


def detect_system_dark(app: QApplication) -> bool:
    palette = app.palette()
    window = palette.color(QPalette.Window)
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
    disabled_text = "#6b7280" if is_dark else "#9aa4b2"
    menu_hover = p.accent
    return f"""
QWidget {{
    color: {p.text};
    background: {p.bg};
    font-family: "Segoe UI", "SF Pro Display", "Inter";
    font-size: 14px;
}}
QMainWindow {{
    background: {p.bg};
}}
QFrame#TopBar,
QFrame#Sidebar,
QFrame#PageCard,
QFrame#LogDrawer,
QFrame#StatusCard {{
    background: {p.panel};
    border: 1px solid {p.border};
    border-radius: 16px;
}}
QFrame#PageCardTitle {{
    background: transparent;
    border: none;
}}
QLabel#TitleLabel {{
    font-size: 24px;
    font-weight: 650;
    letter-spacing: 0.2px;
}}
QLabel#SubtitleLabel {{
    color: {p.text_muted};
    font-size: 12px;
}}
QLabel#SectionTitle {{
    font-size: 18px;
    font-weight: 600;
}}
QLabel#FieldLabel {{
    color: {p.text_muted};
    font-size: 12px;
}}
QLabel#HintLabel {{
    color: {p.text_muted};
    font-size: 13px;
}}
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{
    background: {p.input_bg};
    border: 1px solid {p.border};
    border-radius: 10px;
    padding: 8px 10px;
    min-height: 18px;
}}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {p.accent};
}}
QPushButton {{
    background: {p.panel_soft};
    border: 1px solid {p.border};
    border-radius: 10px;
    padding: 8px 14px;
}}
QPushButton:hover {{
    background: {p.input_bg};
}}
QPushButton:disabled {{
    color: {disabled_text};
}}
QPushButton#PrimaryButton {{
    background: {p.accent};
    border: 1px solid {p.accent};
    color: #ffffff;
    font-weight: 600;
}}
QPushButton#PrimaryButton:hover {{
    background: {p.accent_hover};
}}
QPushButton#DangerButton {{
    background: {p.danger};
    border: 1px solid {p.danger};
    color: #ffffff;
    font-weight: 600;
}}
QPushButton#DangerButton:hover {{
    background: #b91c1c;
}}
QPushButton#SuccessButton {{
    background: {p.success};
    border: 1px solid {p.success};
    color: #ffffff;
    font-weight: 600;
}}
QPushButton#SuccessButton:hover {{
    background: #047857;
}}
QToolButton#SidebarButton {{
    text-align: left;
    border: 1px solid transparent;
    border-radius: 12px;
    padding: 10px 12px;
    color: {p.text_muted};
    background: transparent;
}}
QToolButton#SidebarButton:hover {{
    background: {p.panel_soft};
    color: {p.text};
}}
QToolButton#SidebarButton:checked {{
    background: {p.input_bg};
    border: 1px solid {p.border};
    color: {p.text};
    font-weight: 600;
}}
QToolButton#SidebarButton:disabled {{
    color: {disabled_text};
}}
QCheckBox {{
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 6px;
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
QPlainTextEdit, QTextEdit {{
    background: {p.log_bg};
    border: 1px solid {p.border};
    border-radius: 10px;
    font-family: "Consolas", "JetBrains Mono", monospace;
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
    background: {menu_hover};
    color: #ffffff;
}}
"""
