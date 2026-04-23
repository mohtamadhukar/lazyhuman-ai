"""Registry of sync target adapters.

Each adapter exposes `push(file_path: str, config: dict) -> dict` returning
`{"pushed": int, "errors": [str]}`. Register new adapters here by key.
"""
from .apple_notes import AppleNotesAdapter

REGISTRY = {
    "apple-notes": AppleNotesAdapter,
}
