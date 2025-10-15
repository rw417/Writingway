"""
Jinja2-based prompt rendering for Writingway.

This module provides a centralized renderer that:
- Exposes variable values and param-collector helpers to the template
- Produces readable error markers for missing variables
"""

from typing import Any, Dict, Optional

from jinja2 import Environment, Template, Undefined

# Lazy import to avoid circulars at import time
def _get_variable_manager():
    try:
        from .prompt_variables import get_variable_manager
        return get_variable_manager()
    except Exception:
        return None


class HelpfulUndefined(Undefined):
    """Undefined that renders as an inline error marker instead of empty string."""

    def __str__(self) -> str:  # type: ignore[override]
        name = getattr(self, "_undefined_name", "<unknown>")
        # Render like: {ERROR: 'var_name' not found}
        return f"{{ERROR: {name!r} not found}}"

    def __repr__(self) -> str:  # type: ignore[override]
        return str(self)

    def __call__(self, *args, **kwargs):  # type: ignore[override]
        return str(self)


def _build_env() -> Environment:
    env = Environment(
        undefined=HelpfulUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,
    )

    # Register helper callables that proxy to variable manager param collectors
    def wordsBefore(n: int = 200, fullSentence: bool = True) -> str:
        vm = _get_variable_manager()
        if not vm:
            return ""
        try:
            return vm.evaluate_param_variable("wordsBefore", [n, fullSentence])
        except Exception:
            return ""

    def wordsAfter(n: int = 200, fullSentence: bool = True) -> str:
        vm = _get_variable_manager()
        if not vm:
            return ""
        try:
            return vm.evaluate_param_variable("wordsAfter", [n, fullSentence])
        except Exception:
            return ""

    # Add helpers
    env.globals.update(
        wordsBefore=wordsBefore,
        wordsAfter=wordsAfter,
    )

    return env


_ENV: Optional[Environment] = None


def _env() -> Environment:
    global _ENV
    if _ENV is None:
        _ENV = _build_env()
    return _ENV



def render_template(template_text: str, variables: Optional[Dict[str, Any]] = None) -> str:
    """Render a prompt template using Jinja2.

    - Injects provided variables as the template context
    - Exposes helper functions registered on the environment
    """
    try:
        tmpl: Template = _env().from_string(template_text or "")
        ctx = dict(variables or {})
        return tmpl.render(**ctx)
    except Exception as e:
        # Fail soft: return original text and append error note so UI remains usable
        try:
            return f"{template_text}\n\n[Render error: {str(e)}]"
        except Exception:
            return template_text
