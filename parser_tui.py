from enum import Enum
from urllib.parse import urlparse
import httpx
from textual.app import App, ComposeResult
from textual.reactive import reactive, var
from textual.highlight import highlight
from textual.screen import Screen
from textual.widgets import Header, Footer, Input, ListView, ListItem, Label, Static, LoadingIndicator
from textual.containers import VerticalScroll
from bs4 import BeautifulSoup
import parser


class SelectInputType(Screen[str]):

    def compose(self):
        yield Label("Choose how to import your AO3 fic!")
        yield ListView(
            ListItem(Label("HTML File"), name="HTML File", id="from_html"),
            ListItem(Label("AO3 URL"), name="AO3 URL", id="from_url"),
        )
        yield Footer()

    def on_list_view_selected(self, event: ListView.Selected):
        if event.item.id == "from_html":
            self.dismiss("file")
        else:
            self.dismiss("url")

class InputURL(Screen[str]):

    content: str = reactive("")

    def compose(self):
        yield Label("What is the link to the fic you wish to download?", id="url_label")
        yield Input(placeholder="https://www.archiveofourown.org/works/XXXXXXXX", id="url_in")
        yield Label("", id="msg")
        yield LoadingIndicator(id="load")
        yield Footer()
    
    def on_mount(self):
        self.query_one("#load", LoadingIndicator).styles.display = "none"

    async def on_input_submitted(self, event: Input.Submitted):
        await self.query_one("#url_label", Label).remove()
        await event.input.remove()
        
        self.run_worker(self.retrieve_url_content(event.input.value), exclusive=True, thread=True)
        self.query_one("#load", LoadingIndicator).styles.display = "block"
        msg = self.query_one("#msg",Label)
        msg.content = "Loading content..."
    
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
                self.content = contents.text
                self.dismiss(contents.text)
        except httpx.ConnectError as err:
            self.query_one("#load", LoadingIndicator).styles.display = "none"
            msg = self.query_one("#msg",Label)
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
        return super().action_quit()


if __name__ == "__main__":
    app = AO3BookifyTUI()
    app.run()
