"""Shared visual theme (colors, fonts, QSS) for the MarkAssist desktop UI.

Charcoal layer system on an RGB 58,58,58 base: four lightness steps of the
same grey carry depth (ground, resting panels, raised inputs, floating
dialogs), each with a hairline top highlight so the stack reads as layered
rather than flat. Colour is reserved for meaning only - teal for actions and
anything AI, amber for the single main call-to-action on a screen, green and
red strictly for grades/success and errors. The scanned student page keeps
its true white and is deliberately the brightest object on the desk.
"""

from PySide6.QtGui import QFont

FONT_FAMILY = "Segoe UI"

# --- Charcoal layers (base tone: RGB 58,58,58) ------------------------------
LAYER0 = "#303030"   # window ground
LAYER1 = "#3A3A3A"   # sidebars, panels, resting cards (the 58,58,58 base)
LAYER2 = "#474747"   # inputs, hover states, raised content
LAYER3 = "#545454"   # dialogs, floating work

# --- Text scale (AA contrast on every layer) --------------------------------
TEXT = "#EDEDED"
TEXT_SOFT = "#A5A5A5"
TEXT_FAINT = "#7E7E7E"

# --- Accents: colour always carries meaning ---------------------------------
ACCENT = "#0D9488"            # teal - actions, links, anything AI
ACCENT_HOVER = "#14B8A6"
ACCENT_PRESSED = "#0B7A70"
ACCENT_SOFT = "rgba(20, 184, 166, 38)"   # AI/selection tint on charcoal
ON_ACCENT = "#FFFFFF"

CTA = "#F59E0B"               # amber - the one main call-to-action
CTA_HOVER = "#FBBF24"
CTA_PRESSED = "#D97706"
ON_CTA = "#1F1400"

DESTRUCTIVE = "#DC2626"
DESTRUCTIVE_HOVER = "#EF4444"
DESTRUCTIVE_LIGHT = "rgba(220, 38, 38, 40)"
SUCCESS = "#34D399"
SUCCESS_LIGHT = "rgba(52, 211, 153, 36)"
WARNING = "#F59E0B"
WARNING_LIGHT = "rgba(245, 158, 11, 36)"

# --- Structure --------------------------------------------------------------
BORDER = "#4A4A4A"                       # hairline between charcoal layers
BORDER_LIGHT = "rgba(255, 255, 255, 18)" # inner top highlight
PRIMARY = TEXT                            # headings (legacy alias)
BACKGROUND = LAYER0
FOREGROUND = TEXT
CARD = LAYER1
MUTED = LAYER2
MUTED_FOREGROUND = TEXT_SOFT
ACCENT_LIGHT = ACCENT_SOFT

SIDEBAR_BG = LAYER1
SIDEBAR_TEXT = TEXT
SIDEBAR_TEXT_MUTED = TEXT_SOFT

# Login hero: the brand moment - deep teal, not another grey.
HERO_GRADIENT_START = "#0D9488"
HERO_GRADIENT_END = "#115E59"


def base_font() -> QFont:
    return QFont(FONT_FAMILY, 10)


def heading_font() -> QFont:
    font = QFont(FONT_FAMILY, 15)
    font.setBold(True)
    return font


