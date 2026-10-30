import os
import json
import time
import random
import importlib
from collections import defaultdict
import streamlit as st
import pandas as pd
from pathlib import Path
import html

import config
import bot_logic
import auth
import i18n

# Force reload helper modules so Streamlit Cloud picks up newly added functions without stale cache
try:
    importlib.reload(config)
    importlib.reload(bot_logic)
    importlib.reload(auth)
    importlib.reload(i18n)
except Exception:
    pass


def safe_parse_name_list_json(raw_content) -> dict:
    """Parse name list JSON via bot_logic with defensive local fallback."""
    if hasattr(bot_logic, "parse_name_list_json"):
        return bot_logic.parse_name_list_json(raw_content)

    if isinstance(raw_content, (bytes, bytearray)):
        raw_content = raw_content.decode("utf-8")
    data = json.loads(raw_content) if isinstance(raw_content, str) else raw_content
    result = {}
    if isinstance(data, dict):
        items = data.get("members") or data.get("users") or data.get("roster")
        if not items:
            for k, v in data.items():
                if isinstance(v, str):
                    result[str(k).strip().lower()] = v.strip()
                elif isinstance(v, dict):
                    sid = v.get("id") or v.get("slack_id") or ""
                    result[str(k).strip().lower()] = str(sid).strip()
            return result
    elif isinstance(data, list):
        items = data
    else:
        return {}

    for item in items:
        if isinstance(item, dict):
            name = item.get("name") or item.get("Name") or item.get("member") or ""
            sid = item.get("slack_id") or item.get("Slack ID") or item.get("id") or ""
            if name:
                result[str(name).strip().lower()] = str(sid).strip()
    return result

# -----------------------------------------------------------------------------
# Streamlit Page Setup
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="ST SlackBot",
    page_icon="🥁",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom CSS for styling
st.markdown("""
<style>
    .main-title {
        font-size: 2.2rem;
        font-weight: 700;
        color: #1f2937;
        margin-bottom: 0.2rem;
    }
    .sub-title {
        color: #4b5563;
        font-size: 1.05rem;
        margin-bottom: 1.2rem;
    }
    .slack-preview-card {
        background-color: #1e1e24;
        color: #f3f4f6;
        border-radius: 8px;
        padding: 1.2rem;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        border-left: 4px solid #4a154b;
        margin-bottom: 1rem;
        white-space: pre-wrap;
    }
    .slack-preview-header {
        color: #9ca3af;
        font-size: 0.85rem;
        font-weight: 600;
        margin-bottom: 0.5rem;
    }
    .badge-pd {
        background-color: #e0f2fe;
        color: #0369a1;
        padding: 3px 8px;
        border-radius: 12px;
        font-size: 0.8rem;
        font-weight: 600;
    }
    .badge-lc {
        background-color: #fef3c7;
        color: #92400e;
        padding: 3px 8px;
        border-radius: 12px;
        font-size: 0.8rem;
        font-weight: 600;
    }
    /* Distinct Group Assignment Card Styling & Separation */
    .group-card-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        background: linear-gradient(90deg, rgba(99, 102, 241, 0.22) 0%, rgba(99, 102, 241, 0.05) 100%);
        border-left: 5px solid #6366f1;
        padding: 8px 14px;
        border-radius: 6px;
        margin-bottom: 14px;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    }
    .group-badge-num {
        background: linear-gradient(135deg, #6366f1, #4f46e5);
        color: #ffffff;
        font-size: 0.76rem;
        font-weight: 700;
        padding: 3px 8px;
        border-radius: 4px;
        letter-spacing: 0.6px;
    }
    .group-member-count {
        font-size: 0.85rem;
        color: #cbd5e1;
        font-weight: 500;
    }
    div[data-testid="stVerticalBlock"] > div[data-testid="stVerticalBlockBorderWrapper"]:has(.group-card-header) {
        border: 1px solid rgba(99, 102, 241, 0.35) !important;
        border-left: 5px solid #6366f1 !important;
        border-radius: 10px !important;
        background-color: rgba(30, 41, 59, 0.25) !important;
        box-shadow: 0 4px 14px -3px rgba(0, 0, 0, 0.25) !important;
        margin-bottom: 22px !important;
        transition: border-color 0.15s ease, box-shadow 0.15s ease;
    }
    div[data-testid="stVerticalBlock"] > div[data-testid="stVerticalBlockBorderWrapper"]:has(.group-card-header):hover {
        border-color: rgba(99, 102, 241, 0.65) !important;
        box-shadow: 0 6px 18px -2px rgba(99, 102, 241, 0.2) !important;
    }
    /* Guide Mode & Hover Overlay Tooltip Styles */
    .guide-banner {
        background: linear-gradient(90deg, #312e81 0%, #4338ca 100%);
        color: #ffffff;
        border-radius: 8px;
        padding: 0.75rem 1.1rem;
        margin-bottom: 0.8rem;
        box-shadow: 0 4px 6px -1px rgba(79, 70, 229, 0.25);
        border: 1px solid #6366f1;
        font-size: 0.9rem;
    }
    .guide-sample-badge {
        background: #f59e0b;
        color: #1e1b4b;
        border-radius: 50%;
        display: inline-flex;
        width: 17px;
        height: 17px;
        align-items: center;
        justify-content: center;
        font-weight: 800;
        font-size: 11px;
    }
    /* Permanently visible sidebar collapse & expand controls */
    div[data-testid="stSidebarCollapseButton"],
    div[data-testid="stSidebarCollapseButton"] button,
    button[aria-label="Collapse sidebar"] {
        visibility: visible !important;
        display: inline-flex !important;
        opacity: 1 !important;
    }
    div[data-testid="stExpandSidebarButton"],
    div[data-testid="stExpandSidebarButton"] button,
    button[aria-label="Expand sidebar"],
    [data-testid="collapsedControl"] {
        visibility: visible !important;
        display: inline-flex !important;
        opacity: 1 !important;
    }
    [data-testid="stExpandSidebarButton"] button,
    button[aria-label="Expand sidebar"] {
        background-color: #1e1b4b !important;
        color: #ffffff !important;
        border: 1px solid #6366f1 !important;
        border-radius: 8px !important;
        box-shadow: 0 2px 8px rgba(99, 102, 241, 0.4) !important;
        padding: 4px 8px !important;
        cursor: pointer !important;
    }
    [data-testid="stSidebarCollapseButton"] button {
        background-color: rgba(99, 102, 241, 0.15) !important;
        border: 1px solid #6366f1 !important;
        border-radius: 6px !important;
    }
    /* Sidebar Tooltips: Stay inside sidebar bounds and hover above everything */
    section[data-testid="stSidebar"] {
        z-index: 9999999 !important;
    }
    [data-testid="stSidebar"] .guide-target {
        position: relative !important;
    }
    [data-testid="stSidebar"] .guide-tooltip {
        left: auto !important;
        right: 0 !important;
        width: 250px !important;
        max-width: 80vw !important;
    }
    [data-testid="stSidebar"] .guide-tooltip::after {
        left: auto !important;
        right: 14px !important;
    }
    /* Workflow Stepper Navigation */
    div[data-testid="stSegmentedControl"] {
        display: flex !important;
        justify-content: center !important;
        margin-bottom: 1.2rem !important;
    }
    div[data-testid="stSegmentedControl"] button {
        font-weight: 600 !important;
        font-size: 0.95rem !important;
        padding: 6px 20px !important;
    }
    /* Ensure Step 1 left (Roster) and right (Spreadsheet) containers are always the exact same height */
    [data-testid="stHorizontalBlock"]:has([data-testid="stDataEditor"]) {
        display: flex !important;
        align-items: stretch !important;
    }
    [data-testid="stHorizontalBlock"]:has([data-testid="stDataEditor"]) > [data-testid="column"] {
        display: flex !important;
        flex-direction: column !important;
    }
    [data-testid="stHorizontalBlock"]:has([data-testid="stDataEditor"]) > [data-testid="column"] > [data-testid="stVerticalBlockBorderWrapper"] {
        display: flex !important;
        flex-direction: column !important;
        flex: 1 !important;
        height: 100% !important;
        min-height: 540px !important;
    }
    [data-testid="stHorizontalBlock"]:has([data-testid="stDataEditor"]) > [data-testid="column"] > [data-testid="stVerticalBlockBorderWrapper"] > [data-testid="stVerticalBlock"] {
        display: flex !important;
        flex-direction: column !important;
        flex: 1 !important;
        height: 100% !important;
    }
    [data-testid="column"] {
        overflow: visible !important;
    }
    div[data-testid="stMarkdownContainer"] {
        overflow: visible !important;
    }
    .guide-target {
        position: relative;
        display: inline-block;
        vertical-align: middle;
        margin-left: 6px;
        cursor: help;
    }
    .guide-badge {
        background: linear-gradient(135deg, #6366f1, #8b5cf6);
        color: #ffffff !important;
        font-size: 0.72rem;
        font-weight: 700;
        width: 18px;
        height: 18px;
        border-radius: 50%;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        box-shadow: 0 0 8px rgba(99, 102, 241, 0.7);
        border: 1px solid rgba(255, 255, 255, 0.4);
        transition: transform 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
    }
    .guide-target:hover .guide-badge {
        transform: scale(1.3);
        box-shadow: 0 0 12px rgba(245, 158, 11, 0.95);
        background: linear-gradient(135deg, #f59e0b, #d97706);
    }
    .guide-tooltip {
        display: none !important;
        position: absolute;
        z-index: 999999999 !important;
        top: calc(100% + 8px);
        left: -8px;
        transform: none;
        width: 320px;
        max-width: min(340px, 85vw);
        background-color: #0f172a;
        color: #f8fafc;
        padding: 10px 14px;
        border-radius: 8px;
        border: 1px solid #6366f1;
        box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.6), 0 8px 10px -6px rgba(0, 0, 0, 0.4);
        pointer-events: none;
        font-size: 0.85rem;
        line-height: 1.45;
        text-align: left;
        white-space: normal;
    }
    .guide-tooltip::after {
        content: "";
        position: absolute;
        bottom: 100%;
        left: 12px;
        margin-left: 0;
        border-width: 6px;
        border-style: solid;
        border-color: transparent transparent #0f172a transparent;
    }
    /* Auto-anchor right for right-aligned containers (e.g. mode badge) */
    [style*="text-align: right"] .guide-tooltip,
    .guide-target-right .guide-tooltip {
        left: auto !important;
        right: 0 !important;
    }
    [style*="text-align: right"] .guide-tooltip::after,
    .guide-target-right .guide-tooltip::after {
        left: auto !important;
        right: 12px !important;
    }
    .guide-target:hover .guide-tooltip {
        display: block !important;
    }
    .guide-tooltip-title {
        display: block;
        font-weight: 700;
        font-size: 0.92rem;
        color: #38bdf8;
        margin-bottom: 5px;
        border-bottom: 1px solid #334155;
        padding-bottom: 3px;
    }
    .guide-tooltip-desc {
        display: block;
        color: #e2e8f0;
        margin-bottom: 6px;
        font-size: 0.82rem;
    }
    .guide-tooltip-tip {
        display: block;
        background-color: rgba(245, 158, 11, 0.15);
        border-left: 3px solid #f59e0b;
        padding: 4px 8px;
        border-radius: 4px;
        font-size: 0.78rem;
        color: #fef3c7;
        margin-top: 4px;
    }
</style>
""", unsafe_allow_html=True)


