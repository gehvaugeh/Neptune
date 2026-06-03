import os
import re
import asyncio
from typing import List, Dict, Any
from common import fuzzy_match

class AutocompleteProvider:
    async def get_suggestions(self, query: str, context: Dict[str, Any]) -> List[Dict[str, str]]:
        """Returns a list of suggestion objects: {'value': str, 'display': str, 'description': str, 'type': str}"""
        return []

class HistoryProvider(AutocompleteProvider):
    async def get_suggestions(self, query: str, context: Dict[str, Any]) -> List[Dict[str, str]]:
        history = context.get("history", [])
        suggestions = []
        seen = set()
        for h in history[::-1]:
            if h not in seen and fuzzy_match(query, h):
                suggestions.append({
                    "value": h,
                    "display": h,
                    "description": "From History",
                    "type": "history"
                })
                seen.add(h)
                if len(suggestions) >= 5: break
        return suggestions

class WorkflowProvider(AutocompleteProvider):
    async def get_suggestions(self, query: str, context: Dict[str, Any]) -> List[Dict[str, str]]:
        workflows = context.get("workflows", [])
        suggestions = []
        for wf in workflows:
            if fuzzy_match(query, wf['name']) or fuzzy_match(query, wf['cmd']):
                suggestions.append({
                    "value": wf['cmd'],
                    "display": wf['name'],
                    "description": f"Workflow: {wf['cmd'][:30]}...",
                    "type": "workflow"
                })
                if len(suggestions) >= 5: break
        return suggestions

class ShadowShellProvider(AutocompleteProvider):
    async def get_suggestions(self, query: str, context: Dict[str, Any]) -> List[Dict[str, str]]:
        app = context.get("app")
        if not app: return []

        pty_uid = context.get("pty_uid", 0)
        request_id = str(os.urandom(4).hex())

        # We need a way to wait for the response from the server
        # This will be handled in ClientApp.listen_to_server and a Future
        future = asyncio.get_event_loop().create_future()
        app._autocomplete_futures[request_id] = future

        await app.send_message({
            "type": "autocomplete_query",
            "pty_uid": pty_uid,
            "query": query,
            "request_id": request_id
        })

        try:
            results = await asyncio.wait_for(future, timeout=2.0)
            suggestions = []
            for res in results:
                suggestions.append({
                    "value": res,
                    "display": res,
                    "description": "Shadow Shell",
                    "type": "shell"
                })
                if len(suggestions) >= 10: break # More from shell but client will trim
            return suggestions
        except asyncio.TimeoutError:
            return []
        finally:
            app._autocomplete_futures.pop(request_id, None)

class BashAutocompleteProvider(AutocompleteProvider):
    def __init__(self):
        self.providers = [HistoryProvider(), WorkflowProvider(), ShadowShellProvider()]

    async def get_suggestions(self, query: str, context: Dict[str, Any]) -> List[Dict[str, str]]:
        all_suggestions = []
        # Run providers in parallel
        tasks = [p.get_suggestions(query, context) for p in self.providers]
        results = await asyncio.gather(*tasks)
        for r in results:
            all_suggestions.extend(r)

        # Robust tokenization: find the last token
        token = self._get_current_token(query)

        # Match scoring and sorting
        def score(s):
            # Prioritize exact matches and shorter values relative to the TOKEN
            val = s['value'].lower()
            q = token.lower() if token else query.lower()
            if not q: return 2

            # If the suggestion contains the query token at the end (for paths)
            if val == q: return 0
            if val.startswith(q) or val.endswith(f"/{q}"): return 1
            return 2

        all_suggestions.sort(key=lambda s: (score(s), len(s['value'])))
        return all_suggestions[:5]

    def _get_current_token(self, text: str) -> str:
        if not text or text.endswith(" "): return ""
        # Improved tokenization to handle quotes and spaces correctly
        parts = re.findall(r'(?:[^\s"\']|"(?:\\.|[^"])*"|\'(?:\\.|[^\'])*\')+', text)
        return parts[-1] if parts else ""

class CmdAutocompleteProvider(AutocompleteProvider):
    def __init__(self, commands: List[Dict[str, str]]):
        self.commands = commands
        self.bash_provider = BashAutocompleteProvider()

    async def get_suggestions(self, query: str, context: Dict[str, Any]) -> List[Dict[str, str]]:
        # If there's a space, we are in parameter territory
        if " " in query:
            parts = query.split(" ", 1)
            cmd, param_query = parts[0], parts[1]
            return await self.bash_provider.get_suggestions(param_query, context)

        suggestions = []
        for cmd in self.commands:
            if fuzzy_match(query, cmd['name']):
                suggestions.append({
                    "value": cmd['name'],
                    "display": cmd['name'],
                    "description": f"{cmd.get('params', '')} - {cmd.get('desc', '')}",
                    "type": "cmd"
                })
        return suggestions[:5]

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

    async def get_suggestions(self, query: str, context: Dict[str, Any]) -> List[Dict[str, str]]:
        if not query: return self.SYNTAX[:5]
        return [s for s in self.SYNTAX if fuzzy_match(query, s['display'])][:5]
