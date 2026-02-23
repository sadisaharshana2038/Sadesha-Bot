import json
import os

ADMINS_FILE = "admins.json"
HARDCODED_ADMINS = {"@slhomelander", "@sljohnwick"}

def load_dynamic_admins():
    """Loads dynamic admins from admins.json."""
    if not os.path.exists(ADMINS_FILE):
        return set()
    try:
        with open(ADMINS_FILE, "r") as f:
            data = json.load(f)
            return set(data.get("admins", []))
    except (json.JSONDecodeError, Exception):
        return set()

def save_dynamic_admins(admins):
    """Saves dynamic admins to admins.json."""
    with open(ADMINS_FILE, "w") as f:
        json.dump({"admins": list(admins)}, f, indent=4)

def get_all_admins():
    """Returns a set of all admins (hardcoded + dynamic + environment)."""
    dynamic_admins = load_dynamic_admins()
    all_admins = HARDCODED_ADMINS.union(dynamic_admins)
    
    # Heroku compatibility: load admins from environment variable
    env_admins = os.environ.get("EXTRA_ADMINS", "")
    if env_admins:
        extra = {admin.strip() for admin in env_admins.split(",") if admin.strip()}
        all_admins = all_admins.union(extra)
        
    return all_admins

def is_admin(username):
    """Checks if a username is in the admin list."""
    if not username:
        return False
    # Ensure username starts with @ for comparison
    if not username.startswith("@") and not username.isdigit():
        username = f"@{username}"
    
    all_admins = get_all_admins()
    return username in all_admins

def add_admin(username):
    """Adds a new username to dynamic admins."""
    if not username.startswith("@") and not username.isdigit():
        username = f"@{username}"
    
    if username in HARDCODED_ADMINS:
        return False, "User is already a permanent admin."
    
    admins = load_dynamic_admins()
    if username in admins:
        return False, "User is already an admin."
    
    admins.add(username)
    save_dynamic_admins(admins)
    return True, f"User {username} added as admin."

def remove_admin(username):
    """Removes a username from dynamic admins."""
    if not username.startswith("@") and not username.isdigit():
        username = f"@{username}"
    
    if username in HARDCODED_ADMINS:
        return False, "Cannot remove permanent admins."
    
    admins = load_dynamic_admins()
    if username not in admins:
        return False, "User is not a dynamic admin."
    
    admins.remove(username)
    save_dynamic_admins(admins)
    return True, f"User {username} removed from admins."
