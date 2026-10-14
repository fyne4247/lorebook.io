"""
novelWriter – AI Model / Effort Choices
=======================================

Shared model and effort labels for the AI sidebar and Preferences dialog.
Values are passed through to Claude Code as ``--model`` / ``--effort``.
"""  # noqa

from __future__ import annotations

# (data value for --model / CONFIG.aiModel, display label)
# Empty string is "Agent default" and is added by the UI, not listed here.
#
# Short aliases (sonnet, opus, haiku, fable) follow Claude Code conventions.
# Versioned ids match what works with `claude --model …` and `/model`.
AI_MODEL_CHOICES: tuple[tuple[str, str], ...] = (
    ("sonnet", "Sonnet"),
    ("claude-sonnet-4-6", "Sonnet 4.6"),
    ("claude-sonnet-4-5", "Sonnet 4.5"),
    ("opus", "Opus"),
    ("claude-opus-4-6", "Opus 4.6"),
    ("haiku", "Haiku"),
    ("fable", "Fable"),
)

# (data value for --effort / CONFIG.aiEffort, display label)
# Empty string is "Default" and is added by the UI, not listed here.
AI_EFFORT_CHOICES: tuple[tuple[str, str], ...] = (
    ("low", "Low"),
    ("medium", "Medium"),
    ("high", "High"),
    ("xhigh", "Extra high"),
    ("max", "Max"),
)

# Fresh-install defaults for the AI sidebar combos.
DEFAULT_AI_AGENT = "muse"
DEFAULT_AI_MODEL = "sonnet"
DEFAULT_AI_EFFORT = ""  # CLI / agent default