def gb(key: str) -> str:
    """Helper to render guide badge HTML when guide mode is enabled."""
    return i18n.guide_badge(key, is_active=st.session_state.get("guide_mode", False))


# -----------------------------------------------------------------------------
# Session State Initialization
# -----------------------------------------------------------------------------
if "config_loaded" not in st.session_state:
    config.load_config()
    st.session_state["config_loaded"] = True

if "name_dict" not in st.session_state:
    st.session_state["name_dict"] = bot_logic.load_name_list(config.name_filepath)

if "group_configs" not in st.session_state:
    st.session_state["group_configs"] = []

if "parsed_comments" not in st.session_state:
    st.session_state["parsed_comments"] = {}

if "full_messages" not in st.session_state:
    st.session_state["full_messages"] = {}

if "active_spreadsheet_name" not in st.session_state:
    st.session_state["active_spreadsheet_name"] = config.form_file

if "message_header_text" not in st.session_state:
    base = os.path.splitext(os.path.basename(config.form_file))[0] if config.form_file else ""
    st.session_state["message_header_text"] = f"{base}" if base else ""

if "selected_recipient_idx" not in st.session_state:
    st.session_state["selected_recipient_idx"] = 0

if "has_assigned_names" not in st.session_state:
    st.session_state["has_assigned_names"] = False

if "slack_token" not in st.session_state:
    st.session_state["slack_token"] = config.slack_token

if "name_list_source" not in st.session_state:
    st.session_state["name_list_source"] = config.name_filepath

if "guide_mode" not in st.session_state:
    st.session_state["guide_mode"] = False

if "current_step" not in st.session_state:
    st.session_state["current_step"] = 1

if "sidebar_auto_collapsed" not in st.session_state:
    st.session_state["sidebar_auto_collapsed"] = True
    import streamlit.components.v1 as components
    components.html("""
    <script>
    (function() {
        try {
            const pDoc = window.parent.document;
            // 1. Ensure initial sidebar state is collapsed on first load
            const sidebar = pDoc.querySelector('[data-testid="stSidebar"]');
            if (sidebar && sidebar.getAttribute('aria-expanded') !== 'false' && sidebar.getAttribute('data-collapsed') !== 'true') {
                const btn = pDoc.querySelector('button[aria-label="Collapse sidebar"]') || pDoc.querySelector('[data-testid="stSidebarCollapseButton"] button');
                if (btn) {
                    btn.click();
                } else {
                    const content = pDoc.querySelector('[data-testid="stSidebarContent"]');
                    if (content) {
                        content.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
                        setTimeout(() => {
                            const b = pDoc.querySelector('button[aria-label="Collapse sidebar"]') || pDoc.querySelector('[data-testid="stSidebarCollapseButton"] button');
                            if (b) b.click();
                        }, 80);
                    }
                }
            }
            // 2. Keep the collapse button mounted in React so it remains permanently visible
            function keepCollapseMounted() {
                try {
                    const c = pDoc.querySelector('[data-testid="stSidebarContent"]');
                    if (c) {
                        c.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
                    }
                } catch(err) {}
            }
            setInterval(keepCollapseMounted, 1200);
        } catch(e) {}
    })();
    </script>
    """, height=0, width=0)


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------
def get_active_token():
    """Get active Slack bot token from session state or config."""
    return st.session_state.get("slack_token") or config.slack_token


def refresh_name_list():
    st.session_state["name_dict"] = bot_logic.load_name_list(config.name_filepath)
    st.session_state["name_list_source"] = config.name_filepath


def clear_group_gui_state():
    """Clear all group and member GUI items and parsed feedback."""
    keys_to_clear = [
        k for k in list(st.session_state.keys())
        if any(k.startswith(prefix) for prefix in (
            "members_", "input_add_", "btn_add_", "multiselect_group_",
            "g_col_", "i_col_", "name_", "title_", "custom_name_",
            "btn_detect_", "del_group_", "btn_clr_", "add_miss_"
        ))
    ]
    for k in keys_to_clear:
        del st.session_state[k]
    st.session_state["group_configs"] = []
    st.session_state["parsed_comments"] = {}
    st.session_state["full_messages"] = {}
    st.session_state["selected_recipient_idx"] = 0
    st.session_state["has_assigned_names"] = False


def trigger_parse_comments(sheet):
    """Parse comments according to current mode and group/column config."""
    name_list = list(st.session_state["name_dict"].keys())

    # Retrieve or derive message header text
    header_title = st.session_state.get("message_header_text")
    if not header_title:
        active_sheet_name = st.session_state.get("active_spreadsheet_name", "")
        base_name = os.path.splitext(os.path.basename(active_sheet_name))[0] if active_sheet_name else ""
        header_title = f"{base_name}" if base_name else ""

    if config.mode == "PD":
        if st.session_state["group_configs"]:
            # Sync members and columns from session state if present
            for g in st.session_state["group_configs"]:
                gid = g.get("id")
                if gid and f"members_{gid}" in st.session_state:
                    g["members"] = list(st.session_state[f"members_{gid}"])
                if gid and f"g_col_{gid}" in st.session_state:
                    g["group_col"] = st.session_state[f"g_col_{gid}"]
                if gid and f"i_col_{gid}" in st.session_state:
                    g["indiv_col"] = st.session_state[f"i_col_{gid}"]
                if gid and f"name_{gid}" in st.session_state:
                    g["group_name"] = st.session_state[f"name_{gid}"]
            comments, msgs = bot_logic.parse_pd_comments(sheet, st.session_state["group_configs"], header_title=header_title)
            st.session_state["parsed_comments"] = comments
            st.session_state["full_messages"] = msgs
            st.session_state["last_parsed_mode"] = "PD"
    elif config.mode == "LC":
        comments, msgs = bot_logic.parse_lc_comments(sheet, name_list, header_title=header_title)
        st.session_state["parsed_comments"] = comments
        st.session_state["full_messages"] = msgs
        st.session_state["last_parsed_mode"] = "LC"