STYLESHEET = f"""
QWidget {{
    background-color: {BACKGROUND};
    color: {FOREGROUND};
    font-family: "{FONT_FAMILY}";
    font-size: 13px;
}}

QLabel#HeadingLabel {{
    font-size: 18px;
    font-weight: 600;
    color: {TEXT};
    padding: 2px 0px 8px 0px;
    background: transparent;
}}

QLabel#SectionHeading {{
    font-size: 15px;
    font-weight: 700;
    color: {TEXT};
    padding-top: 4px;
    background: transparent;
}}

QLabel#FieldLabel {{
    color: {TEXT_SOFT};
    font-size: 12px;
    font-weight: 600;
    padding-top: 4px;
    background: transparent;
}}

QLabel#StatusLabel {{
    color: {TEXT_SOFT};
    font-size: 12px;
    padding: 2px 0px;
    background: transparent;
}}

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {{
    background-color: {LAYER2};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 9px 12px;
    color: {TEXT};
    font-size: 13px;
    selection-background-color: {ACCENT};
    selection-color: {ON_ACCENT};
}}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {ACCENT_HOVER};
}}

QPushButton {{
    background-color: {LAYER2};
    color: {TEXT};
    border: 1px solid {BORDER_LIGHT};
    border-top: 1px solid rgba(255, 255, 255, 26);
    border-radius: 9px;
    padding: 9px 18px;
    font-size: 13px;
    font-weight: 600;
}}

QPushButton:hover {{
    background-color: {LAYER3};
}}

QPushButton:pressed {{
    background-color: #404040;
}}

QPushButton:disabled {{
    background-color: {LAYER1};
    color: {TEXT_FAINT};
    border: 1px solid {BORDER};
}}

QPushButton#PrimaryButton {{
    background-color: {ACCENT};
    color: {ON_ACCENT};
    border: none;
    border-top: 1px solid rgba(255, 255, 255, 60);
    border-radius: 10px;
    padding: 12px 22px;
}}

QPushButton#PrimaryButton:hover {{
    background-color: {ACCENT_HOVER};
}}

QPushButton#PrimaryButton:pressed {{
    background-color: {ACCENT_PRESSED};
}}

QPushButton#PrimaryButton:disabled {{
    background-color: {LAYER2};
    color: {TEXT_FAINT};
    border: 1px solid {BORDER};
}}

QPushButton#CtaButton {{
    background-color: {CTA};
    color: {ON_CTA};
    border: none;
    border-top: 1px solid rgba(255, 255, 255, 90);
    border-radius: 10px;
    padding: 12px 22px;
    font-weight: 700;
}}

QPushButton#CtaButton:hover {{
    background-color: {CTA_HOVER};
}}

QPushButton#CtaButton:pressed {{
    background-color: {CTA_PRESSED};
}}

QPushButton#CtaButton:disabled {{
    background-color: {LAYER2};
    color: {TEXT_FAINT};
    border: 1px solid {BORDER};
}}

QPushButton#DestructiveButton {{
    background-color: {DESTRUCTIVE};
    color: {ON_ACCENT};
    border: none;
    border-radius: 10px;
    padding: 12px 22px;
}}

QPushButton#DestructiveButton:hover {{
    background-color: {DESTRUCTIVE_HOVER};
}}

QComboBox {{
    background-color: {LAYER2};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 12px;
    color: {TEXT};
    font-size: 13px;
}}

QComboBox:focus {{
    border: 1px solid {ACCENT_HOVER};
}}

QComboBox::drop-down {{
    border: none;
}}

QComboBox QAbstractItemView {{
    background-color: {LAYER3};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT};
    selection-color: {ON_ACCENT};
    outline: none;
}}

QPushButton#RowActionButton {{
    background-color: {LAYER2};
    color: {TEXT};
    border: 1px solid {BORDER_LIGHT};
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 600;
}}

QPushButton#RowActionButton:hover {{
    background-color: {LAYER3};
}}

QPushButton#RowActionButton:disabled {{
    background-color: {LAYER1};
    color: {TEXT_FAINT};
    border: 1px solid {BORDER};
}}

QGroupBox {{
    background-color: {LAYER1};
    border: 1px solid {BORDER};
    border-top: 1px solid rgba(255, 255, 255, 16);
    border-radius: 12px;
    margin-top: 14px;
    padding: 18px 16px 16px 16px;
    font-weight: 600;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 0px 6px;
    color: {TEXT};
}}

QTableWidget {{
    background-color: {LAYER1};
    alternate-background-color: #363636;
    border: 1px solid {BORDER};
    border-radius: 12px;
    gridline-color: {BORDER};
    selection-background-color: {ACCENT};
    selection-color: {ON_ACCENT};
    color: {TEXT};
}}

QHeaderView::section {{
    background-color: {LAYER2};
    color: {TEXT};
    font-weight: 600;
    padding: 10px 8px;
    border: none;
    border-bottom: 1px solid {BORDER};
}}

QTableWidget::item {{
    padding: 4px;
}}

QTableCornerButton::section {{
    background-color: {LAYER2};
    border: none;
}}

QScrollBar:vertical {{
    background: {LAYER0};
    width: 11px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: {LAYER3};
    border-radius: 5px;
    min-height: 28px;
}}

QScrollBar::handle:vertical:hover {{
    background: #616161;
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QScrollBar:horizontal {{
    background: {LAYER0};
    height: 11px;
    margin: 0;
}}

QScrollBar::handle:horizontal {{
    background: {LAYER3};
    border-radius: 5px;
    min-width: 28px;
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

QToolTip {{
    background-color: {LAYER3};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 6px 9px;
    border-radius: 6px;
}}

QCheckBox, QRadioButton {{
    background: transparent;
    color: {TEXT};
}}

QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 8px;
}}

QTabBar::tab {{
    background: {LAYER1};
    color: {TEXT_SOFT};
    padding: 7px 14px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}}

QTabBar::tab:selected {{
    background: {LAYER2};
    color: {TEXT};
}}

QProgressBar {{
    background-color: {LAYER2};
    border: 1px solid {BORDER};
    border-radius: 7px;
    color: {TEXT};
    text-align: center;
    font-size: 11px;
}}

QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 6px;
}}

/* --- App shell: sidebar, header, content --- */

QFrame#Sidebar {{
    background-color: {SIDEBAR_BG};
    border: none;
    border-right: 1px solid {BORDER};
}}

QLabel#SidebarBrand {{
    color: {TEXT};
    font-size: 16px;
    font-weight: 700;
    background: transparent;
}}

QLabel#SidebarGroupHeading {{
    color: {TEXT_FAINT};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    background: transparent;
    padding: 4px 14px 2px 14px;
}}

QPushButton#NavButton {{
    background-color: transparent;
    color: {TEXT_SOFT};
    border: none;
    border-radius: 8px;
    text-align: left;
    padding: 10px 14px;
    font-size: 13px;
    font-weight: 600;
}}

QPushButton#NavButton:hover {{
    background-color: {LAYER2};
    color: {TEXT};
    padding-left: 18px; /* subtle hover slide toward the content */
}}

QPushButton#NavButton:checked {{
    background-color: {ACCENT};
    color: {ON_ACCENT};
}}

QPushButton#LogoutButton {{
    background-color: transparent;
    color: {TEXT_SOFT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 9px 14px;
    font-size: 12px;
    font-weight: 600;
}}

QPushButton#LogoutButton:hover {{
    background-color: {LAYER2};
    color: {TEXT};
    border-color: {LAYER3};
}}

QFrame#Header {{
    background-color: {LAYER1};
    border-bottom: 1px solid {BORDER};
}}

QLabel#UserChip {{
    color: {TEXT};
    font-size: 12px;
    font-weight: 600;
    background-color: {LAYER2};
    padding: 6px 14px;
    border-radius: 14px;
}}

QWidget#ContentArea {{
    background-color: {BACKGROUND};
}}

QScrollArea#ContentScrollArea {{
    border: none;
}}

QFrame#StatCard {{
    background-color: {LAYER1};
    border: 1px solid {BORDER};
    border-top: 1px solid rgba(255, 255, 255, 16);
    border-radius: 12px;
}}

QLabel#StatCardTitle {{
    color: {TEXT_SOFT};
    font-size: 12px;
    font-weight: 600;
    background: transparent;
}}

QLabel#StatCardValue {{
    color: {TEXT};
    font-size: 24px;
    font-weight: 700;
    background: transparent;
}}

/* --- Collapsible sections --- */

QFrame#CollapsibleSection {{
    background-color: {LAYER1};
    border: 1px solid {BORDER};
    border-top: 1px solid rgba(255, 255, 255, 14);
    border-radius: 10px;
}}

QPushButton#CollapsibleSectionHeader {{
    background-color: transparent;
    color: {TEXT};
    border: none;
    text-align: left;
    font-weight: 700;
    padding: 10px 12px;
}}

QPushButton#CollapsibleSectionHeader:hover {{
    color: {ACCENT_HOVER};
}}

/* --- Login screen --- */

QFrame#LoginHeroPanel {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {HERO_GRADIENT_START}, stop:1 {HERO_GRADIENT_END});
    border-top-left-radius: 18px;
    border-bottom-left-radius: 18px;
}}

QLabel#HeroTitle {{
    color: {ON_ACCENT};
    font-size: 26px;
    font-weight: 700;
    background: transparent;
}}

QLabel#HeroSubtitle {{
    color: rgba(255, 255, 255, 215);
    font-size: 13px;
    background: transparent;
}}

QFrame#LoginCard {{
    background-color: {LAYER1};
    border-top-right-radius: 18px;
    border-bottom-right-radius: 18px;
}}

QLabel#LoginCardTitle {{
    font-size: 22px;
    font-weight: 700;
    color: {TEXT};
    background: transparent;
}}

QLabel#HelperText {{
    color: {TEXT_FAINT};
    font-size: 11px;
    background: transparent;
}}

/* --- Feedback popup --- */

QDialog#FeedbackDialog {{
    background: transparent;
}}

QFrame#FeedbackCard {{
    background-color: {LAYER3};
    border: 1px solid {BORDER};
    border-top: 1px solid rgba(255, 255, 255, 20);
    border-radius: 16px;
}}

/* --- UI interactivity round --- */

QLineEdit#TableSearchInput {{
    background-color: {LAYER2};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 12px;
    font-size: 12px;
    color: {TEXT};
}}

QLineEdit#TableSearchInput:focus {{
    border-color: {ACCENT};
}}

QLabel#Toast {{
    background-color: {LAYER3};
    color: {TEXT};
    border: 1px solid {ACCENT};
    border-radius: 10px;
    padding: 12px 18px;
    font-size: 12px;
    font-weight: 600;
}}

QDialog#CommandPalette {{
    background: transparent;
}}

QLabel#EmptyStateLabel {{
    color: {TEXT_FAINT};
    font-size: 13px;
    background: transparent;
    padding: 24px;
}}

QLineEdit#ValidatedInputError {{
    border: 1px solid #E4572E;
}}

QPushButton#DangerButton {{
    background-color: transparent;
    color: #E4572E;
    border: 1px solid #E4572E;
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 12px;
    font-weight: 600;
}}

QPushButton#DangerButton:hover {{
    background-color: #E4572E;
    color: #FFFFFF;
}}
"""
