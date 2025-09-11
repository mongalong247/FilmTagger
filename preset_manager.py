import os
import json

# --- CONSTANTS ---
# Define a base directory for presets within a 'resources' folder
RESOURCES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources")
PRESETS_DIR = os.path.join(RESOURCES_DIR, "presets")
PRESET_TYPES = ["cameras", "lenses", "film_stocks"]

def ensure_presets_dir_exists():
    """Create the presets directory if it doesn't exist."""
    os.makedirs(PRESETS_DIR, exist_ok=True)

def get_preset_filepath(preset_type: str) -> str:
    """Returns the full path for a given preset type's JSON file."""
    if preset_type not in PRESET_TYPES:
        raise ValueError(f"Invalid preset type: {preset_type}")
    return os.path.join(PRESETS_DIR, f"{preset_type}.json")

def load_presets(preset_type: str) -> dict:
    """
    Loads presets from a JSON file.
    Returns a dictionary of presets, or an empty dictionary if the file doesn't exist.
    """
    ensure_presets_dir_exists()
    filepath = get_preset_filepath(preset_type)
    
    if not os.path.exists(filepath):
        return {}
        
    try:
        with open(filepath, 'r') as f:
            data = json.load(f)
            # Ensure the data is a dictionary
            return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error loading {filepath}: {e}")
        return {}

def save_presets(preset_type: str, data: dict):
    """
    Saves a dictionary of presets to a JSON file.
    """
    ensure_presets_dir_exists()
    filepath = get_preset_filepath(preset_type)
    
    try:
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=4)
        return True
    except IOError as e:
        print(f"Error saving {filepath}: {e}")
        return False