# -----------------------------------------------------------------------------
# User Authentication Screen (Access Gate)
# -----------------------------------------------------------------------------
if not st.session_state.get("authenticated"):
    st.markdown('<div class="main-title">🥁 ST SlackBot</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">Feedback sender for (M)(A)(O)PPs & EOQM/EOYM feedback</div>', unsafe_allow_html=True)
    st.markdown("---")

    col_l1, col_l2, col_l3 = st.columns([1, 2, 1])
    with col_l2:
        st.markdown("### 🔐 User Login")
        st.caption("Please sign in with your username and password.")

        with st.form("login_form"):
            username_input = st.text_input("Username", placeholder="Enter username")
            password_input = st.text_input("Password", type="password", placeholder="Enter password")
            submit_login = st.form_submit_button("Sign In", type="primary", use_container_width=True)

            if submit_login:
                ok, err_msg = auth.verify_credentials(username_input, password_input)
                if ok:
                    st.session_state["authenticated"] = True
                    st.session_state["user_label"] = username_input.strip()
                    st.toast(f"Welcome, {st.session_state['user_label']}!", icon="👋")
                    st.rerun()
                else:
                    st.error(err_msg)

        with st.expander("ℹ️ Configuring user accounts on Streamlit Cloud", expanded=False):
            st.markdown(
                "In your Streamlit Cloud **App Settings → Secrets** (or `.streamlit/secrets.toml` locally):\n"
                "```toml\n"
                "[users]\n"
                'admin = "admin_password"\n'
                'audrey = "audrey_password"\n'
                'pd_lead = "pd_team_password"\n'
                "```\n"
                "*(Default local fallback: username `admin` / password `taiko`)*"
            )

    st.stop()


# -----------------------------------------------------------------------------
# Sidebar: User Info, Bot Connection & Advanced Settings
# -----------------------------------------------------------------------------
with st.sidebar:
    u_label = st.session_state.get("user_label", "Admin")
    c_u1, c_u2 = st.columns([2, 1])
    with c_u1:
        st.markdown(f"**👤 User:** `{u_label}`")
    with c_u2:
        if st.button("Log Out", key="sidebar_logout", use_container_width=True):
            st.session_state["authenticated"] = False
            clear_group_gui_state()
            st.rerun()

    st.markdown("---")
    # Slack Bot Connection
    st.markdown(f"##### 🔌 Slack Bot Connection {gb('slack_token')}", unsafe_allow_html=True)
    cfg_token = st.text_input(
        "Slack Bot Token",
        value=get_active_token(),
        type="password",
        help="Bot user token starting with xoxb-.",
        label_visibility="collapsed"
    )
    col_t_save, col_t_test = st.columns(2)
    with col_t_save:
        if st.button("💾 Save Token", key="sb_save_token", use_container_width=True):
            clean_tok, _ = config.save_token(cfg_token)
            st.session_state["slack_token"] = clean_tok
            st.toast("Saved Slack token!", icon="🔌")
    with col_t_test:
        if st.button("🧪 Test Auth", key="sb_test_token", use_container_width=True):
            with st.spinner("Testing connection..."):
                ok, res = bot_logic.test_slack_token(get_active_token(), config.slack_api_url)
                if ok:
                    st.success(f"Connected: @{res.get('user')}")
                else:
                    st.error(f"Failed: {res}")

    # Advanced Settings (Collapsed Expander)
    with st.expander("⚙️ Advanced Settings", expanded=False):
        st.markdown(f"**⚙️ Advanced Settings** {gb('optional_settings')}", unsafe_allow_html=True)
        st.markdown(f"**Group Column Terms** {gb('group_keywords')}", unsafe_allow_html=True)
        g_terms_in = st.text_input(
            "Group Column Terms",
            value=", ".join(config.group_search_list),
            help="Terms identifying group columns",
            label_visibility="collapsed"
        )
        st.markdown(f"**Individual Column Terms** {gb('indiv_keywords')}", unsafe_allow_html=True)
        i_terms_in = st.text_input(
            "Individual Column Terms",
            value=", ".join(config.indiv_search_list),
            help="Terms identifying individual columns",
            label_visibility="collapsed"
        )
        st.markdown(f"**Excluded Header Terms** {gb('exclude_keywords')}", unsafe_allow_html=True)
        e_terms_in = st.text_input(
            "Excluded Header Terms",
            value=", ".join(config.exclude_search_list),
            help="Terms to ignore from group detection (e.g. PDs, ADs, Leadership, Timestamp)",
            label_visibility="collapsed"
        )
        if st.button("💾 Save Keywords", key="sb_save_keywords", use_container_width=True):
            up_group = [t.strip() for t in g_terms_in.split(",") if t.strip()]
            up_indiv = [t.strip() for t in i_terms_in.split(",") if t.strip()]
            up_exclude = [t.strip() for t in e_terms_in.split(",") if t.strip()]
            cfg = config.load_config()
            if "search" not in cfg:
                cfg["search"] = {}
            cfg["search"]["group_terms"] = up_group
            cfg["search"]["indiv_terms"] = up_indiv
            cfg["search"]["exclude_terms"] = up_exclude
            cfg["search"].pop("terms", None)
            config.save_config(cfg)
            config.group_search_list = up_group
            config.indiv_search_list = up_indiv
            config.exclude_search_list = up_exclude
            config.search_list = up_group + up_indiv
            st.toast("Keywords saved!", icon="🔍")

        st.markdown("---")
        st.markdown(f"**Configuration File** {gb('config_io')}", unsafe_allow_html=True)
        col_c_imp, col_c_exp = st.columns(2)
        with col_c_imp:
            with st.popover("📥 Import", use_container_width=True):
                uploaded_cfg = st.file_uploader("Upload config.json", type=["json"], key="sb_cfg_upload")
                if uploaded_cfg is not None:
                    try:
                        cfg_data = json.loads(uploaded_cfg.getvalue().decode("utf-8"))
                        if isinstance(cfg_data, dict):
                            config.save_config(cfg_data)
                            st.toast("Imported configuration!", icon="⚙️")
                            st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")
        with col_c_exp:
            current_cfg_str = json.dumps(config.load_config(), indent=2)
            st.download_button(
                "📤 Export",
                data=current_cfg_str,
                file_name="config.json",
                mime="application/json",
                use_container_width=True,
                key="sb_cfg_export"
            )

        st.markdown("---")
        st.link_button("📖 View README on GitHub", "https://github.com/uuind/ST-SlackBot#readme", use_container_width=True)


# -----------------------------------------------------------------------------
# Main Header
# -----------------------------------------------------------------------------
col_title, col_ctrls = st.columns([2.2, 1.8])
with col_title:
    st.markdown(f'<div class="main-title">{i18n.t("header.title")} {gb("app_header")}</div>', unsafe_allow_html=True)
    u_label = st.session_state.get("user_label", "Admin")
    st.caption(f"Logged in as **@{u_label}**")

with col_ctrls:
    c_badge, c_readme, c_guide = st.columns([1, 1.1, 1.4])
    with c_badge:
        mode_badge_html = f'<div style="text-align: right; margin-top: 6px;"><span class="{"badge-pd" if config.mode == "PD" else "badge-lc"}">{config.mode} MODE</span> {gb("mode_badge")}</div>'
        st.markdown(mode_badge_html, unsafe_allow_html=True)
    with c_readme:
        st.link_button("📖 README", "https://github.com/uuind/ST-SlackBot#readme", use_container_width=True, help="Open project documentation and README on GitHub")
    with c_guide:
        is_guide = st.session_state.get("guide_mode", False)
        guide_label = "✕ Exit Guide" if is_guide else "🧭 Help Guide"
        guide_type = "primary" if is_guide else "secondary"
        c_gb_btn, c_gb_icon = st.columns([4, 1])
        with c_gb_btn:
            if st.button(guide_label, key="main_header_guide_btn", type=guide_type, use_container_width=True, help="Toggle interactive help tooltips over UI elements"):
                st.session_state["guide_mode"] = not is_guide
                st.rerun()
        with c_gb_icon:
            st.markdown(f"<div style='margin-top: 6px;'>{gb('guide_toggle')}</div>", unsafe_allow_html=True)

# Single dismissible banner when Guide Mode is active
if st.session_state.get("guide_mode", False):
    g_status = i18n.get_guide_status()
    total_loaded = g_status.get("loaded_count", 0)
    c_gb1, c_gb2 = st.columns([5, 1.8])
    with c_gb1:
        st.info(f"💡 **Interactive Guide Active:** Hover over any purple `?` badge to see helpful tips. `{total_loaded}/{total_loaded} topics loaded & verified ✅`")
    with c_gb2:
        with st.popover(f"📖 Help Index ({total_loaded})", use_container_width=True):
            st.markdown("###### 📖 Help Topics Index")
            if st.button("🔄 Reload & Verify Guide Tips", key="reload_guide_btn", use_container_width=True):
                i18n.reload()
                st.toast(f"✅ Verified: {len(i18n.get_all_guide_explanations())} guide topics loaded and active!", icon="📖")
                st.rerun()

            all_exps = i18n.get_all_guide_explanations()
            categories = i18n.get_guide_categories()
            tab_names = ["All"] + list(categories.keys())
            guide_tabs = st.tabs(tab_names)

            for tab_idx, cat_name in enumerate(tab_names):
                with guide_tabs[tab_idx]:
                    if cat_name == "All":
                        cat_keys = list(all_exps.keys())
                    else:
                        cat_keys = categories.get(cat_name, [])

                    q = st.text_input(f"Filter topics:", placeholder="Search...", key=f"pop_search_{tab_idx}")
                    matched = 0
                    for k in cat_keys:
                        info = all_exps.get(k, {})
                        if not info:
                            continue
                        text_to_search = f"{k} {info.get('title', '')} {info.get('description', '')} {info.get('tip', '')}".lower()
                        if q and q.lower() not in text_to_search:
                            continue
                        matched += 1
                        st.markdown(f"**{info.get('title', k)}**")
                        st.write(info.get("description", ""))
                        if info.get("tip"):
                            st.caption(f"💡 {info['tip']}")
                        st.markdown("---")
                    if matched == 0:
                        st.caption("No matching topics found.")


