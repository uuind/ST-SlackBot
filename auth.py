import streamlit as st

DEFAULT_ACCOUNTS = {
    "admin": "taiko"
}


def get_registered_users() -> dict[str, str]:
    """
    Retrieve configured username -> password mappings from Streamlit secrets.
    Supports:
      1. Simple mapping:
         [users]
         admin = "password123"
         audrey = "mypassword"
      2. Table mapping:
         [users.admin]
         password = "password123"
      3. Fallback:
         If only single PASSWORD = "..." exists in secrets, registers under 'admin'.
    """
    accounts = {}
    try:
        if hasattr(st, "secrets"):
            if "users" in st.secrets:
                users_sec = st.secrets["users"]
                for username, val in users_sec.items():
                    u_clean = str(username).strip().lower()
                    if isinstance(val, dict) or hasattr(val, "items"):
                        p_val = val.get("password") or val.get("pass") or ""
                        accounts[u_clean] = str(p_val).strip()
                    else:
                        accounts[u_clean] = str(val).strip()

            if not accounts:
                if "PASSWORD" in st.secrets:
                    accounts["admin"] = str(st.secrets["PASSWORD"]).strip()
                elif "APP_PASSWORD" in st.secrets:
                    accounts["admin"] = str(st.secrets["APP_PASSWORD"]).strip()
    except Exception:
        pass

    if not accounts:
        accounts = dict(DEFAULT_ACCOUNTS)

    return accounts


def verify_credentials(username: str, password: str) -> tuple[bool, str]:
    """
    Verify if the entered username and password match an authorized account.
    Returns (is_valid: bool, error_message: str).
    """
    if not username or not username.strip():
        return False, "Please enter your username."
    if not password:
        return False, "Please enter your password."

    clean_user = username.strip().lower()
    clean_pass = password.strip()

    accounts = get_registered_users()

    if clean_user not in accounts:
        return False, "Invalid username or password."

    expected_pass = accounts[clean_user]
    if clean_pass != expected_pass:
        return False, "Invalid username or password."

    return True, ""
