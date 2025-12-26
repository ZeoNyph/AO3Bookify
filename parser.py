import os
import subprocess
import sys
from argparse import ArgumentParser, Namespace
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup, Tag
from playwright.sync_api import sync_playwright
from requests.exceptions import ConnectionError

parser: ArgumentParser
args: Namespace

filepath: str
temp_file: str = "./tmp.html"

## Filter functions


def is_note(css_class) -> bool:
    return css_class is not None and (
        "notes" in css_class or "meta" in css_class or "end" in css_class
    )


def is_heading(css_class) -> bool:
    return css_class is not None and ("heading" in css_class or "title" in css_class)


def is_summary(css_class) -> bool:
    return css_class is not None and "summary" in css_class


## Helper functions


def remove_summary(contents: BeautifulSoup):
    summaries = contents.find_all("div", attrs=is_summary)
    for summary in summaries:
        head = summary.find("h2", class_="heading")

        if head:
            summary.insert_before(head)
        summary.decompose()


def remove_author_notes(contents: BeautifulSoup):
    notes = contents.find_all("div", attrs=is_note)
    for note in notes:
        head = note.find("h2", class_="heading")

        if head:
            note.insert_before(head)
        note.decompose()


def remove_chapter_text_headings(contents: BeautifulSoup):
    chp_text_headings = contents.find_all("h3", string="Chapter Text")
    for hd in chp_text_headings:
        hd.decompose()


def format_headings(contents: BeautifulSoup):
    headings = contents.find_all(class_=is_heading)
    for heading in headings:
        a_text = heading.a.extract().get_text() if heading.a else ""
        heading_text = heading.get_text()
        heading.string = a_text + heading_text.strip()
        heading.name = "strong" if heading.find_parent(is_note) else "h2"


def remove_whitespace_paragraphs(contents: BeautifulSoup):
    ws = contents.find_all("p")
    for para in ws:
        if para.get_text(strip=True) == "" and len(para.find_all(recursive=False)) == 0:
            para.decompose()


def inject_css(contents: BeautifulSoup):
    contents.wrap(Tag(name="body"))
    contents.wrap(Tag(name="html"))
    contents.insert(0, Tag(name="head"))
    contents.find("head").append(
        Tag(name="link", attrs={"rel": "stylesheet", "href": f"bookify.css"})
    )


def write_to_pdf(input: BeautifulSoup, output: str):
    if os.path.exists(temp_file):
        os.remove(temp_file)
    with open(temp_file, "x", encoding="utf-8") as temp:
        temp.write(input.prettify())
    with sync_playwright() as playwright:
        chr = playwright.chromium
        browser = chr.launch()
        context = browser.new_context()
        page = context.new_page()
        page.goto(f"file://{os.path.abspath(temp_file)}")
        page.pdf(path=output, prefer_css_page_size=True)
    os.remove(temp_file)


def get_fic_metadata(contents: BeautifulSoup) -> dict:
    title = (
        contents.find("div", class_="meta").h1.get_text().strip()
        if contents.find("div", class_="meta")
        else None
    )
    if not title:
        title = contents.find("div", class_={"preface", "group"}).h2.get_text().strip()
    author = contents.find("a", rel="author").get_text().strip()
    return {"title": title, "author": author}


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


def get_from_url(url: str) -> str:
    parsed_url = urlparse(url)
    relative_path = parsed_url.path
    if "chapters" in relative_path:
        parts = relative_path.split("/")
        relative_path = "/".join(parts[:3])
        parsed_url = parsed_url._replace(path=relative_path)
    if not parsed_url.query.startswith("view_full_work"):
        parsed_url = parsed_url._replace(query="view_full_work=true")
    try:
        contents = requests.get(parsed_url.geturl())
        return contents.text
    except ConnectionError:
        print(
            "Oops! Looks like something went wrong while trying to request the fic.\nMake sure you're connected to the Internet and that your ISP doesn't block AO3!",
            file=sys.stderr,
        )
        exit(-1)


def get_from_file(file: str) -> str:
    with open(file, "rt", encoding="utf8") as fic:
        return fic.read()


def parse_fic(path: str) -> BeautifulSoup:
    content = ""
    if path.startswith("https://archiveofourown.org"):
        print(
            "Requesting fic data from AO3...\n[Depending on the fic, this may take a while.]"
        )
        content = get_from_url(path)
    elif path.endswith(".html"):
        content = get_from_file(path)
    else:
        print("Path not supported")
    return BeautifulSoup(content, "lxml")


def check_playwright():
    proc = subprocess.run(
        ["uv", "run", "playwright", "install", "--list"], stdout=subprocess.PIPE
    )
    out = proc.stdout.decode().strip()
    if out == "" or proc.returncode != 0:
        print("Installing Playwright dependencies for PDF conversion...")
        subprocess.run(["uv", "run", "playwright", "install", "chromium"])


## Main loop

if __name__ == "__main__":
    try:
        init_parser()
        args = parser.parse_args()

        check_playwright()

        parsed_html = parse_fic(args.path)
        data = get_fic_metadata(parsed_html)
        print(f"Bookifying {data['title']} by {data['author']}")
        contents = parsed_html.find("div", id="chapters")
        # Format document
        if args.no_notes:
            remove_author_notes(contents)
        remove_summary(contents)
        remove_chapter_text_headings(contents)
        format_headings(contents)
        remove_whitespace_paragraphs(contents)
        inject_css(contents)

        output = f"{data['title']}.pdf" if args.output is None else args.output
        write_to_pdf(contents, output)
    except KeyboardInterrupt:
        print("\nExiting AO3Bookify...")
        exit(1)
