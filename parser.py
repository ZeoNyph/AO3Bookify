import os
import re
import subprocess
import sys
import tempfile
from argparse import ArgumentParser, Namespace
from pathlib import Path
from typing import Callable, Tuple
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup, Tag
from playwright.sync_api import sync_playwright

parser: ArgumentParser
args: Namespace

CSS_FILE = Path(__file__).resolve().parent / "bookify.css"
USER_AGENT = "AO3Bookify/0.1 (+https://github.com/ZeoNyph/AO3Bookify)"


class BookifyError(Exception):
    """An error with a message that can be shown directly to the user."""


## Filter functions

NOTE_CLASSES = {"notes", "endnotes", "meta", "end"}
HEADING_CLASSES = {"heading", "title"}
SUMMARY_CLASSES = {"summary"}


def has_class(tag: Tag, names: set) -> bool:
    # Exact class names only, and never inside the fic text itself: authors use
    # their own classes there (e.g. "subtitle", "calendar") via work skins.
    # (#chapters itself is also .userstuff in AO3 downloads, so it doesn't count.)
    text = tag.find_parent(lambda t: has_userstuff(t) and t.get("id") != "chapters")
    return bool(names & set(tag.get("class") or [])) and text is None


def has_userstuff(tag: Tag) -> bool:
    return "userstuff" in (tag.get("class") or [])


## Helper functions


def remove_blocks(contents: BeautifulSoup, names: set):
    blocks = contents.find_all(lambda t: t.name == "div" and has_class(t, names))
    for block in blocks:
        if block.decomposed:  # was nested inside a block removed earlier
            continue
        head = block.find("h2", class_="heading")

        if head:
            block.insert_before(head)
        block.decompose()


def remove_chapter_text_headings(contents: BeautifulSoup):
    chp_text_headings = contents.find_all("h3", string="Chapter Text")
    for hd in chp_text_headings:
        hd.decompose()


def format_headings(contents: BeautifulSoup):
    headings = contents.find_all(lambda t: has_class(t, HEADING_CLASSES))
    for heading in headings:
        a_text = heading.a.extract().get_text() if heading.a else ""
        heading_text = heading.get_text()
        heading.string = a_text + heading_text.strip()
        # Not "meta": in AO3 downloads it also wraps the chapter heading.
        in_note = heading.find_parent(lambda t: has_class(t, NOTE_CLASSES - {"meta"}))
        heading.name = "strong" if in_note else "h2"


def remove_whitespace_paragraphs(contents: BeautifulSoup):
    ws = contents.find_all("p")
    for para in ws:
        if para.get_text(strip=True) == "" and len(para.find_all(recursive=False)) == 0:
            para.decompose()


def inject_css(contents: BeautifulSoup):
    contents.wrap(Tag(name="body"))
    contents.wrap(Tag(name="html"))
    contents.insert(0, Tag(name="head"))
    head = contents.find("head")
    head.append(Tag(name="meta", attrs={"charset": "utf-8"}))
    head.append(
        Tag(name="link", attrs={"rel": "stylesheet", "href": CSS_FILE.as_uri()})
    )


