"""Public, sanitized Chiron building blocks."""

from importlib import import_module

__all__ = [
    "inspect_pdf_geometry",
    "render_agent_manifest",
    "tailor_contract",
    "validate_manifest",
]


def __getattr__(name: str):
    if name in __all__:
        return getattr(import_module(".resume", __name__), name)
    raise AttributeError(name)
