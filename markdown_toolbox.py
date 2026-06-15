from textual.widgets import Input, OptionList
from textual.widgets.option_list import Option
from textual.containers import Vertical
from textual import on, message, events
from textual.app import ComposeResult
from common import fuzzy_match

MD_ELEMENTS = [
    {"id": "h1",       "value": "# <content>",                  "display": "# Header 1",    "desc": "H1 title",         "placeholder": "<content>"},
    {"id": "h2",       "value": "## <content>",                 "display": "## Header 2",   "desc": "H2 title",         "placeholder": "<content>"},
    {"id": "h3",       "value": "### <content>",                "display": "### Header 3",  "desc": "H3 title",         "placeholder": "<content>"},
    {"id": "bold",     "value": "**<content>**",                "display": "**Bold**",      "desc": "Bold text",        "placeholder": "<content>"},
    {"id": "italic",   "value": "*<content>*",                  "display": "*Italic*",      "desc": "Italic text",      "placeholder": "<content>"},
    {"id": "code",     "value": "```bash\n~<content>\n```",     "display": "``` Code",      "desc": "Code block",       "placeholder": "<content>"},
    {"id": "bullet",   "value": "- <content>",                  "display": "- List",        "desc": "Unordered list",   "placeholder": "<content>"},
    {"id": "link",     "value": "[<content>](url)",             "display": "[Link]",        "desc": "Markdown link",    "placeholder": "<content>"},
    {"id": "image",    "value": "![<content>](url)",            "display": "![Image]",      "desc": "Image",            "placeholder": "<content>"},
    {"id": "quote",    "value": "> <content>",                  "display": "> Quote",       "desc": "Blockquote",       "placeholder": "<content>"},
    {"id": "hr",       "value": "---\n",                        "display": "--- HR",        "desc": "Horizontal rule"},
    {"id": "inline_c", "value": "`<content>`",                  "display": "`Code`",        "desc": "Inline code",      "placeholder": "<content>"},
    {"id": "task",     "value": "- [ ] <content>",              "display": "- [ ] Task",    "desc": "Task list item",   "placeholder": "<content>"},
]

class MdElementSelected(message.Message):
    def __init__(self, element: dict) -> None:
        super().__init__()
        self.element = element

class MarkdownToolboxPanel(Vertical):
    DEFAULT_CSS = ""

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Filter markdown...", id="md_filter")
        yield OptionList(id="md_list")

    def on_mount(self):
        self._populate()

    def show(self):
        self.add_class("-visible")
        self.query_one("#md_filter").focus()
        self._populate()

    def hide(self):
        self.remove_class("-visible")
        self.query_one("#md_filter").value = ""

    def _populate(self, query: str = ""):
        ol = self.query_one("#md_list")
        ol.clear_options()
        for item in MD_ELEMENTS:
            if not query or fuzzy_match(query, item["display"]):
                ol.add_option(Option(
                    f"[bold #ff5252]{item['id'].upper()}:[/] {item['display']}"
                    f" [dim]{item['desc']}[/]",
                    id=item["id"]
                ))
        if ol.option_count > 0 and ol.highlighted is None:
            ol.highlighted = 0

    @on(Input.Changed, "#md_filter")
    def on_filter_change(self, event: Input.Changed):
        self._populate(event.value)

    @on(Input.Submitted, "#md_filter")
    def on_filter_submit(self):
        ol = self.query_one("#md_list")
        if ol.highlighted is not None:
            opt = ol.get_option_at_index(ol.highlighted)
            self._select(opt.id)

    @on(OptionList.OptionSelected, "#md_list")
    def on_list_selected(self, event: OptionList.OptionSelected):
        self._select(event.option.id)

    def _select(self, element_id: str):
        for item in MD_ELEMENTS:
            if item["id"] == element_id:
                self.post_message(MdElementSelected(item))
                break

    def on_key(self, event: events.Key):
        if event.key == "up":
            event.stop()
            ol = self.query_one("#md_list")
            idx = ol.highlighted if ol.highlighted is not None else 0
            ol.highlighted = max(0, idx - 1)
        elif event.key == "down":
            event.stop()
            ol = self.query_one("#md_list")
            idx = ol.highlighted if ol.highlighted is not None else 0
            ol.highlighted = min(ol.option_count - 1, idx + 1)
