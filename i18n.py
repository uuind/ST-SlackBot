import os
import json
import html
from pathlib import Path
from typing import Any, Dict, Optional

LOCALES_DIR = Path(__file__).parent / "locales"
DEFAULT_LOCALE = "en"
GUIDE_FILE = LOCALES_DIR / "guide_explanations.json"

_current_locale = DEFAULT_LOCALE
_locale_data: Dict[str, Any] = {}
_guide_data: Dict[str, Dict[str, str]] = {}
_locale_mtime = 0.0
_guide_mtime = 0.0


def load_locale(locale_code: str = DEFAULT_LOCALE) -> Dict[str, Any]:
    """Load locale phrases from JSON file with mtime checking."""
    global _current_locale, _locale_data, _locale_mtime
    _current_locale = locale_code
    filepath = LOCALES_DIR / f"{locale_code}.json"
    if not filepath.exists():
        filepath = LOCALES_DIR / f"{DEFAULT_LOCALE}.json"

    if filepath.exists():
        try:
            mtime = filepath.stat().st_mtime
            if mtime != _locale_mtime or not _locale_data:
                with open(filepath, "r", encoding="utf-8") as f:
                    _locale_data = json.load(f)
                _locale_mtime = mtime
        except Exception:
            if not _locale_data:
                _locale_data = {}
    else:
        _locale_data = {}

    return _locale_data


def load_guide(filepath: Optional[Path] = None) -> Dict[str, Dict[str, str]]:
    """Load element guide explanations from JSON file with mtime checking."""
    global _guide_data, _guide_mtime
    target = filepath or GUIDE_FILE
    if target.exists():
        try:
            mtime = target.stat().st_mtime
            if mtime != _guide_mtime or not _guide_data:
                with open(target, "r", encoding="utf-8") as f:
                    _guide_data = json.load(f)
                _guide_mtime = mtime
        except Exception:
            if not _guide_data:
                _guide_data = {}
    else:
        _guide_data = {}
    return _guide_data


def reload():
    """Reload all locale and guide data from disk."""
    load_locale(_current_locale)
    load_guide()


# Initialize upon module load
load_locale(DEFAULT_LOCALE)
load_guide()


def t(key: str, default: Optional[str] = None, **kwargs) -> str:
    """
    Look up a localized phrase using dot-separated notation (e.g. 'setup.step_title').
    Supports keyword interpolation: t('setup.members_loaded', count=12).
    """
    if not _locale_data:
        load_locale(_current_locale)

    parts = key.split(".")
    val: Any = _locale_data
    for p in parts:
        if isinstance(val, dict) and p in val:
            val = val[p]
        else:
            val = None
            break

    if val is None or not isinstance(val, str):
        if default is not None:
            val = default
        else:
            # Fallback to key's last segment formatted nicely
            val = parts[-1].replace("_", " ").capitalize()

    if kwargs and isinstance(val, str):
        try:
            val = val.format(**kwargs)
        except (KeyError, ValueError):
            pass

    return str(val)


GUIDE_CATEGORIES = {
    "General & Header": [
        "app_header",
        "guide_toggle",
        "mode_badge"
    ],
    "Step 1: Setup & Data": [
        "roster_directory",
        "roster_fetch",
        "roster_import",
        "roster_export",
        "roster_editor",
        "spreadsheet_selection",
        "mode_detection",
        "mode_override",
        "message_header",
        "sheet_preview",
        "parse_proceed_button"
    ],
    "Step 2: Groups & Assignments": [
        "groups_overview",
        "auto_detect_all",
        "add_group",
        "clear_group_names",
        "membership_summary",
        "unassigned_warnings",
        "group_card",
        "group_col_select",
        "indiv_col_select",
        "member_multiselect",
        "detect_single_group",
        "generate_comments_btn",
        "lc_overview"
    ],
    "Step 3: Sample & Preview": [
        "comments_overview",
        "recipient_metrics",
        "recipient_selector",
        "slack_dm_preview",
        "raw_markdown",
        "section_breakdown",
        "audit_all"
    ],
    "Step 4: Review & Send": [
        "send_overview",
        "recipient_checklist",
        "test_send",
        "broadcast_confirmation",
        "broadcast_button"
    ],
    "Sidebar & Config": [
        "optional_settings",
        "slack_token",
        "group_keywords",
        "indiv_keywords",
        "exclude_keywords",
        "config_io"
    ]
}


def get_guide_categories() -> Dict[str, list]:
    """Return categorized index of all guide topic keys."""
    return GUIDE_CATEGORIES


def get_guide_status() -> Dict[str, Any]:
    """Returns diagnostics confirming guide explanations are loaded and intact."""
    if not _guide_data:
        load_guide()
    total = len(_guide_data)
    valid_entries = sum(1 for v in _guide_data.values() if v.get("title") and v.get("description"))
    return {
        "loaded_count": total,
        "valid_count": valid_entries,
        "is_healthy": total > 0 and total == valid_entries,
        "categories": {cat: [k for k in keys if k in _guide_data] for cat, keys in GUIDE_CATEGORIES.items()}
    }


def get_guide_explanation(key: str) -> Optional[Dict[str, str]]:
    """Retrieve title, description, and tip for a specific UI element."""
    if not _guide_data:
        load_guide()
    res = _guide_data.get(key)
    if not res:
        # Reload once in case file was touched or modified externally
        load_guide()
        res = _guide_data.get(key)
    return res


def get_all_guide_explanations() -> Dict[str, Dict[str, str]]:
    """Return all guide explanations."""
    if not _guide_data:
        load_guide()
    return _guide_data


def guide_badge(key: str, is_active: bool = True) -> str:
    """
    Returns HTML for an interactive guide hover badge with popup tooltip.
    Renders only if `is_active` is True.
    Constructs a strictly single-line, zero-newline string of pure <span> tags
    so that CommonMark markdown parsers never break paragraph parsing.
    """
    if not is_active:
        return ""

    info = get_guide_explanation(key)
    if not info:
        # Graceful fallback so a missing badge key is immediately visible to developer/user
        title = html.escape(f"Help: {key.replace('_', ' ').title()}")
        desc = html.escape(f"Explanation for '{key}' is being initialized.")
        tip_html = ""
    else:
        title = html.escape(str(info.get("title", "")))
        desc = html.escape(str(info.get("description", "")))
        tip = html.escape(str(info.get("tip", "")))
        tip_html = f'<span class="guide-tooltip-tip">💡 <b>Tip:</b> {tip}</span>' if tip else ""

    # Strictly single-line HTML with NO newlines
    return (
        f'<span class="guide-target" data-guide-key="{html.escape(key)}">'
        f'<span class="guide-badge">?</span>'
        f'<span class="guide-tooltip">'
        f'<span class="guide-tooltip-title">{title}</span>'
        f'<span class="guide-tooltip-desc">{desc}</span>'
        f'{tip_html}'
        f'</span>'
        f'</span>'
    )
