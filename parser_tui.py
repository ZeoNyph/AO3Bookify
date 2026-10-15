from pathlib import Path
from typing import Iterable

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    Checkbox,
    DirectoryTree,
    Footer,
    Input,
    Label,
    LoadingIndicator,
    RadioButton,
    RadioSet,
    RichLog,
    Static,
)
from textual.worker import get_current_worker

import parser

ascii_text: str = """\
 _____ _____ ___ _____         _   _ ___
|  _  |     |_  | __  |___ ___| |_|_|  _|_ _
|     |  |  |_  | __ -| . | . | '_| |  _| | |
|__|__|_____|___|_____|___|___|_,_|_|_| |_  |
                                        |___|"""

URL_PLACEHOLDER = "https://archiveofourown.org/works/12345678"
FILE_PLACEHOLDER = "~/Downloads/My Fic.html"


class HtmlDirectoryTree(DirectoryTree):
    """Directory tree that only shows folders and HTML files."""

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        return [
            path
            for path in paths
            if not path.name.startswith(".")
            and (path.is_dir() or path.suffix.lower() in (".html", ".htm"))
        ]


class FilePicker(ModalScreen[str | None]):
    """Modal for picking an HTML file from disk."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("backspace", "go_up", "Parent folder"),
    ]

    def __init__(self, start: Path) -> None:
        super().__init__()
        self.start = start

    def compose(self) -> ComposeResult:
        with Vertical(id="picker"):
            yield Label("Pick the HTML file of your fic", id="picker_title")
            yield Label(str(self.start), id="picker_path", markup=False)
            yield HtmlDirectoryTree(self.start, id="picker_tree")
            with Horizontal(classes="buttons"):
                yield Button("Parent folder", id="picker_up")
                yield Button("Cancel", id="picker_cancel", variant="error")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(HtmlDirectoryTree).focus()

    def _set_root(self, path: Path) -> None:
        self.start = path
        self.query_one(HtmlDirectoryTree).path = path
        self.query_one("#picker_path", Label).update(str(path))

    @on(DirectoryTree.FileSelected)
    def file_selected(self, event: DirectoryTree.FileSelected) -> None:
        self.dismiss(str(event.path))

    @on(Button.Pressed, "#picker_up")
    def action_go_up(self) -> None:
        self._set_root(self.start.parent)

    @on(Button.Pressed, "#picker_cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)


class FormScreen(Screen):
    """Main screen: choose the fic source and options."""

    BINDINGS = [
        Binding("ctrl+o", "browse", "Browse files"),
        Binding("ctrl+b", "bookify", "Bookify!", priority=True),
    ]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="form_scroll"):
            with Vertical(id="form"):
                with Center():
                    yield Static(ascii_text, id="banner")
                yield Label(
                    "Turn an AO3 fic into a nicely formatted, book-sized PDF.",
                    id="tagline",
                )

                yield Label("1. Where is the fic?", classes="section")
                with RadioSet(id="source"):
                    yield RadioButton("AO3 link", id="src_url", value=True)
                    yield RadioButton("HTML file on this computer", id="src_file")
                with Horizontal(id="path_row"):
                    yield Input(placeholder=URL_PLACEHOLDER, id="path")
                    yield Button("Browse…", id="browse")
                yield Label("", id="path_msg", classes="hint", markup=False)

                yield Label("2. Options", classes="section")
                yield Checkbox("Remove author notes", id="no_notes")
                yield Input(
                    placeholder="Output file (leave empty to use the fic's title)",
                    id="output",
                )

                with Center():
                    yield Button("Bookify!", id="go", variant="success")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#browse").display = False
        self.query_one("#path", Input).focus()

    using_url: bool = True

    def _set_source(self, url: bool) -> None:
        """Switch source mode without clearing what the user typed."""
        self.using_url = url
        with self.prevent(RadioSet.Changed):
            self.query_one("#src_url" if url else "#src_file", RadioButton).value = True
        self.query_one("#path", Input).placeholder = (
            URL_PLACEHOLDER if url else FILE_PLACEHOLDER
        )
        self.query_one("#browse").display = not url

    @on(RadioSet.Changed, "#source")
    def source_changed(self, event: RadioSet.Changed) -> None:
        self.using_url = event.pressed.id == "src_url"
        path_input = self.query_one("#path", Input)
        path_input.placeholder = URL_PLACEHOLDER if self.using_url else FILE_PLACEHOLDER
        path_input.value = ""
        self.query_one("#browse").display = not self.using_url
        self._show_hint("")
        path_input.focus()

    def _show_hint(self, message: str, error: bool = False) -> None:
        msg = self.query_one("#path_msg", Label)
        msg.update(message)
        msg.set_class(error, "-error")
        self.query_one("#path", Input).set_class(error, "-invalid")

    def _validate(self) -> bool:
        value = self.query_one("#path", Input).value.strip()
        if not value:
            self._show_hint(
                "Paste a link to the fic." if self.using_url else "Choose a file.",
                error=True,
            )
            return False
        check = parser.verify_url if self.using_url else parser.verify_file
        ok, error = check(value)
        self._show_hint("" if ok else error, error=not ok)
        return ok

    @on(Input.Changed, "#path")
    def path_changed(self, event: Input.Changed) -> None:
        # Auto-switch source if the user pastes something of the other kind.
        value = event.value.strip()
        looks_like_file = value.lower().endswith((".html", ".htm"))
        target = None
        if parser.is_url(value) and not self.using_url:
            target = "#src_url"
        elif looks_like_file and not parser.is_url(value) and self.using_url:
            target = "#src_file"
        if target:
            self._set_source(target == "#src_url")
        if self.query_one("#path_msg", Label).has_class("-error"):
            self._validate()

    @on(Input.Submitted)
    def input_submitted(self) -> None:
        self.action_bookify()

    @on(Button.Pressed, "#browse")
    def action_browse(self) -> None:
        def picked(path: str | None) -> None:
            if path:
                self._set_source(url=False)
                self.query_one("#path", Input).value = path
                self._validate()
                self.query_one("#go", Button).focus()

        current = Path(self.query_one("#path", Input).value.strip()).expanduser()
        start = current.parent if current.parent.is_dir() and str(current) != "." else Path.cwd()
        self.app.push_screen(FilePicker(start.resolve()), picked)

    @on(Button.Pressed, "#go")
    def action_bookify(self) -> None:
        if not self._validate():
            self.query_one("#path", Input).focus()
            return
        self.app.push_screen(
            ProgressScreen(
                path=self.query_one("#path", Input).value.strip(),
                no_notes=self.query_one("#no_notes", Checkbox).value,
                output=self.query_one("#output", Input).value.strip() or None,
            )
        )


STEPS = [
    ("load", "Loading fic"),
    ("format", "Formatting chapters"),
    ("browser", "Preparing PDF renderer"),
    ("pdf", "Writing PDF"),
]


class ProgressScreen(Screen):
    """Runs the conversion and shows progress / result."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("o", "open_pdf", "Open PDF", show=False),
    ]

    def __init__(self, path: str, no_notes: bool, output: str | None) -> None:
        super().__init__()
        self.path = path
        self.no_notes = no_notes
        self.output = output
        self.result: Path | None = None
        self.running = True

    def compose(self) -> ComposeResult:
        with Vertical(id="progress"):
            yield Label("Bookifying…", id="progress_title")
            yield Label(self.path, id="progress_source", markup=False)
            with Vertical(id="steps"):
                for key, text in STEPS:
                    yield Label(f"  ○  {text}", id=f"step_{key}", classes="step")
            yield LoadingIndicator(id="spinner")
            yield Label("", id="result", markup=False)
            yield RichLog(id="log", wrap=True, min_width=20)
            with Horizontal(classes="buttons", id="done_buttons"):
                yield Button("Open PDF", id="open", variant="success")
                yield Button("Bookify another", id="again", variant="primary")
                yield Button("Quit", id="quit", variant="error")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#done_buttons").display = False
        self.query_one("#result").display = False
        self.convert()

    # --- UI helpers (called from the worker thread via call_from_thread) ---

    def _log(self, text: str) -> None:
        self.query_one(RichLog).write(text)

    def _step(self, key: str, state: str) -> None:
        icon = {"running": "◐", "done": "✔", "failed": "✘"}[state]
        text = dict(STEPS)[key]
        step = self.query_one(f"#step_{key}", Label)
        step.update(f"  {icon}  {text}")
        step.set_classes(f"step -{state}")

    def _finish(self, ok: bool, message: str) -> None:
        self.running = False
        self.query_one("#spinner").display = False
        title = self.query_one("#progress_title", Label)
        title.update("All done!" if ok else "Something went wrong")
        title.set_class(not ok, "-error")
        result = self.query_one("#result", Label)
        result.update(message)
        result.set_class(not ok, "-error")
        result.display = True
        self.query_one("#open").display = ok
        self.query_one("#again", Button).label = (
            "Bookify another" if ok else "Back"
        )
        self.query_one("#done_buttons").display = True
        self.query_one("#open" if ok else "#again", Button).focus()

    # --- worker ---

    @work(thread=True, exclusive=True)
    def convert(self) -> None:
        call = self.app.call_from_thread
        worker = get_current_worker()
        current = "load"
        try:
            call(self._step, "load", "running")
            if parser.is_url(self.path):
                call(self._log, "Downloading from AO3 (big fics can take a while)…")
            soup = parser.load_fic(self.path)
            meta = parser.get_fic_metadata(soup)
            call(self._log, f"Found {meta['title']} by {meta['author']}")
            call(self._step, "load", "done")
            if worker.is_cancelled:
                return

            current = "format"
            call(self._step, "format", "running")
            contents = parser.format_fic(soup, self.no_notes)
            if self.no_notes:
                call(self._log, "Removed author notes")
            call(self._step, "format", "done")
            if worker.is_cancelled:
                return

            current = "browser"
            call(self._step, "browser", "running")
            if not parser.chromium_installed():
                call(self._log, "Installing Chromium (one-time setup)…")
                parser.install_chromium(lambda line: call(self._log, line))
            call(self._step, "browser", "done")
            if worker.is_cancelled:
                return

            current = "pdf"
            call(self._step, "pdf", "running")
            output = parser.output_path(self.output, meta["title"])
            parser.write_to_pdf(contents, str(output))
            call(self._step, "pdf", "done")

            self.result = output.resolve()
            call(self._log, f"Saved to {self.result}")
            call(
                self._finish,
                True,
                f"{meta['title']} by {meta['author']}\nSaved to {self.result}",
            )
        except parser.BookifyError as err:
            call(self._step, current, "failed")
            call(self._finish, False, str(err))
        except Exception as err:  # show unexpected errors instead of crashing
            call(self._step, current, "failed")
            call(self._log, f"{type(err).__name__}: {err}")
            call(self._finish, False, f"Unexpected error: {err}")

    # --- actions ---

    @on(Button.Pressed, "#open")
    def action_open_pdf(self) -> None:
        if self.result:
            self.app.open_url(self.result.as_uri())

    @on(Button.Pressed, "#again")
    def action_back(self) -> None:
        if self.running:
            self.notify("Still working — please wait a moment.", severity="warning")
            return
        self.app.pop_screen()

    @on(Button.Pressed, "#quit")
    def quit_app(self) -> None:
        self.app.exit()


class AO3BookifyTUI(App):
    CSS_PATH = "styles.tcss"
    TITLE = "AO3Bookify"
    BINDINGS = [Binding("ctrl+q", "quit", "Quit", priority=True)]

    def on_mount(self) -> None:
        self.push_screen(FormScreen())


if __name__ == "__main__":
    AO3BookifyTUI().run()
