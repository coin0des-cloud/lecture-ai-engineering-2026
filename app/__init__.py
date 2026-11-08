"""Google ADK CLI entrypoint for ``adk run app`` and ``adk web``."""

from app.agent import root_agent

__all__ = ["root_agent"]