# -----------------------------------------------------------------------------
# Step-by-Step Workflow Navigation (Single Unified Stepper)
# -----------------------------------------------------------------------------
if "current_step" not in st.session_state:
    st.session_state["current_step"] = 1

step_labels = {
    1: f"1. {i18n.t('nav.tab_setup')}",
    2: f"2. {i18n.t('nav.tab_groups_pd') if config.mode == 'PD' else i18n.t('nav.tab_groups_lc')}",
    3: f"3. {i18n.t('nav.tab_preview')}",
    4: f"4. {i18n.t('nav.tab_send')}"
}

def on_step_change():
    st.session_state["current_step"] = st.session_state["nav_step_control"]

def go_to_step(s: int):
    st.session_state["current_step"] = s
    st.rerun()

# Synchronize nav_step_control before the widget is created
st.session_state["nav_step_control"] = st.session_state["current_step"]

st.segmented_control(
    "Workflow Navigation",
    options=[1, 2, 3, 4],
    format_func=lambda s: step_labels[s],
    key="nav_step_control",
    on_change=on_step_change,
    label_visibility="collapsed"
)

active_step = st.session_state.get("current_step", 1)


# =============================================================================
# STEP 1: SETUP & SPREADSHEET
# =============================================================================
if active_step == 1:
    col_roster, col_sheet = st.columns(2)

    # Card 1: Member Directory
    with col_roster:
        with st.container(border=True):
            c_rh, c_rt = st.columns([3, 1])
            with c_rh:
                num_members = len(st.session_state["name_dict"])
                st.markdown(f"##### 👥 {i18n.t('setup.roster_heading')} `{num_members} members` {gb('roster_directory')}", unsafe_allow_html=True)
            with c_rt:
                with st.popover("⚙️ Tools", use_container_width=True):
                    st.markdown("###### Directory Tools")
                    st.markdown(f"<div style='font-size:0.8rem; color:#6366f1; margin-bottom:6px;'>Fetch {gb('roster_fetch')} | Import {gb('roster_import')} | Export {gb('roster_export')}</div>", unsafe_allow_html=True)
                    if st.button("🏷️ Fetch from Slack", use_container_width=True, help="Queries Slack API users.list via users:read to populate members & IDs"):
                        active_tok = get_active_token()
                        with st.spinner("Fetching members from Slack..."):
                            ok, res = bot_logic.fetch_slack_users(active_tok, config.slack_api_url)
                            if not ok:
                                st.error(res)
                            else:
                                existing_id_to_name = {v: k for k, v in st.session_state["name_dict"].items() if v}
                                new_dict = {}
                                slack_meta = dict(st.session_state.get("slack_user_meta", {}))
                                for m in res:
                                    uid = m["id"]
                                    assigned_name = existing_id_to_name.get(uid, m["suggested_name"])
                                    if assigned_name in new_dict and new_dict[assigned_name] != uid:
                                        assigned_name = m["username"].lower()
                                    new_dict[assigned_name] = uid
                                    slack_meta[uid] = f"{m['real_name']} (@{m['username']})" if m['real_name'] else f"@{m['username']}"

                                st.session_state["name_dict"] = new_dict
                                st.session_state["slack_user_meta"] = slack_meta
                                st.session_state["name_list_source"] = "Slack Workspace API (users.list)"
                                st.toast(f"Fetched {len(res)} members from Slack!", icon="🤖")
                                st.rerun()

                    uploaded_name_file = st.file_uploader(
                        "Import JSON",
                        type=["json"],
                        key="pop_upload_name_file",
                        help="Upload name_list.json"
                    )
                    if uploaded_name_file is not None:
                        name_sig = f"{uploaded_name_file.name}_{uploaded_name_file.size}"
                        if st.session_state.get("last_uploaded_name_sig") != name_sig:
                            try:
                                parsed_dict = safe_parse_name_list_json(uploaded_name_file.getvalue())
                                if parsed_dict:
                                    st.session_state["name_dict"] = parsed_dict
                                    st.session_state["name_list_source"] = uploaded_name_file.name
                                    st.session_state["last_uploaded_name_sig"] = name_sig
                                    bot_logic.save_name_list(parsed_dict, config.name_filepath)
                                    st.toast(f"Imported {len(parsed_dict)} members!", icon="📥")
                                    st.rerun()
                                else:
                                    st.error("No valid members found in JSON.")
                            except Exception as e:
                                st.error(f"Error parsing JSON: {e}")

                    json_export = json.dumps(st.session_state["name_dict"], indent=2)
                    st.download_button(
                        "📥 Export JSON",
                        data=json_export,
                        file_name="name_list.json",
                        mime="application/json",
                        use_container_width=True
                    )
                    if st.button("🔄 Reload from File", use_container_width=True):
                        refresh_name_list()
                        st.rerun()

            st.markdown(f"<div style='font-size:0.85rem; color:#9ca3af; margin-bottom:4px;'>Double-click any cell below to match names or edit Slack IDs: {gb('roster_editor')}</div>", unsafe_allow_html=True)
            slack_meta_cache = st.session_state.get("slack_user_meta", {})
            name_records = []
            for k, v in st.session_state["name_dict"].items():
                rec = {
                    "Spreadsheet Name": k,
                    "Slack ID": v,
                }
                if v in slack_meta_cache:
                    rec["Slack Profile Info"] = slack_meta_cache[v]
                name_records.append(rec)

            df_names = pd.DataFrame(name_records)
            col_config = {
                "Spreadsheet Name": st.column_config.TextColumn("Spreadsheet Name", required=True),
                "Slack ID": st.column_config.TextColumn("Slack User ID", required=True),
            }
            if "Slack Profile Info" in df_names.columns:
                col_config["Slack Profile Info"] = st.column_config.TextColumn("Slack Profile", disabled=True)

            edited_df = st.data_editor(
                df_names,
                height=340,
                num_rows="dynamic",
                use_container_width=True,
                column_config=col_config,
                key="setup_roster_editor"
            )

            if st.button("💾 Save Directory Changes", type="secondary", use_container_width=True):
                updated_dict = {}
                for _, row in edited_df.iterrows():
                    name_val = str(row.get("Spreadsheet Name", "")).strip().lower() if pd.notna(row.get("Spreadsheet Name")) else ""
                    id_val = str(row.get("Slack ID", "")).strip() if pd.notna(row.get("Slack ID")) else ""
                    if name_val:
                        updated_dict[name_val] = id_val
                st.session_state["name_dict"] = updated_dict
                bot_logic.save_name_list(updated_dict, config.name_filepath)
                st.toast(f"Saved {len(updated_dict)} members!", icon="💾")
                st.rerun()

    # Card 2: Spreadsheet Selection
    with col_sheet:
        with st.container(border=True):
            st.markdown(f"##### 📁 {i18n.t('setup.sheet_heading')} {gb('spreadsheet_selection')}", unsafe_allow_html=True)
            existing_files = bot_logic.get_available_spreadsheets(config.spreadsheet_folder)
            sheet_source = None
            loaded_file_label = ""

            c_src_type = st.radio("Selection Source", ["Select from folder", "Upload new (.xlsx)"], horizontal=True, label_visibility="collapsed")
            if c_src_type == "Select from folder":
                if existing_files:
                    default_idx = existing_files.index(config.form_file) if config.form_file in existing_files else 0
                    selected_file = st.selectbox("Select file", existing_files, index=default_idx, label_visibility="collapsed")
                    if selected_file:
                        sheet_source = os.path.join(config.spreadsheet_folder, selected_file)
                        loaded_file_label = selected_file
                        st.session_state["active_spreadsheet_name"] = selected_file
                else:
                    st.caption(f"No spreadsheets found in `{config.spreadsheet_folder}/`.")
            else:
                uploaded_file = st.file_uploader("Upload Excel spreadsheet (.xlsx)", type=["xlsx"], key="setup_uploader_file", label_visibility="collapsed")
                if uploaded_file is not None:
                    sheet_source = uploaded_file
                    loaded_file_label = uploaded_file.name
                    st.session_state["active_spreadsheet_name"] = uploaded_file.name
                    save_path = os.path.join(config.spreadsheet_folder, uploaded_file.name)
                    os.makedirs(config.spreadsheet_folder, exist_ok=True)
                    with open(save_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())

            if sheet_source is not None:
                try:
                    wb, sheet, sheet_names = bot_logic.load_workbook_and_sheet(sheet_source)
                    st.session_state["wb"] = wb
                    st.session_state["sheet"] = sheet

                    if len(sheet_names) > 1:
                        selected_sheet_name = st.selectbox("Worksheet", sheet_names, index=sheet_names.index(sheet.title) if sheet.title in sheet_names else 0)
                        if selected_sheet_name != sheet.title:
                            sheet = wb[selected_sheet_name]
                            st.session_state["sheet"] = sheet

                    headers = bot_logic.get_sheet_headers(sheet)
                    st.session_state["headers"] = headers

                    # Auto-detection
                    all_known = list(st.session_state["name_dict"].keys())
                    detected_mode, detect_reason, _ = bot_logic.detect_spreadsheet_mode(
                        headers, all_known, config.group_search_list, config.indiv_search_list, config.exclude_search_list
                    )
                    st.session_state["detected_mode"] = detected_mode
                    st.session_state["detected_reason"] = detect_reason

                    if st.session_state.get("last_loaded_file") != loaded_file_label:
                        st.session_state["last_loaded_file"] = loaded_file_label
                        base_name = os.path.splitext(loaded_file_label)[0]
                        default_title = f"{base_name}"
                        st.session_state["message_header_text"] = default_title
                        st.session_state["input_message_header"] = default_title
                        clear_group_gui_state()
                        if config.mode != detected_mode:
                            config.mode = detected_mode
                            cfg = config.load_config()
                            cfg["mode"] = detected_mode
                            config.save_config(cfg)
                        if config.mode == "PD":
                            paired, _, _ = bot_logic.detect_groups_pd(
                                headers, config.group_search_list, config.indiv_search_list, config.exclude_search_list
                            )
                            if paired:
                                st.session_state["group_configs"] = [
                                    {
                                        "id": f"grp_{i}_{int(time.time()*1000)}",
                                        "group_name": p["group_name"],
                                        "group_col": p["group_col"],
                                        "indiv_name": p["indiv_name"],
                                        "indiv_col": p["indiv_col"],
                                        "members": []
                                    }
                                    for i, p in enumerate(paired)
                                ]
                            else:
                                # When groups haven't been detected yet, ensure exactly 1 group is visible
                                default_gid = f"grp_0_{int(time.time()*1000)}"
                                st.session_state["group_configs"] = [{
                                    "id": default_gid,
                                    "group_name": "Group 1",
                                    "group_col": 1 if len(headers) > 0 else None,
                                    "indiv_name": None,
                                    "indiv_col": None,
                                    "members": []
                                }]
                                st.session_state[f"members_{default_gid}"] = []
                        st.toast(f"Loaded {loaded_file_label} ({detected_mode} Mode)", icon="📄")
                        st.rerun()

                    # Mode & Status Indicator
                    c_det_banner, c_det_toggle = st.columns([3, 1.2])
                    with c_det_banner:
                        if config.mode == detected_mode:
                            st.info(f"🤖 **Auto-detected:** `{detected_mode} Mode` ({detect_reason}) {gb('mode_detection')}")
                        else:
                            st.warning(f"⚠️ **Override Active:** Using **{config.mode} Mode** (detected as `{detected_mode}`) {gb('mode_detection')}")
                    with c_det_toggle:
                        other_mode = "LC" if config.mode == "PD" else "PD"
                        c_sw_btn, c_sw_gb = st.columns([4, 1])
                        with c_sw_btn:
                            if st.button(f"Switch to {other_mode}", use_container_width=True):
                                config.mode = other_mode
                                cfg = config.load_config()
                                cfg["mode"] = other_mode
                                config.save_config(cfg)
                                clear_group_gui_state()
                                st.rerun()
                        with c_sw_gb:
                            st.markdown(f"<div style='margin-top:6px;'>{gb('mode_override')}</div>", unsafe_allow_html=True)

                    # Message Header Banner
                    current_header = st.session_state.get("message_header_text", "")
                    if not current_header:
                        current_header = f"Feedback: {os.path.splitext(loaded_file_label)[0]}"
                        st.session_state["message_header_text"] = current_header

                    if "input_message_header" not in st.session_state:
                        st.session_state["input_message_header"] = current_header

                    st.markdown(f"**📝 Message Header Banner** {gb('message_header')}", unsafe_allow_html=True)
                    new_header = st.text_input(
                        "Message Header Banner",
                        key="input_message_header",
                        label_visibility="collapsed",
                        help="Appears at the very top of each member's Slack message"
                    )
                    if new_header != st.session_state.get("message_header_text"):
                        st.session_state["message_header_text"] = new_header
                        if st.session_state.get("full_messages"):
                            trigger_parse_comments(sheet)
                        st.rerun()

                    with st.expander("👀 View Sample Rows", expanded=False):
                        st.markdown(f"**Spreadsheet Inspector** {gb('sheet_preview')}", unsafe_allow_html=True)
                        rows_data = []
                        for r in range(1, min(sheet.max_row + 1, 5)):
                            row_vals = [sheet.cell(row=r, column=c).value for c in range(1, len(headers) + 1)]
                            rows_data.append(row_vals)
                        if rows_data:
                            df = pd.DataFrame(rows_data[1:], columns=rows_data[0])
                            st.dataframe(df, use_container_width=True)

                except Exception as e:
                    st.error(f"Error loading workbook: {e}")
            else:
                st.info("Select or upload an Excel spreadsheet above to begin.")

    # Step 1 Bottom Navigation
    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
    if "sheet" in st.session_state:
        target_step_title = "Review Groups" if config.mode == "PD" else "Review Columns"
        if st.session_state.get("guide_mode"):
            st.markdown(f"<div style='font-size:0.82rem; color:#6366f1; margin-bottom:4px;'>Proceed Action: {gb('parse_proceed_button')}</div>", unsafe_allow_html=True)
        if st.button(f"Continue to Step 2: {target_step_title} ➡️", type="primary", use_container_width=True):
            trigger_parse_comments(st.session_state["sheet"])
            go_to_step(2)
            st.rerun()
    else:
        st.info("👈 Please select or upload a spreadsheet above to begin.")


