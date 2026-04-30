"""Backward-compatible alias for superordinate_getresponse.

The advertised/discovered tool name is now superordinate_getresponse.
This module remains so older explicit calls to superordinate_lastresponse do not break.
"""

try:
    # Package import path, used when plugin modules are importable as packages.
    from usr.plugins.a0_superordinates.tools.superordinate_getresponse import SuperordinateGetresponse
except Exception:
    # File-loader fallback, used by loaders that import this module without a
    # package parent. Keep this alias invisible to prompts/tool discovery.
    import importlib.util
    import os

    _path = os.path.join(os.path.dirname(__file__), "superordinate_getresponse.py")
    _spec = importlib.util.spec_from_file_location("_a0_superordinate_getresponse_alias", _path)
    _module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_module)
    SuperordinateGetresponse = _module.SuperordinateGetresponse


class SuperordinateLastresponse(SuperordinateGetresponse):
    pass
