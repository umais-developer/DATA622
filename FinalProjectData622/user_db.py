"""
user_db.py - JSON-backed user database for PharmaCast authentication.

Stores authorized users, roles, invite codes, and hashed passwords.
The database file (users.json) is synced to GCS alongside other data.
"""

import json
import os
import hashlib
import secrets
from datetime import datetime

from config import DATA_DIR

USERS_FILE = os.path.join(DATA_DIR, "users.json")
DEFAULT_ADMIN = "umaisabdullah@gmail.com"


def _load_db():
    """Load user database from disk, initializing if needed."""
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE) as f:
            return json.load(f)
    return _init_db()


def _save_db(db):
    """Persist user database to disk."""
    os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)
    with open(USERS_FILE, "w") as f:
        json.dump(db, f, indent=2)


def _init_db():
    """Create initial database with super admin."""
    db = {
        "users": {
            DEFAULT_ADMIN: {
                "role": "admin",
                "auth_types": ["google"],
                "status": "active",
                "name": "Umais Abdullah",
                "created": datetime.now().isoformat(),
            }
        },
        "pending_invites": {},
    }
    _save_db(db)
    return db


# ---- User lookups ----

def get_user(email):
    """Get user record by email, or None."""
    db = _load_db()
    return db["users"].get(email)


def is_authorized(email):
    """Check if email has active access."""
    user = get_user(email)
    return user is not None and user.get("status") == "active"


def is_admin(email):
    """Check if email is an admin."""
    user = get_user(email)
    return user is not None and user.get("role") == "admin"


def list_users():
    """Return dict of all registered users."""
    db = _load_db()
    return db["users"]


# ---- User management ----

def add_user(email, role="viewer", auth_types=None, name=""):
    """Add or update a user with Google access."""
    db = _load_db()
    db["users"][email] = {
        "role": role,
        "auth_types": auth_types or ["google"],
        "status": "active",
        "name": name,
        "created": datetime.now().isoformat(),
    }
    _save_db(db)


def remove_user(email):
    """Remove a user. Cannot remove the super admin."""
    if email == DEFAULT_ADMIN:
        return False
    db = _load_db()
    db["users"].pop(email, None)
    # Also clean up any pending invite
    db["pending_invites"].pop(email, None)
    _save_db(db)
    return True


def update_user_role(email, role):
    """Change a user's role. Cannot demote the super admin."""
    if email == DEFAULT_ADMIN:
        return False
    db = _load_db()
    if email in db["users"]:
        db["users"][email]["role"] = role
        _save_db(db)
        return True
    return False


# ---- Invite codes (for email/password users) ----

def create_invite(email, role="viewer"):
    """Generate an invite code for an email address. Returns the code."""
    db = _load_db()
    code = secrets.token_urlsafe(6)  # Short, readable code (8 chars)
    db["pending_invites"][email] = {
        "code": code,
        "role": role,
        "created": datetime.now().isoformat(),
    }
    _save_db(db)
    return code


def verify_invite(email, code):
    """Check if an invite code is valid. Returns invite dict or None."""
    db = _load_db()
    invite = db["pending_invites"].get(email)
    if invite and invite["code"] == code:
        return invite
    return None


def complete_invite(email, code, password_hash, name=""):
    """Activate an account using an invite code. Returns True on success."""
    db = _load_db()
    invite = db["pending_invites"].get(email)
    if not invite or invite["code"] != code:
        return False
    db["users"][email] = {
        "role": invite["role"],
        "auth_types": ["email"],
        "status": "active",
        "name": name,
        "password_hash": password_hash,
        "created": datetime.now().isoformat(),
    }
    del db["pending_invites"][email]
    _save_db(db)
    return True


def get_pending_invites():
    """Return dict of pending invites."""
    db = _load_db()
    return db.get("pending_invites", {})


# ---- Password hashing ----

def hash_password(password):
    """Hash a password with a random salt using SHA-256."""
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}:{hashed}"


def verify_password(password, stored_hash):
    """Verify a password against a stored hash."""
    try:
        salt, hashed = stored_hash.split(":")
        return hashlib.sha256((salt + password).encode()).hexdigest() == hashed
    except (ValueError, AttributeError):
        return False