# =============================================================================
# STEP 2: REVIEW GROUPS & MEMBERS
# =============================================================================
elif active_step == 2:
    if "sheet" not in st.session_state:
        st.warning("Please upload or select a spreadsheet in Step 1 first.")
        if st.button("⬅️ Go to Step 1: Setup", use_container_width=True):
            go_to_step(1)
            st.rerun()
    else:
        sheet = st.session_state["sheet"]
        headers = st.session_state.get("headers", bot_logic.get_sheet_headers(sheet))
        all_known_members = sorted(list(st.session_state["name_dict"].keys()))

        if config.mode == "PD":
            st.markdown(f"### 👥 Step 2: Review Groups & Member Assignments {gb('groups_overview')}", unsafe_allow_html=True)
            st.caption("Assign members to each song/ensemble group to ensure everyone receives their feedback.")

            if not st.session_state["group_configs"]:
                paired, _, _ = bot_logic.detect_groups_pd(headers, config.group_search_list, config.indiv_search_list, config.exclude_search_list)
                if paired:
                    initial_configs = []
                    for i, p in enumerate(paired):
                        gid = f"grp_{i}_{int(time.time()*1000)}"
                        initial_configs.append({
                            "id": gid,
                            "group_name": p["group_name"],
                            "group_col": p["group_col"],
                            "indiv_name": p["indiv_name"],
                            "indiv_col": p["indiv_col"],
                            "members": []
                        })
                        st.session_state[f"members_{gid}"] = []
                    st.session_state["group_configs"] = initial_configs
                else:
                    # When groups haven't been detected yet, ensure exactly 1 group is visible
                    default_gid = f"grp_0_{int(time.time()*1000)}"
                    st.session_state["group_configs"] = [{
                        "id": default_gid,
                        "group_name": "Group 1",
                        "group_col": 1 if len(headers) > 0 else None,
                        "indiv_name": None,
                        "indiv_col": None,
                        "members": []
                    }]
                    st.session_state[f"members_{default_gid}"] = []

            # Automatically purge any non-performance/organizer feedback headers (e.g. Question/Comments for PDs/ADs)
            st.session_state["group_configs"] = [
                g for g in st.session_state["group_configs"]
                if not bot_logic.is_excluded_group_header(g.get("group_name", ""), exclude_terms=config.exclude_search_list)
            ]

            # If all groups were purged or empty, maintain 1 visible group
            if not st.session_state["group_configs"]:
                default_gid = f"grp_0_{int(time.time()*1000)}"
                st.session_state["group_configs"] = [{
                    "id": default_gid,
                    "group_name": "Group 1",
                    "group_col": 1 if len(headers) > 0 else None,
                    "indiv_name": None,
                    "indiv_col": None,
                    "members": []
                }]
                st.session_state[f"members_{default_gid}"] = []

            def cb_add_new_group(headers_len):
                new_group_num = len(st.session_state["group_configs"]) + 1
                first_col = 1 if headers_len > 0 else None
                new_gid = f"grp_{new_group_num}_{int(time.time()*1000)}"
                st.session_state["group_configs"].append({
                    "id": new_gid,
                    "group_name": f"Group {new_group_num}",
                    "group_col": first_col,
                    "indiv_name": None,
                    "indiv_col": None,
                    "members": []
                })
                st.session_state[f"members_{new_gid}"] = []

            def cb_auto_detect_all():
                sheet_obj = st.session_state.get("sheet")
                if not sheet_obj:
                    return
                all_known = sorted(list(st.session_state["name_dict"].keys()))
                for g in st.session_state.get("group_configs", []):
                    gid = g.get("id")
                    i_col = st.session_state.get(f"i_col_{gid}", g.get("indiv_col"))
                    g_nm = st.session_state.get(f"name_{gid}", g.get("group_name", ""))
                    detected = bot_logic.auto_detect_members_for_group(sheet_obj, i_col, all_known, group_name=g_nm)
                    g["members"] = detected
                    st.session_state[f"members_{gid}"] = detected
                st.session_state["has_assigned_names"] = True

            def cb_clear_all():
                for g in st.session_state.get("group_configs", []):
                    gid = g.get("id")
                    g["members"] = []
                    st.session_state[f"members_{gid}"] = []
                st.session_state["has_assigned_names"] = False

            def cb_detect_group(group_id):
                sheet_obj = st.session_state.get("sheet")
                if not sheet_obj:
                    return
                grp = next((g for g in st.session_state.get("group_configs", []) if g.get("id") == group_id), None)
                if not grp:
                    return
                i_col = st.session_state.get(f"i_col_{group_id}", grp.get("indiv_col"))
                g_nm = st.session_state.get(f"name_{group_id}", grp.get("group_name", ""))
                all_known = sorted(list(st.session_state["name_dict"].keys()))
                detected = bot_logic.auto_detect_members_for_group(sheet_obj, i_col, all_known, group_name=g_nm)
                st.session_state[f"members_{group_id}"] = detected
                grp["members"] = detected
                st.session_state["has_assigned_names"] = True

            def cb_clear_group(group_id):
                st.session_state[f"members_{group_id}"] = []
                for g in st.session_state.get("group_configs", []):
                    if g.get("id") == group_id:
                        g["members"] = []

            def cb_add_missing(group_id):
                sheet_obj = st.session_state.get("sheet")
                if not sheet_obj:
                    return
                grp = next((g for g in st.session_state.get("group_configs", []) if g.get("id") == group_id), None)
                if not grp:
                    return
                i_col = st.session_state.get(f"i_col_{group_id}", grp.get("indiv_col"))
                g_nm = st.session_state.get(f"name_{group_id}", grp.get("group_name", ""))
                all_known = sorted(list(st.session_state["name_dict"].keys()))
                mentioned = bot_logic.auto_detect_members_for_group(sheet_obj, i_col, all_known, group_name=g_nm)
                cur = list(st.session_state.get(f"members_{group_id}", grp.get("members", [])))
                updated = sorted(list(set(cur + mentioned)))
                st.session_state[f"members_{group_id}"] = updated
                grp["members"] = updated
                st.session_state["has_assigned_names"] = True

            def cb_remove_group(group_id):
                configs = st.session_state.get("group_configs", [])
                st.session_state["group_configs"] = [g for g in configs if g.get("id") != group_id]
                member_k = f"members_{group_id}"
                if member_k in st.session_state:
                    del st.session_state[member_k]
                # If all groups removed, ensure 1 group remains visible
                if not st.session_state["group_configs"]:
                    default_gid = f"grp_0_{int(time.time()*1000)}"
                    st.session_state["group_configs"] = [{
                        "id": default_gid,
                        "group_name": "Group 1",
                        "group_col": 1 if len(headers) > 0 else None,
                        "indiv_name": None,
                        "indiv_col": None,
                        "members": []
                    }]
                    st.session_state[f"members_{default_gid}"] = []

            def cb_on_members_change(group_id):
                new_m = list(st.session_state.get(f"members_{group_id}", []))
                for g in st.session_state.get("group_configs", []):
                    if g.get("id") == group_id:
                        g["members"] = new_m
                if new_m:
                    st.session_state["has_assigned_names"] = True
                for m in new_m:
                    clean = m.strip().lower()
                    if clean and clean not in st.session_state["name_dict"]:
                        st.session_state["name_dict"][clean] = ""

            member_group_map = defaultdict(list)
            for g in st.session_state["group_configs"]:
                gid = g.get("id")
                m_list = st.session_state.get(f"members_{gid}", g.get("members", []))
                for m in m_list:
                    member_group_map[m].append(g.get("group_name", "Group"))

            all_assigned_members = sorted(list(member_group_map.keys()))
            has_assigned_names = st.session_state.get("has_assigned_names", False) or len(all_assigned_members) > 0

            # Action bar: Add, Auto-detect, Clear, Reset, Matrix
            if st.session_state.get("guide_mode"):
                st.markdown(f"<div style='margin-bottom:4px; font-size:0.8rem; color:#6366f1;'><strong>Batch Controls:</strong> Add {gb('add_group')} | Auto-Detect {gb('auto_detect_all')} | Clear {gb('clear_group_names')} | Matrix {gb('membership_summary')}</div>", unsafe_allow_html=True)

            c_act1, c_act2, c_act3, c_act4 = st.columns([1.5, 2.2, 1.3, 1.5])
            with c_act1:
                st.button("➕ Add Group", on_click=cb_add_new_group, args=(len(headers),), use_container_width=True)
            with c_act2:
                st.button("🪄 Auto-Detect All", on_click=cb_auto_detect_all, use_container_width=True, help="Scans comments to populate members")
            with c_act3:
                st.button("🧹 Clear All", on_click=cb_clear_all, use_container_width=True)
            with c_act4:
                with st.popover("📋 Member Matrix", use_container_width=True):
                    st.markdown(f"###### Member Matrix Overview {gb('membership_summary')}", unsafe_allow_html=True)
                    if all_assigned_members:
                        summary_data = []
                        for m in all_assigned_members:
                            slack_id = st.session_state["name_dict"].get(m, "⚠️ Missing Slack ID")
                            groups_str = ", ".join(member_group_map[m])
                            summary_data.append({
                                "Member": m,
                                "Slack ID": slack_id,
                                "Groups": groups_str,
                                "Count": len(member_group_map[m])
                            })
                        st.dataframe(pd.DataFrame(summary_data), use_container_width=True)
                    else:
                        st.info("No members assigned yet.")

            # Summary metrics
            if st.session_state.get("guide_mode"):
                st.markdown(f"<div style='font-size:0.8rem; color:#6366f1; margin-bottom:4px;'><strong>Assignment Health Checks:</strong> {gb('unassigned_warnings')}</div>", unsafe_allow_html=True)

            c_sm1, c_sm2, c_sm3 = st.columns(3)
            c_sm1.metric("Total Groups", len(st.session_state["group_configs"]))
            c_sm2.metric("Members Assigned", len(all_assigned_members))
            unassigned_count = len([m for m in all_known_members if m not in all_assigned_members]) if has_assigned_names else 0
            c_sm3.metric("Unassigned in Directory", unassigned_count if has_assigned_names else "-", delta_color="inverse")

            # Missing members warnings
            if not has_assigned_names:
                st.info("💡 Groups are currently empty. Click **Auto-Detect All** above to scan feedback, or assign members manually in each card below.")
            else:
                unassigned_dir_members = [m for m in all_known_members if m not in all_assigned_members]
                if unassigned_dir_members:
                    st.warning(f"⚠️ **{len(unassigned_dir_members)} member(s) unassigned:** {', '.join([f'`{m}`' for m in unassigned_dir_members])}")

                all_sheet_mentions = set()
                for g in st.session_state["group_configs"]:
                    indiv_col = st.session_state.get(f"i_col_{g.get('id')}", g.get("indiv_col"))
                    grp_name = st.session_state.get(f"name_{g.get('id')}", g.get("group_name", ""))
                    if indiv_col or grp_name:
                        m_list = bot_logic.auto_detect_members_for_group(sheet, indiv_col, all_known_members, group_name=grp_name)
                        all_sheet_mentions.update(m_list)

                unassigned_sheet_mentions = sorted([m for m in all_sheet_mentions if m not in all_assigned_members])
                if unassigned_sheet_mentions:
                    st.error(f"🚨 **{len(unassigned_sheet_mentions)} member(s) have individual feedback but are NOT assigned to any group:** {', '.join([f'`{m}`' for m in unassigned_sheet_mentions])}")

                missing_slack = [m for m in all_assigned_members if not st.session_state["name_dict"].get(m)]
                if missing_slack:
                    st.error(f"❌ **{len(missing_slack)} assigned member(s) missing Slack User IDs:** {', '.join([f'`{m}`' for m in missing_slack])}")

            # Column option mapping
            col_options = {idx + 1: f"Col {idx + 1}: {h}" for idx, h in enumerate(headers) if h}
            col_options_with_none = {None: "(None)"}
            col_options_with_none.update(col_options)

            # Group Cards
            for idx, group_item in enumerate(st.session_state["group_configs"]):
                if "id" not in group_item:
                    group_item["id"] = f"grp_{idx}_{int(time.time()*1000)}"
                group_id = group_item["id"]
                member_key = f"members_{group_id}"

                if member_key not in st.session_state:
                    st.session_state[member_key] = list(group_item.get("members", []))

                current_m = list(st.session_state.get(member_key, group_item.get("members", [])))
                g_display_name = group_item.get("group_name", f"Group {idx + 1}")

                with st.container(border=True):
                    # Distinct Group Banner Header
                    member_count_str = f"👥 <strong>{len(current_m)}</strong> member{'s' if len(current_m) != 1 else ''} assigned"
                    guide_part = f" {gb('group_card')}" if gb('group_card') else ""
                    escaped_name = html.escape(str(g_display_name))
                    header_html = (
                        f'<div class="group-card-header">'
                        f'<div style="display: flex; align-items: center; gap: 8px;">'
                        f'<span class="group-badge-num">GROUP {idx + 1}</span>'
                        f'<span style="font-weight: 700; font-size: 1.05rem; color: #f8fafc;">{escaped_name}</span>'
                        f'{guide_part}'
                        f'</div>'
                        f'<div class="group-member-count">{member_count_str}</div>'
                        f'</div>'
                    )
                    st.markdown(header_html, unsafe_allow_html=True)

                    c_title, c_del = st.columns([5, 1])
                    with c_title:
                        group_item["group_name"] = st.text_input(
                            f"Group {idx + 1} Name",
                            value=group_item.get("group_name", f"Group {idx + 1}"),
                            key=f"name_{group_id}",
                            label_visibility="collapsed",
                            help="Rename this group or ensemble"
                        )
                    with c_del:
                        st.button(
                            "🗑️ Remove Group",
                            key=f"del_group_{group_id}",
                            on_click=cb_remove_group,
                            args=(group_id,),
                            use_container_width=True
                        )

                    c_g1, c_g2 = st.columns(2)
                    with c_g1:
                        st.markdown(f"**Group Feedback Column** {gb('group_col_select')}", unsafe_allow_html=True)
                        current_g_col = group_item.get("group_col")
                        g_keys = list(col_options_with_none.keys())
                        g_idx = g_keys.index(current_g_col) if current_g_col in g_keys else 0
                        selected_g_col = st.selectbox(
                            f"Group Feedback Column",
                            options=g_keys,
                            format_func=lambda x: col_options_with_none.get(x, f"Col {x}"),
                            index=g_idx,
                            key=f"g_col_{group_id}",
                            label_visibility="collapsed"
                        )
                        group_item["group_col"] = selected_g_col

                    with c_g2:
                        st.markdown(f"**Individual Feedback Column** {gb('indiv_col_select')}", unsafe_allow_html=True)
                        current_i_col = group_item.get("indiv_col")
                        i_keys = list(col_options_with_none.keys())
                        i_idx = i_keys.index(current_i_col) if current_i_col in i_keys else 0
                        selected_i_col = st.selectbox(
                            f"Individual Feedback Column",
                            options=i_keys,
                            format_func=lambda x: col_options_with_none.get(x, str(x)),
                            index=i_idx,
                            key=f"i_col_{group_id}",
                            label_visibility="collapsed"
                        )
                        group_item["indiv_col"] = selected_i_col
                        group_item["indiv_name"] = headers[selected_i_col - 1] if selected_i_col else None

                    all_opts = sorted(list(set(all_known_members + current_m)))

                    c_m_hdr, c_m_det, c_m_clr = st.columns([4, 1.2, 1])
                    with c_m_hdr:
                        st.markdown(f"<div style='font-size:0.88rem; font-weight:600; margin-top:4px;'>Assigned Members ({len(current_m)}) {gb('member_multiselect')} {gb('detect_single_group')}</div>", unsafe_allow_html=True)
                    with c_m_det:
                        st.button("🪄 Detect", key=f"btn_detect_{group_id}", on_click=cb_detect_group, args=(group_id,), use_container_width=True, help="Auto-detect members from comments for this group")
                    with c_m_clr:
                        st.button("🧹 Clear", key=f"btn_clr_{group_id}", on_click=cb_clear_group, args=(group_id,), use_container_width=True)

                    st.multiselect(
                        f"Members in {group_item['group_name']}",
                        options=all_opts,
                        key=member_key,
                        on_change=cb_on_members_change,
                        args=(group_id,),
                        accept_new_options=True,
                        placeholder="Search/select members or type a new name and press Enter...",
                        label_visibility="collapsed"
                    )
                    group_item["members"] = st.session_state.get(member_key, [])

                    if has_assigned_names and (selected_i_col or group_item.get("group_name")):
                        mentioned_for_group = bot_logic.auto_detect_members_for_group(
                            sheet, selected_i_col, all_known_members, group_name=group_item.get("group_name", "")
                        )
                        missing_from_group = [m for m in mentioned_for_group if m not in current_m]
                        if missing_from_group:
                            c_w_txt, c_w_btn = st.columns([4, 1.4])
                            with c_w_txt:
                                names_str = ", ".join([f"`{m}`" for m in missing_from_group])
                                st.warning(f"⚠️ Mentioned in feedback but missing: {names_str}")
                            with c_w_btn:
                                st.button(
                                    f"➕ Add Missing ({len(missing_from_group)})",
                                    key=f"add_miss_{group_id}",
                                    on_click=cb_add_missing,
                                    args=(group_id,),
                                    use_container_width=True
                                )

                st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)

            # Step 2 Bottom Navigation
            st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)
            if st.session_state.get("guide_mode"):
                st.markdown(f"<div style='font-size:0.82rem; color:#6366f1; margin-bottom:4px;'>Generate Feedback Action: {gb('generate_comments_btn')}</div>", unsafe_allow_html=True)

            c_back, c_next = st.columns([1, 2])
            with c_back:
                if st.button("⬅️ Back to Step 1: Setup", use_container_width=True):
                    go_to_step(1)
                    st.rerun()
            with c_next:
                if st.button("Continue to Step 3: Review Comments ➡️", type="primary", use_container_width=True):
                    trigger_parse_comments(sheet)
                    go_to_step(3)
                    st.rerun()

        elif config.mode == "LC":
            st.markdown(f"### 📋 Step 2: Review Member Columns (LC Mode) {gb('lc_overview')}", unsafe_allow_html=True)
            st.caption("In LC mode, columns in the spreadsheet are mapped directly to member names.")

            matched_columns = []
            for col_idx, h in enumerate(headers, 1):
                if h.lower().strip() in all_known_members:
                    matched_columns.append({"Column": f"Col {col_idx}", "Header": h, "Matched Member": h.lower().strip()})

            if matched_columns:
                st.success(f"Found {len(matched_columns)} columns matching member names.")
                st.dataframe(pd.DataFrame(matched_columns), use_container_width=True)

                matched_members_set = {col["Matched Member"] for col in matched_columns}
                unmatched_lc = [m for m in all_known_members if m not in matched_members_set]
                if unmatched_lc:
                    st.warning(f"⚠️ **{len(unmatched_lc)} member(s) in `name_list.json` without a feedback column:** {', '.join([f'`{m}`' for m in unmatched_lc])}")
            else:
                st.warning("No columns in this spreadsheet directly match member names in name_list.json.")

            st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)
            if st.session_state.get("guide_mode"):
                st.markdown(f"<div style='font-size:0.82rem; color:#6366f1; margin-bottom:4px;'>Generate Feedback Action: {gb('generate_comments_btn')}</div>", unsafe_allow_html=True)

            c_back, c_next = st.columns([1, 2])
            with c_back:
                if st.button("⬅️ Back to Step 1: Setup", use_container_width=True):
                    go_to_step(1)
                    st.rerun()
            with c_next:
                if st.button("Continue to Step 3: Review Comments ➡️", type="primary", use_container_width=True):
                    trigger_parse_comments(sheet)
                    go_to_step(3)
                    st.rerun()