def write_to_pdf(input: BeautifulSoup, output: str):
    # Not using prettify() here: it puts inline tags on their own lines,
    # which adds stray spaces around italics, links, etc.
    fd, temp_file = tempfile.mkstemp(suffix=".html", prefix="ao3bookify-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as temp:
            temp.write("<!DOCTYPE html>\n" + str(input))
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_context().new_page()
                page.goto(Path(temp_file).as_uri(), wait_until="networkidle")
                page.pdf(path=output, prefer_css_page_size=True)
            finally:
                browser.close()
    finally:
        os.remove(temp_file)


def get_fic_metadata(contents: BeautifulSoup) -> dict:
    title = None
    # HTML download from AO3
    meta = contents.find("div", class_="meta")
    if meta and meta.h1:
        title = meta.h1.get_text().strip()
    # Page saved / fetched from the website
    if not title:
        title_tag = contents.find(class_="title heading") or contents.find(
            "h2", class_="title"
        )
        if title_tag:
            title = title_tag.get_text().strip()
    if not title and contents.title:
        title = contents.title.get_text().split("|")[0].strip()

    author_tag = contents.find("a", rel="author")
    author = author_tag.get_text().strip() if author_tag else "Anonymous"
    return {"title": title or "Untitled", "author": author}


def safe_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip(" .")
    return name or "fic"


def output_path(output: str | None, title: str) -> Path:
    path = Path(output).expanduser() if output else Path(f"{safe_filename(title)}.pdf")
    # Always end in .pdf, so "-o fic.html" can't overwrite the source HTML.
    if path.suffix.lower() != ".pdf":
        path = path.with_name(path.name + ".pdf")
    # Default name: never overwrite another fic's PDF with the same title.
    n = 2
    while not output and path.exists():
        path = path.with_name(f"{safe_filename(title)} ({n}).pdf")
        n += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def init_parser():
    global parser
    parser = ArgumentParser(
        prog="AO3Bookify",
        description="Python program that parses a HTML download of an AO3 fic.",
    )
    parser.add_argument(
        "path",
        help="The path to the HTML file containing the fic. Can also be a URL to the fic itself.",
    )
    parser.add_argument("-o", "--output")
    parser.add_argument(
        "--no-notes",
        action="store_true",
        default=False,
        help="Remove author notes from the output.",
    )
    return parser


def is_url(path: str) -> bool:
    return urlparse(path.strip()).scheme in ("http", "https")


def verify_url(url: str) -> Tuple[bool, str]:
    parsed_url = urlparse(url.strip())
    if parsed_url.scheme not in ("http", "https") or not (
        parsed_url.netloc == "archiveofourown.org"
        or parsed_url.netloc.endswith(".archiveofourown.org")
    ):
        return (False, "URL must be a valid AO3 link!")
    path_split = [p for p in parsed_url.path.split("/") if p]
    if not path_split or path_split[0] != "works" or len(path_split) < 2:
        return (False, "URL must point to a work on AO3!")
    if not path_split[1].isdigit():
        return (False, "URL must have a valid work ID!")
    return (True, "")


def verify_file(path: str) -> Tuple[bool, str]:
    file = Path(path.strip()).expanduser()
    if not path.strip():
        return (False, "Please enter a file path.")
    if not file.is_file():
        return (False, "That file doesn't exist!")
    if file.suffix.lower() not in (".html", ".htm"):
        return (False, "File must be an HTML file (.html or .htm)!")
    return (True, "")


def full_work_url(url: str) -> str:
    parsed_url = urlparse(url.strip())
    parts = [p for p in parsed_url.path.split("/") if p]
    # /works/<id>/chapters/<id> -> /works/<id>
    parsed_url = parsed_url._replace(
        scheme="https",
        path="/" + "/".join(parts[:2]),
        query="view_full_work=true&view_adult=true",
        fragment="",
    )
    return parsed_url.geturl()


def get_from_url(url: str) -> str:
    try:
        response = requests.get(
            full_work_url(url), headers={"User-Agent": USER_AGENT}, timeout=120
        )
    except requests.exceptions.Timeout:
        raise BookifyError("AO3 took too long to respond. Please try again later.")
    except requests.exceptions.ConnectionError:
        raise BookifyError(
            "Oops! Looks like something went wrong while trying to request the fic.\n"
            "Make sure you're connected to the Internet and that your ISP doesn't block AO3!"
        )
    if response.status_code == 404:
        raise BookifyError("That work doesn't exist (AO3 returned 404).")
    if response.status_code == 429:
        raise BookifyError("AO3 is rate-limiting requests. Wait a bit and try again.")
    if response.status_code >= 400:
        raise BookifyError(f"AO3 returned an error (HTTP {response.status_code}).")
    if "/users/login" in response.url:
        raise BookifyError(
            "This work is only visible to logged-in users.\n"
            "Download it as HTML from AO3 in your browser and use the file option instead."
        )
    return response.text


def get_from_file(file: str) -> str:
    try:
        with open(Path(file.strip()).expanduser(), "rt", encoding="utf8") as fic:
            return fic.read()
    except OSError as err:
        raise BookifyError(f"Couldn't read the file: {err.strerror}")
    except UnicodeDecodeError:
        raise BookifyError("Couldn't read the file: it isn't valid UTF-8 text.")


def load_fic(path: str) -> BeautifulSoup:
    if is_url(path):
        ok, msg = verify_url(path)
        if not ok:
            raise BookifyError(msg)
        content = get_from_url(path)
    else:
        ok, msg = verify_file(path)
        if not ok:
            raise BookifyError(msg)
        content = get_from_file(path)
    return BeautifulSoup(content, "lxml")


def format_fic(soup: BeautifulSoup, no_notes: bool = False) -> Tag:
    contents = soup.find("div", id="chapters")
    if contents is None:
        raise BookifyError(
            "Couldn't find the fic's chapters in this page.\n"
            "Make sure it's a full AO3 work (HTML download or 'Entire Work' view)."
        )
    if no_notes:
        remove_blocks(contents, NOTE_CLASSES)
    remove_blocks(contents, SUMMARY_CLASSES)
    remove_chapter_text_headings(contents)
    format_headings(contents)
    remove_whitespace_paragraphs(contents)
    inject_css(contents)
    return contents


def chromium_installed() -> bool:
    try:
        with sync_playwright() as playwright:
            return Path(playwright.chromium.executable_path).exists()
    except Exception:
        return False


def install_chromium(log: Callable[[str], None] = print):
    proc = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    for line in proc.stdout.splitlines():
        if line.strip():
            log(line.strip())
    if proc.returncode != 0:
        raise BookifyError("Failed to install Chromium for PDF conversion.")


def check_playwright():
    if not chromium_installed():
        print("Installing Playwright dependencies for PDF conversion...")
        install_chromium()


## Main loop

if __name__ == "__main__":
    try:
        init_parser()
        args = parser.parse_args()

        if verify_url(args.path)[0]:
            print(
                "Requesting fic data from AO3...\n[Depending on the fic, this may take a while.]"
            )
        parsed_html = load_fic(args.path)
        data = get_fic_metadata(parsed_html)
        print(f"Bookifying {data['title']} by {data['author']}")
        contents = format_fic(parsed_html, args.no_notes)

        check_playwright()

        output = output_path(args.output, data["title"])
        write_to_pdf(contents, str(output))
        print(f"Saved to {output}")
    except BookifyError as err:
        print(err, file=sys.stderr)
        exit(-1)
    except KeyboardInterrupt:
        print("\nExiting AO3Bookify...")
        exit(1)
