"""
auth_manager.py - Authentication manager for PharmaCast.

Handles:
  - Google OAuth 2.0 sign-in (direct HTTP — no PKCE, no library quirks)
  - Email/password login with invite-code activation
  - Session management via Streamlit session state
  - Graceful fallback: if OAuth is not configured, auth is bypassed

Environment variables (required for Google OAuth):
  GOOGLE_CLIENT_ID      - OAuth 2.0 client ID from GCP console
  GOOGLE_CLIENT_SECRET  - OAuth 2.0 client secret
  OAUTH_REDIRECT_URI    - Redirect URI (defaults to http://localhost:8501)
"""

import os
import urllib.parse
import streamlit as st

from user_db import (
    get_user, is_authorized, is_admin,
    verify_invite, complete_invite, hash_password, verify_password,
)

# Google OAuth endpoints
_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_SCOPES = "openid email profile"


def is_auth_configured():
    """Check if Google OAuth credentials are set."""
    return bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"))


def require_auth():
    """Gate function. Returns user info dict if authenticated, shows login and stops otherwise.

    If OAuth is not configured (no env vars), returns None to indicate demo/bypass mode.
    """
    if not is_auth_configured():
        return None

    # Already authenticated this session
    if st.session_state.get("authenticated"):
        return st.session_state["user_info"]

    # Check for OAuth callback (Google redirected back with ?code=...)
    params = st.query_params
    if "code" in params:
        _handle_oauth_callback(params.get("code"))
        # If callback succeeded, rerun already happened.
        # If it failed, fall through to login page.

    _show_login_page()
    st.stop()


def logout():
    """Clear auth session and rerun."""
    for key in ["authenticated", "user_info"]:
        st.session_state.pop(key, None)
    st.rerun()


# =============================================================================
# Google OAuth flow (direct HTTP — no google-auth-oauthlib, no PKCE)
# =============================================================================

def _get_redirect_uri():
    return os.environ.get("OAUTH_REDIRECT_URI", "http://localhost:8501")