# =============================================================================
# STEP 3: REVIEW SAMPLE COMMENTS
# =============================================================================
elif active_step == 3:
    st.markdown(f"### 💬 Step 3: Review Sample Comments {gb('comments_overview')}", unsafe_allow_html=True)
    st.caption("Inspect the exact formatted Slack messages generated for each member before sending.")

    mode_changed = st.session_state.get("last_parsed_mode") != config.mode
    if (not st.session_state.get("full_messages") or mode_changed) and "sheet" in st.session_state:
        trigger_parse_comments(st.session_state["sheet"])

    full_msgs = st.session_state.get("full_messages", {})
    if not full_msgs:
        st.warning("No comments generated yet. Please configure groups in Step 2 first.")
        if st.button("⬅️ Go to Step 2", use_container_width=True):
            go_to_step(2)
            st.rerun()
    else:
        recipients = sorted(list(full_msgs.keys()))
        total_recipients = len(recipients)
        missing_ids = [r for r in recipients if not st.session_state["name_dict"].get(r)]

        # Compact metric row
        if st.session_state.get("guide_mode"):
            st.markdown(f"<div style='font-size:0.8rem; color:#6366f1; margin-bottom:4px;'>Recipient Coverage Metrics: {gb('recipient_metrics')}</div>", unsafe_allow_html=True)

        c_m1, c_m2, c_m3 = st.columns(3)
        c_m1.metric("Total Recipients", total_recipients)
        c_m2.metric("Slack IDs Configured", f"{total_recipients - len(missing_ids)} / {total_recipients}")
        c_m3.metric("Missing Slack IDs", len(missing_ids), delta_color="inverse")

        if missing_ids:
            st.warning(f"⚠️ {len(missing_ids)} member(s) have feedback but no Slack ID in name_list.json: {', '.join(missing_ids)}.")

        col_sel, col_rand = st.columns([3, 1])
        with col_sel:
            st.markdown(f"**Select Member to Preview** {gb('recipient_selector')}", unsafe_allow_html=True)
            selected_person = st.selectbox(
                "Select Member to Preview",
                options=recipients,
                index=st.session_state["selected_recipient_idx"] if st.session_state["selected_recipient_idx"] < len(recipients) else 0,
                label_visibility="collapsed"
            )
            st.session_state["selected_recipient_idx"] = recipients.index(selected_person)
        with col_rand:
            st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
            if st.button("🎲 Random Sample", use_container_width=True):
                rand_idx = random.randint(0, len(recipients) - 1)
                st.session_state["selected_recipient_idx"] = rand_idx
                st.rerun()

        slack_id = st.session_state["name_dict"].get(selected_person)
        msg_text = full_msgs[selected_person]

        # Tabbed preview: Clean Slack DM vs Raw Markdown vs Section Breakdown
        tab_dm, tab_raw, tab_sec = st.tabs(["📱 Slack DM Preview", "📝 Raw Payload", "🔍 Section Breakdown"])
        with tab_dm:
            st.markdown(f"##### 📱 Simulated Slack DM {gb('slack_dm_preview')}", unsafe_allow_html=True)
            slack_html = bot_logic.render_slack_dm_html("ST SlackBot", selected_person, slack_id, msg_text, theme="dark")
            st.markdown(slack_html, unsafe_allow_html=True)
        with tab_raw:
            st.markdown(f"##### 📝 Raw API Payload {gb('raw_markdown')}", unsafe_allow_html=True)
            st.text_area("Payload", value=msg_text, height=350, disabled=True, label_visibility="collapsed")
        with tab_sec:
            st.markdown(f"##### 🔍 Section-by-Section Breakdown {gb('section_breakdown')}", unsafe_allow_html=True)
            st.caption(f"Inspection of parsed feedback sections for **@{selected_person}**:")
            sections = [s.strip() for s in msg_text.split("───") if s.strip()]
            if sections:
                for sec in sections:
                    with st.container(border=True):
                        st.text(sec)
            else:
                st.info("No section dividers detected in payload.")

        with st.expander(f"📋 Audit All {len(recipients)} Recipients", expanded=False):
            st.markdown(f"**Batch Audit Verification** {gb('audit_all')}", unsafe_allow_html=True)
            search_query = st.text_input("Filter members:", placeholder="Type to filter...")
            filtered_recipients = [r for r in recipients if search_query.lower() in r.lower()] if search_query else recipients
            for r in filtered_recipients:
                r_slack = st.session_state["name_dict"].get(r, "Missing ID")
                st.markdown(f"**@{r}** (`{r_slack}`)")
                st.text_area(f"msg_{r}", value=full_msgs[r], height=100, disabled=True, label_visibility="collapsed")

        # Step 3 Bottom Navigation
        st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)
        c_back, c_next = st.columns([1, 2])
        with c_back:
            if st.button("⬅️ Back to Step 2: Groups", use_container_width=True):
                go_to_step(2)
                st.rerun()
        with c_next:
            if st.button("Continue to Step 4: Send Messages ➡️", type="primary", use_container_width=True):
                go_to_step(4)
                st.rerun()


