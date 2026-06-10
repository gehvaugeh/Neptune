import os
import asyncio
import logging
from typing import List, Dict, Any
from common import fuzzy_match, get_current_token



class AutocompleteProvider:
    async def get_suggestions(self, query: str, context: Dict[str, Any]) -> List[Dict[str, str]]:
        """Returns a list of suggestion objects: {'value': str, 'display': str, 'description': str, 'type': str}"""
        return []

    def _get_current_token(self, text: str) -> str:
        return get_current_token(text)

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
        if not app:
            logging.warning("ShadowShellProvider: No app in context")
            return []

        pty_uid = context.get("pty_uid", 0)
        logging.debug(f"ShadowShellProvider: Querying completions for UID {pty_uid}, query: '{query}'")
        request_id = str(os.urandom(4).hex())

        # We need a way to wait for the response from the server
        # This will be handled in ClientApp.listen_to_server and a Future
        future = asyncio.get_event_loop().create_future()
        app._autocomplete_futures[request_id] = future

        logging.debug(f"ShadowShellProvider: Sending request {request_id}")
        await app.send_message({
            "type": "autocomplete_query",
            "pty_uid": pty_uid,
            "query": query,
            "request_id": request_id
        })

        try:
            results = await asyncio.wait_for(future, timeout=2.0)
            logging.debug(f"ShadowShellProvider: Received {len(results)} results")
            if results:
                logging.debug(f"ShadowShellProvider: First 3: {results[:3]}")
            suggestions = []
            for res in results:
                suggestions.append({
                    "value": res,
                    "display": res,
                    "description": "Shadow Shell",
                    "type": "shell"
                })
                if len(suggestions) >= 10: break
            return suggestions
        except asyncio.TimeoutError:
            logging.warning("ShadowShellProvider: Timeout waiting for response")
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
            if q in val: return 2
            return 3

        all_suggestions.sort(key=lambda s: (score(s), len(s['value'])))
        return all_suggestions[:5]

    def _get_current_token(self, text: str) -> str:
        return get_current_token(text)

class LocalFileProvider(AutocompleteProvider):
    async def get_suggestions(self, query: str, context: Dict[str, Any]) -> List[Dict[str, str]]:
        cwd = context.get("cwd", os.getcwd())
        token = self._get_current_token(query)
        suggestions = []

        # Determine directory to list and filter prefix
        if token and "/" in token:
            dir_part, _, base_part = token.rpartition("/")
            if not dir_part or dir_part == ".":
                search_dir = cwd
            else:
                search_dir = os.path.join(cwd, dir_part)
            prefix = base_part
            prefix_path = token[:len(token) - len(base_part)] if base_part else token
        else:
            search_dir = cwd
            prefix = token or ""
            prefix_path = prefix

        try:
            entries = sorted(os.listdir(search_dir))
            for entry in entries:
                if prefix and not entry.lower().startswith(prefix.lower()):
                    continue
                full_path = os.path.join(search_dir, entry)
                display = entry + "/" if os.path.isdir(full_path) else entry
                if prefix_path and prefix is not token and prefix_path:
                    display = prefix_path + display
                suggestions.append({
                    "value": display,
                    "display": display,
                    "description": "Local file",
                    "type": "path"
                })
            return suggestions[:10]
        except (PermissionError, FileNotFoundError):
            return []

class CmdAutocompleteProvider(AutocompleteProvider):
    def __init__(self, commands: List[Dict[str, str]]):
        self.commands = commands
        self.bash_provider = BashAutocompleteProvider()
        self.file_provider = LocalFileProvider()

    async def get_suggestions(self, query: str, context: Dict[str, Any]) -> List[Dict[str, str]]:
        # If there's a space, we are in parameter territory — use LocalFileProvider
        if " " in query:
            parts = query.split(" ", 1)
            cmd, param_query = parts[0], parts[1]
            return await self.file_provider.get_suggestions(param_query, context)

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

