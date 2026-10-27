import os
import json
from pathlib import Path
from dotenv import load_dotenv

try:
    import tomllib
except ImportError:
    tomllib = None

CONFIG_FILE = './config.json'
SECRETS_FILE = './.streamlit/secrets.toml'
ENV_FILE = './token.env'

# Global configuration variables
slack_token = ""
slack_api_url = "https://slack.com/api/"
name_filepath = "name_list.json"
form_filepath = ""
search_list = ["Group", "Ensemble", "Arashi", "Three Sizz", "Individual"]
mode = "PD"
spreadsheet_folder = "spreadsheets"
form_file = ""


def get_token_from_secrets():
    """Retrieve token from Streamlit secrets (st.secrets or .streamlit/secrets.toml)."""
    # 1. Try accessing via streamlit.secrets if streamlit is running
    try:
        import streamlit as st
        if hasattr(st, "secrets") and "SLACK_BOT_TOKEN" in st.secrets:
            token = st.secrets["SLACK_BOT_TOKEN"]
            if token and str(token).strip():
                return str(token).strip()
    except Exception:
        pass

    # 2. Try parsing .streamlit/secrets.toml directly
    if os.path.exists(SECRETS_FILE) and tomllib:
        try:
            with open(SECRETS_FILE, "rb") as f:
                secrets_data = tomllib.load(f)
                token = secrets_data.get("SLACK_BOT_TOKEN")
                if token and str(token).strip():
                    return str(token).strip()
        except Exception:
            pass

    # 3. Fallback to environment variables / token.env
    if os.path.exists(ENV_FILE):
        load_dotenv(dotenv_path=Path(ENV_FILE), override=True)

    return os.getenv("SLACK_BOT_TOKEN") or os.getenv("SLACK_API_TOKEN") or ""


def load_config(config_file=CONFIG_FILE):
    """Load configuration from config.json and Streamlit secrets."""
    global slack_token, slack_api_url, name_filepath, form_filepath, search_list, mode, spreadsheet_folder, form_file

    config = {}
    if os.path.exists(config_file):
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)

    slack_api_url = config.get('slack', {}).get('api_url', 'https://slack.com/api/')
    name_filepath = config.get('file', {}).get('name_list', 'name_list.json')
    spreadsheet_folder = config.get('file', {}).get('spreadsheet_folder', 'spreadsheets')
    form_file = config.get('file', {}).get('form_file', '')
    form_filepath = os.path.join(spreadsheet_folder, form_file) if form_file else ""
    search_list = config.get('search', {}).get('terms', ["Group", "Ensemble", "Arashi", "Three Sizz", "Individual"])
    mode = config.get('mode', 'PD')

    slack_token = get_token_from_secrets() or config.get('slack', {}).get('token', '')

    return config


def save_config(config_dict, config_file=CONFIG_FILE):
    """Save configuration dictionary to config.json and reload in-memory variables.
    Returns (config_dict, saved_to_disk: bool).
    """
    global slack_api_url, name_filepath, spreadsheet_folder, form_file, form_filepath, search_list, mode
    saved_to_disk = False
    try:
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config_dict, f, indent=2)
        saved_to_disk = True
    except OSError:
        saved_to_disk = False

    slack_api_url = config_dict.get('slack', {}).get('api_url', slack_api_url)
    name_filepath = config_dict.get('file', {}).get('name_list', name_filepath)
    spreadsheet_folder = config_dict.get('file', {}).get('spreadsheet_folder', spreadsheet_folder)
    form_file = config_dict.get('file', {}).get('form_file', form_file)
    form_filepath = os.path.join(spreadsheet_folder, form_file) if form_file else ""
    search_list = config_dict.get('search', {}).get('terms', search_list)
    mode = config_dict.get('mode', mode)

    return config_dict, saved_to_disk


def save_token(token, secrets_file=SECRETS_FILE):
    """Save the Slack Bot Token to .streamlit/secrets.toml and reload in-memory variable.
    Returns (clean_token, saved_to_disk: bool).
    """
    clean_token = token.strip()
    global slack_token
    slack_token = clean_token

    saved_to_disk = False
    try:
        os.makedirs(os.path.dirname(secrets_file), exist_ok=True)
        with open(secrets_file, 'w', encoding='utf-8') as f:
            f.write(f'SLACK_BOT_TOKEN = "{clean_token}"\n')

        # Also keep token.env in sync if it exists and is writable
        if os.path.exists(ENV_FILE):
            try:
                with open(ENV_FILE, 'w', encoding='utf-8') as f:
                    f.write(f"SLACK_BOT_TOKEN={clean_token}\n")
            except OSError:
                pass
        saved_to_disk = True
    except OSError:
        saved_to_disk = False

    return slack_token, saved_to_disk


# Initial load upon import
load_config()