# =============================================================================
# STEP 4: SEND COMMENTS TO SLACK
# =============================================================================
elif active_step == 4:
    st.markdown(f"### 🚀 Step 4: Send Comments to Slack {gb('send_overview')}", unsafe_allow_html=True)
    st.caption("Verify the recipient checklist and dispatch feedback messages directly to members.")

    full_msgs = st.session_state.get("full_messages", {})
    if not full_msgs:
        st.warning("No comments ready to send. Please configure groups in Step 2 first.")
        if st.button("⬅️ Go to Step 2", use_container_width=True):
            go_to_step(2)
            st.rerun()
    else:
        recipients = sorted(list(full_msgs.keys()))

        # 1. Recipient Checklist
        st.markdown(f"##### 1. Recipient Checklist {gb('recipient_checklist')}", unsafe_allow_html=True)
        select_all = st.checkbox("Select All Recipients", value=True)

        recipient_status = []
        for r in recipients:
            sid = st.session_state["name_dict"].get(r, "")
            status = "Ready ✅" if sid else "Missing Slack ID ❌"
            recipient_status.append({
                "Send": select_all and bool(sid),
                "Member": r,
                "Slack ID": sid or "MISSING",
                "Status": status,
                "Char Count": len(full_msgs[r])
            })

        df_recipients = pd.DataFrame(recipient_status)
        edited_recipients = st.data_editor(
            df_recipients,
            column_config={
                "Send": st.column_config.CheckboxColumn("Send?", default=True),
                "Member": st.column_config.TextColumn("Member", disabled=True),
                "Slack ID": st.column_config.TextColumn("Slack User ID", disabled=True),
                "Status": st.column_config.TextColumn("Status", disabled=True),
                "Char Count": st.column_config.NumberColumn("Length", disabled=True)
            },
            hide_index=True,
            use_container_width=True
        )

        selected_rows = edited_recipients[edited_recipients["Send"] == True]
        confirmed_recipients = selected_rows["Member"].tolist()
        st.caption(f"**{len(confirmed_recipients)}** of **{len(recipients)}** recipients selected for delivery.")

        # 2. Test Message
        st.markdown("---")
        with st.expander("🧪 Optional: Send a Test Message First", expanded=False):
            st.markdown(f"**Deliver Test DM** {gb('test_send')}", unsafe_allow_html=True)
            st.caption("Deliver a sample message to your own Slack ID or test channel to verify formatting.")
            with st.form("test_send_form"):
                t_col_user, t_col_target, t_col_btn = st.columns([2, 3, 2])
                with t_col_user:
                    sample_target = st.selectbox("Sample Payload:", options=recipients, index=0)
                with t_col_target:
                    test_slack_id = st.text_input("Your Slack ID or Channel ID:", value=st.session_state.get("last_test_slack_id", ""), placeholder="e.g. U0XXXXXXXXX")
                with t_col_btn:
                    st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
                    send_test_btn = st.form_submit_button("Send Test DM", type="secondary", use_container_width=True)

                if send_test_btn:
                    clean_target = test_slack_id.strip()
                    if not clean_target:
                        st.error("Please enter a Slack User ID or test channel ID.")
                    else:
                        st.session_state["last_test_slack_id"] = clean_target
                        sample_msg = full_msgs[sample_target]
                        with st.spinner(f"Sending test for @{sample_target}..."):
                            active_tok = get_active_token()
                            ok, res = bot_logic.send_slack_message(active_tok, config.slack_api_url, clean_target, sample_msg)
                            if ok:
                                st.success(f"✅ Test message delivered to **`{clean_target}`**!")
                            else:
                                st.error(f"Failed: {res}")

        # 3. Final Broadcast
        st.markdown("---")
        st.markdown(f"##### 2. Final Dispatch {gb('broadcast_confirmation')}", unsafe_allow_html=True)
        confirm_checkbox = st.checkbox(
            f"I confirm sending messages to all {len(confirmed_recipients)} selected members.",
            value=False
        )

        if st.session_state.get("guide_mode"):
            st.markdown(f"<div style='font-size:0.82rem; color:#6366f1; margin-bottom:4px;'>Final Dispatch Action: {gb('broadcast_button')}</div>", unsafe_allow_html=True)

        if st.button(
            f"🚀 Send Slack Messages to {len(confirmed_recipients)} Members",
            type="primary",
            disabled=not confirm_checkbox or len(confirmed_recipients) == 0,
            use_container_width=True
        ):
            progress_bar = st.progress(0)
            status_text = st.empty()
            log_container = st.container()

            success_count = 0
            fail_count = 0
            active_tok = get_active_token()

            with log_container:
                for idx, person in enumerate(confirmed_recipients):
                    slack_id = st.session_state["name_dict"].get(person)
                    msg_body = full_msgs[person]

                    status_text.text(f"Sending ({idx + 1}/{len(confirmed_recipients)}): @{person}...")

                    if not slack_id:
                        st.write(f"❌ **@{person}**: Skipped - missing Slack ID")
                        fail_count += 1
                        continue

                    ok, res = bot_logic.send_slack_message(active_tok, config.slack_api_url, slack_id, msg_body)
                    if ok:
                        st.write(f"✅ **@{person}** (`{slack_id}`): Delivered")
                        success_count += 1
                    else:
                        st.write(f"❌ **@{person}** (`{slack_id}`): Failed - {res}")
                        fail_count += 1

                    progress_bar.progress((idx + 1) / len(confirmed_recipients))

            status_text.text("Finished!")
            if success_count > 0 and fail_count == 0:
                st.success(f"🎉 Successfully delivered feedback to all {success_count} members!")
            else:
                st.warning(f"Completed: {success_count} succeeded, {fail_count} failed.")

        # Step 4 Bottom Navigation
        st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)
        if st.button("⬅️ Back to Step 3: Review Comments", use_container_width=True):
            go_to_step(3)
            st.rerun()
