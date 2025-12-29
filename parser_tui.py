from enum import Enum
from urllib.parse import urlparse
import httpx
from textual.app import App, ComposeResult
from textual.reactive import reactive, var
from textual.highlight import highlight
from textual.screen import Screen
from textual.widgets import Header, Footer, Input, OptionList, Label, Static, LoadingIndicator
from textual.widgets.option_list import Option
from textual.containers import VerticalScroll, VerticalGroup, HorizontalGroup
from bs4 import BeautifulSoup
import parser

ascii_text : str = """
 _____ _____ ___ _____         _   _ ___     
|  _  |     |_  | __  |___ ___| |_|_|  _|_ _ 
|     |  |  |_  | __ -| . | . | '_| |  _| | |
|__|__|_____|___|_____|___|___|_,_|_|_| |_  |
                                        |___|
"""

class SelectInputType(Screen[str]):
    CSS_PATH = "styles.tcss"

    def compose(self) -> ComposeResult:
        with VerticalGroup(id="welcome_text"):
            yield Label(ascii_text)
            yield Label("Choose how to import your AO3 fic!")
        lv = OptionList(
            Option("HTML File", id="from_html"),
            Option("AO3 URL", id="from_url"),
            id="in_opt"
        )
        lv.border_title = "Input"
        yield lv
        yield Footer()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id == "from_html":
            self.dismiss("file")
        else:
            self.dismiss("url")

class InputURL(Screen[str]):

    content: str = reactive("")

    def compose(self):
        yield Label("What is the link to the fic you wish to download?", id="url_label")
        url_in = Input(placeholder="https://www.archiveofourown.org/works/XXXXXXXX", id="url_in")
        url_in.border_title = "URL"
        yield url_in
        yield Label("", id="msg")
        yield LoadingIndicator(id="load")
        yield Footer()
    
    def on_mount(self):
        self.query_one("#load", LoadingIndicator).styles.display = "none"

    def display_error(self, error_msg : str) -> None:
        self.query_one("#load", LoadingIndicator).styles.display = "none"
        msg = self.query_one("#msg",Label)
        msg.border_title = "ERROR"
        msg.remove_class("-info")
        msg.add_class("-ao3-error")
        msg.content = error_msg

    async def on_input_submitted(self, event: Input.Submitted):

        is_valid, error_msg = parser.verify_url(event.input.value)

        if not is_valid:
            msg = self.query_one("#msg",Label)
            msg.set_class(not msg.has_class("-ao3-error"), "-ao3-error")
            msg.border_title = "ERROR"
            msg.content = error_msg
            return
        
        await self.query_one("#url_label", Label).remove()
        await event.input.remove()
        self.query_one("#load", LoadingIndicator).styles.display = "block"
        msg = self.query_one("#msg",Label)
        msg.remove_class("-ao3-error")
        msg.add_class("-info")
        msg.border_title = "INFO"
        msg.content = "Loading content..."
        self.run_worker(self.retrieve_url_content(event.input.value), exclusive=True, thread=True)
    
    async def retrieve_url_content(self, url: str):
        parsed_url = urlparse(url)
        relative_path = parsed_url.path
        if "chapters" in relative_path:
            parts = relative_path.split("/")
            relative_path = "/".join(parts[:3])
            parsed_url = parsed_url._replace(path=relative_path)
        if not parsed_url.query.startswith("view_full_work"):
            parsed_url = parsed_url._replace(query="view_full_work=true")
        try:
            async with httpx.AsyncClient() as client:
                contents = await client.get(parsed_url.geturl(), timeout=60)
                self.content = f"This had response {contents.status_code}\n" + contents.text
                self.dismiss(self.content)
        except httpx.ConnectError as err:
            self.query_one("#load", LoadingIndicator).styles.display = "none"
            msg = self.query_one("#msg",Label)
            msg.border_title = "ERROR"
            msg.remove_class("-info")
            msg.add_class("-ao3-error")
            msg.content = "Oops! Looks like something went wrong while trying to request the fic.\nMake sure you're connected to the Internet and that your ISP doesn't block AO3!"


class AO3BookifyTUI(App):

    BINDINGS = {("q", "quit", "Quit")}

    html_preview = reactive("")

    def compose(self):
        with VerticalScroll(id="code-view"):
            yield Static(id="code", expand=True)
        yield Footer()
    

    def on_mount(self) -> None:
        self.install_screen(SelectInputType(), name="select_input")
        self.install_screen(InputURL(), name="input_url")

        def update_field(input: str | None) -> None:
            block = self.query_one("#code", Static)
            block.update(highlight(BeautifulSoup(input, "lxml").prettify(), language="html"))
        
        def switch_to_fic_input(mode: str | None) -> None:
            if mode == "file":
                self.exit(message="HTML!")
            else:
                self.push_screen("input_url", update_field)

        self.push_screen("select_input", callback=switch_to_fic_input)

    def action_quit(self):
        self.exit(message="Exiting AO3Bookify...")


if __name__ == "__main__":
    app = AO3BookifyTUI()
    app.run()