def _get_google_auth_url():
    """Build Google OAuth authorization URL manually. No PKCE, no library."""
    params = {
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "redirect_uri": _get_redirect_uri(),
        "response_type": "code",
        "scope": _GOOGLE_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{_GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"


def _handle_oauth_callback(code):
    """Exchange authorization code for tokens using direct HTTP POST."""
    import json
    import urllib.request

    try:
        # Exchange code for tokens
        token_data = urllib.parse.urlencode({
            "code": code,
            "client_id": os.environ["GOOGLE_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            "redirect_uri": _get_redirect_uri(),
            "grant_type": "authorization_code",
        }).encode()

        req = urllib.request.Request(
            _GOOGLE_TOKEN_URL,
            data=token_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req) as resp:
            token_response = json.loads(resp.read().decode())

        id_token_jwt = token_response.get("id_token")
        if not id_token_jwt:
            st.session_state["auth_error"] = "No ID token in response from Google."
            st.query_params.clear()
            return

        # Verify and decode the ID token
        from google.oauth2 import id_token
        from google.auth.transport import requests as google_requests

        id_info = id_token.verify_oauth2_token(
            id_token_jwt,
            google_requests.Request(),
            os.environ["GOOGLE_CLIENT_ID"],
        )

        email = id_info["email"]
        name = id_info.get("name", "")

        if is_authorized(email):
            user = get_user(email)
            st.session_state["authenticated"] = True
            st.session_state["user_info"] = {
                "email": email,
                "name": name,
                "role": user["role"],
                "picture": id_info.get("picture", ""),
            }
            st.query_params.clear()
            st.rerun()
        else:
            st.session_state["auth_error"] = (
                f"**{email}** does not have access. "
                "Please request access from the administrator."
            )
            st.query_params.clear()

    except Exception as e:
        st.session_state["auth_error"] = f"Authentication failed: {e}"
        st.query_params.clear()


# =============================================================================
# Login page UI
# =============================================================================

def _show_login_page():
    """Render the login page with Google, email, and invite-code tabs."""

    # Center the form
    _, col, _ = st.columns([1, 2, 1])

    with col:
        st.markdown(
            """
            <div style="text-align: center; padding: 2rem 0 1rem 0;">
                <h1>💊 PharmaCast</h1>
                <p style="color: #666; font-size: 1.1rem;">Intelligent Inventory Management</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Show auth error if any
        if "auth_error" in st.session_state:
            st.error(st.session_state.pop("auth_error"))

        tab1, tab2, tab3 = st.tabs(["🔵 Google Sign-In", "📧 Email Login", "🔑 Activate Account"])

        # ---- Tab 1: Google OAuth ----
        with tab1:
            st.markdown("Sign in with your Google account. Only authorized accounts can access the dashboard.")
            try:
                auth_url = _get_google_auth_url()
                st.markdown(
                    f"""
                    <a href="{auth_url}" target="_self" style="text-decoration: none;">
                        <div style="display: flex; align-items: center; justify-content: center;
                                    background-color: #4285F4; color: white; padding: 12px 24px;
                                    border-radius: 4px; font-size: 16px; font-weight: 500;
                                    cursor: pointer; margin: 20px auto; max-width: 300px;">
                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" width="24" height="24" style="margin-right: 12px;">
                                <path fill="#fff" d="M44.5 20H24v8.5h11.8C34.7 33.9 30.1 37 24 37c-7.2 0-13-5.8-13-13s5.8-13 13-13c3.1 0 5.9 1.1 8.1 2.9l6.4-6.4C34.6 4.1 29.6 2 24 2 11.8 2 2 11.8 2 24s9.8 22 22 22c11 0 21-8 21-22 0-1.3-.2-2.7-.5-4z"/>
                            </svg>
                            Sign in with Google
                        </div>
                    </a>
                    """,
                    unsafe_allow_html=True,
                )
            except Exception as e:
                st.error(f"OAuth configuration error: {e}")

            st.info("Don't have access? Contact the administrator to get authorized.")

        # ---- Tab 2: Email/Password ----
        with tab2:
            st.markdown("Sign in with your email and password.")
            with st.form("email_login_form"):
                email = st.text_input("Email")
                password = st.text_input("Password", type="password")
                submitted = st.form_submit_button("Sign In", use_container_width=True)

            if submitted:
                if not email or not password:
                    st.error("Email and password are required.")
                else:
                    user = get_user(email)
                    if user and "email" in user.get("auth_types", []) and user.get("password_hash"):
                        if verify_password(password, user["password_hash"]):
                            st.session_state["authenticated"] = True
                            st.session_state["user_info"] = {
                                "email": email,
                                "name": user.get("name", ""),
                                "role": user["role"],
                                "picture": "",
                            }
                            st.rerun()
                        else:
                            st.error("Invalid password.")
                    else:
                        st.error("Account not found or not set up for email login.")

        # ---- Tab 3: Activate with invite code ----
        with tab3:
            st.markdown("If an admin has given you an invite code, enter it below to set up your account.")
            with st.form("activate_form"):
                act_email = st.text_input("Email")
                act_code = st.text_input("Invite Code")
                act_name = st.text_input("Your Name")
                act_password = st.text_input("Set Password", type="password")
                act_confirm = st.text_input("Confirm Password", type="password")
                act_submitted = st.form_submit_button("Activate Account", use_container_width=True)

            if act_submitted:
                if not all([act_email, act_code, act_password, act_confirm]):
                    st.error("All fields are required.")
                elif act_password != act_confirm:
                    st.error("Passwords don't match.")
                elif len(act_password) < 8:
                    st.error("Password must be at least 8 characters.")
                else:
                    invite = verify_invite(act_email, act_code)
                    if invite:
                        complete_invite(act_email, act_code, hash_password(act_password), name=act_name)
                        st.success("Account activated! Switch to the **Email Login** tab to sign in.")
                    else:
                        st.error("Invalid invite code for this email address.")
