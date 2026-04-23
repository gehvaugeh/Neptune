import os
import re
from typing import List, Dict, Any
from common import fuzzy_match

class AutocompleteProvider:
    def get_suggestions(self, query: str, context: Dict[str, Any]) -> List[Dict[str, str]]:
        """Returns a list of suggestion objects: {'value': str, 'display': str, 'description': str, 'type': str}"""
        return []

class BashAutocompleteProvider(AutocompleteProvider):
    def get_suggestions(self, query: str, context: Dict[str, Any]) -> List[Dict[str, str]]:
        suggestions = []
        history = context.get("history", [])
        workflows = context.get("workflows", [])

        # 1. Path Completion
        token = self._get_current_token(query)
        last = token.strip("\"'")
        d_p, f_q = os.path.dirname(last), os.path.basename(last)
        try:
            ex_d = os.path.expanduser(d_p) if d_p else "."
            if os.path.isdir(ex_d):
                for f in os.listdir(ex_d):
                    if fuzzy_match(f_q, f):
                        full = os.path.join(d_p, f) if d_p else f
                        is_dir = os.path.isdir(os.path.join(ex_d, f))
                        val = f'"{full}"' if " " in full else full
                        suggestions.append({
                            "value": val,
                            "display": f"{full}{'/' if is_dir else ''}",
                            "description": "Directory" if is_dir else "File",
                            "type": "path"
                        })
        except: pass

        # 2. History
        for h in history[::-1]:
            if fuzzy_match(query, h):
                suggestions.append({
                    "value": h,
                    "display": h,
                    "description": "From History",
                    "type": "history"
                })

        # 3. Workflows
        for wf in workflows:
            if fuzzy_match(query, wf['name']) or fuzzy_match(query, wf['cmd']):
                suggestions.append({
                    "value": wf['cmd'],
                    "display": wf['name'],
                    "description": f"Workflow: {wf['cmd'][:30]}...",
                    "type": "workflow"
                })

        return suggestions[:20]

    def _get_current_token(self, text: str) -> str:
        if not text or text.endswith(" "): return ""
        parts = re.findall(r'(?:[^\s"\']|"(?:\\.|[^"])*"|\'(?:\\.|[^\'])*\')+', text)
        return parts[-1] if parts else ""

class CmdAutocompleteProvider(AutocompleteProvider):
    def __init__(self, commands: List[Dict[str, str]]):
        self.commands = commands

    def get_suggestions(self, query: str, context: Dict[str, Any]) -> List[Dict[str, str]]:
        suggestions = []
        for cmd in self.commands:
            if fuzzy_match(query, cmd['name']):
                suggestions.append({
                    "value": cmd['name'],
                    "display": cmd['name'],
                    "description": f"{cmd.get('params', '')} - {cmd.get('desc', '')}",
                    "type": "cmd"
                })
        return suggestions

class MarkdownAutocompleteProvider(AutocompleteProvider):
    SYNTAX = [
        {"value": "# ", "display": "# Header 1", "description": "H1 title", "type": "md"},
        {"value": "## ", "display": "## Header 2", "description": "H2 title", "type": "md"},
        {"value": "### ", "display": "### Header 3", "description": "H3 title", "type": "md"},
        {"value": "**bold**", "display": "**Bold**", "description": "Bold text", "type": "md"},
        {"value": "*italic*", "display": "*Italic*", "description": "Italic text", "type": "md"},
        {"value": "```bash\n\n```", "display": "``` Code Block", "description": "Bash code block", "type": "md"},
        {"value": "- ", "display": "- List Item", "description": "Unordered list item", "type": "md"},
        {"value": "[label](url)", "display": "[Link]", "description": "Markdown link", "type": "md"},
    ]

    def get_suggestions(self, query: str, context: Dict[str, Any]) -> List[Dict[str, str]]:
        if not query: return self.SYNTAX
        return [s for s in self.SYNTAX if fuzzy_match(query, s['display'])]
