from bs4 import BeautifulSoup
from argparse import ArgumentParser, Namespace
from weasyprint import HTML, CSS
import os, platform

parser : ArgumentParser
args : Namespace

pdf_stylesheet : str = """
@page {
  size: 110mm 170mm;
}
@page :left {
  margin: 12mm 10mm 20mm 15mm;
  @bottom-left { content: counter(page) }
  @top-right { content: string(heading); font-variant: small-caps }
}
@page :right {
  margin: 12mm 20mm 12mm 10mm;
  @top-left { content: string(heading); font-variant: small-caps }
  @bottom-right { content: counter(page) }
}
@page :blank {
  @top-right { content: none }
  @top-left { content: none }
}
@page :clean {
  @top-right { content: none }
  @top-left { content: none }
}

img {
  display: none;
}

html {
  font-size: 8pt;
}
body {
  margin: 0;
}
section {
  break-after: right;
  padding-top: 25mm;
}
aside {
  display: none;
}

h1 {
  break-after: right;
  font-size: 2.6em;
  font-weight: normal;
  margin: 3em 0;
  page: clean;
}
h2 {
  break-before: always;
  font-size: 1.4em;
  font-variant: small-caps;
  font-weight: normal;
  margin: 0 0 1em;
  page: clean;
  string-set: heading content();
  text-align: center;
}
p {
  hyphens: auto;
  margin: 0;
  text-align: justify;
  text-indent: 1em;
}
dd {
  margin: 0 0 0 1em;
}
br::after {
  content: '';
  display: inline-block;
  width: 0.78em;
}

.fullpage {
  display: none;
}
"""

## Filter functions

def is_note(css_class) -> bool:
    return css_class is not None and ("notes" in css_class or "meta group" in css_class or "meta" in css_class)

def is_heading(css_class) -> bool:
    return css_class is not None and ("heading" in css_class or "title" in css_class)

## Helper functions

def remove_author_notes(contents: BeautifulSoup) -> BeautifulSoup:
    notes = contents.find_all('div', class_=is_note)
    for note in notes:
        head = note.find("h2", class_='heading')
        
        if head:
            note.insert_before(head)
        note.decompose()
    return contents

def remove_chapter_text_headings(contents: BeautifulSoup) -> BeautifulSoup:
    chp_text_headings = contents.find_all('h3', string="Chapter Text")
    for hd in chp_text_headings:
        hd.decompose()
    return contents

def format_headings(contents: BeautifulSoup) -> BeautifulSoup:
    headings = contents.find_all(class_=is_heading)
    for heading in headings:
        a_text = heading.a.extract().get_text() if heading.a else ""
        heading_text = heading.get_text()
        heading.string = a_text + heading_text.strip()
        heading.name = 'h2'
    return contents

def write_to_pdf(input: BeautifulSoup, filepath: str):
    if not filepath.endswith(".pdf"):
        filepath += ".pdf"
    css = CSS(string=pdf_stylesheet)
    HTML(string=str(input)).write_pdf(target=filepath, stylesheets=[css])
    print(f"File saved at: {os.path.abspath(filepath)}")

def get_fic_metadata(contents: BeautifulSoup) -> dict:
    
    title = contents.find("div", class_="meta").h1.get_text().strip() if contents.find("div", class_="meta") else None
    if not title:
      title = contents.find("div", class_={"preface", "group"}).h2.get_text().strip()
    author = contents.find("a", rel="author").get_text().strip()
    return {
        "title": title,
        "author": author
    }

def init_parser():
    global parser
    parser = ArgumentParser(
        prog="AO3Bookify",
        description="Python program that parses a HTML download of an AO3 fic."
    )
    parser.add_argument('file')
    parser.add_argument('-o', '--output')
    parser.add_argument('--no-notes', action='store_true', default=False, help="Remove author notes from the output.")
    return parser

## Main loop

if __name__ == "__main__":
    init_parser()
    args = parser.parse_args()

    with open(os.path.abspath(args.file), 'rt') as fic:
        parsed_html = BeautifulSoup(fic, "lxml")
        data = get_fic_metadata(parsed_html)
        print(f"Bookifying {data['title']} by {data['author']}")
        contents = parsed_html.find('div', id="chapters")
        if args.no_notes:
            contents = remove_author_notes(contents)
        contents = remove_chapter_text_headings(contents)
        contents = format_headings(contents)

    filepath = f"{data["title"]}.pdf" if args.output is None else args.output
    write_to_pdf(contents, filepath=filepath)
        
    
