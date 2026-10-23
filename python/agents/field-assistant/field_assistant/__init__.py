"""Field Assistant: plan the day, log door knocks, submit at night.

The ADK agent lives in ``agent.py`` (``adk web`` finds ``root_agent``);
``server.py`` serves the phone app, the REST API and the AG-UI endpoint
from one FastAPI process.
"""

from . import agent
