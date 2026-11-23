# this_file: print_guide.py
"""Render the combined guide within the regular Fly page lifecycle."""

from importlib.resources import files as package_files

from mkdocs.config.defaults import MkDocsConfig
from mkdocs.structure.files import File, Files
from mkdocs.structure.nav import Navigation
from mkdocs.structure.pages import Page
from mkdocs_print_site_plugin.renderer import Renderer
from mkdocs_print_site_plugin.urls import get_page_key


def on_files(files: Files, *, config: MkDocsConfig) -> None:
    """Publish print-site's bundled print styles for the guide template."""
    styles = package_files("mkdocs_print_site_plugin").joinpath("css")
    for name in ("print-site.css", "print-site-materialx.css"):
        files.append(File.generated(config, f"css/{name}", content=styles.joinpath(name).read_bytes()))


def on_page_context(context: dict, *, page: Page, config: MkDocsConfig, nav: Navigation) -> None:
    """Give print-site the finished pages, including the generated topic index."""
    if page.file.src_uri == "print_page.md":
        chapters = {get_page_key(chapter.url): chapter for chapter in nav.pages if chapter is not page}
        for chapter in chapters.values():
            # Keep print-site's injected tags on a separate line so it namespaces the first heading ID.
            chapter.html = "\n" + chapter.content
        renderer = Renderer(
            {"enumerate_headings": True, "enumerate_figures": True, "toc_depth": 3},
            mkdocs_config=config,
            print_page=page,
        )
        renderer.items = nav.items
        page.content, page.toc = renderer.write_combined()
        # print-site normalizes a relative link back to the home chapter as ".".
        page.content = page.content.replace('href="#."', 'href="#index"').replace('href="#.-', 'href="#index-')
        context["print_chapters"] = chapters
