"""Agent tools for loading and using skills."""
from langchain_core.tools import tool

from app.agent.skills import registry


@tool
def load_skill(skill_name: str) -> str:
    """Load full instructions for a specific skill.

    Use this when you need detailed instructions for a task that matches
    one of the Available Skills in your system prompt.

    Args:
        skill_name: Exact name of the skill (from Available Skills list)

    Returns:
        Full SKILL.md content with detailed instructions
    """
    try:
        return registry.get_skill_md(skill_name)
    except FileNotFoundError:
        return f"Skill '{skill_name}' not found. Check Available Skills list."
    except Exception as e:
        return f"Error loading skill: {e}"


@tool
def read_skill_resource(skill_name: str, filename: str) -> str:
    """Read a supporting file bundled with a skill.

    Skills may include reference documents, scripts, or examples.
    Use this to access those files when the SKILL.md instructs you to.

    Args:
        skill_name: Name of the skill
        filename: Relative filename within the skill folder (e.g., "reference.md", "script.py")

    Returns:
        File content as text
    """
    try:
        return registry.get_skill_resource(skill_name, filename)
    except FileNotFoundError as e:
        return f"Resource not found: {e}"
    except ValueError as e:
        return f"Invalid path: {e}"
    except Exception as e:
        return f"Error reading resource: {e}"


SKILL_TOOLS = [load_skill, read_skill_resource]
