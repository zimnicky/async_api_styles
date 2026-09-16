#!/usr/bin/env python3
"""
build_book.py - Generates an mdBook directly from async_api.md into the book/ folder.
Intermediate files are generated in a temporary build directory and cleaned up automatically.

Usage:
    python build_book.py              # Generate book into book/ folder from async_api.md
    python build_book.py --open       # Build and open in browser
    python build_book.py --serve      # Start local live-reload server at http://localhost:3000
    python build_book.py --clean      # Clean book/ folder before building
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r'[^a-z0-9]+', '_', text).strip('_')
    return text or "section"


def parse_frontmatter_and_content(filepath: str):
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    frontmatter_lines = []
    content_lines = []
    idx = 0
    if lines and lines[0].strip() == "---":
        idx = 1
        while idx < len(lines):
            line = lines[idx]
            if line.strip() == "---":
                idx += 1
                break
            frontmatter_lines.append(line)
            idx += 1
    content_lines = lines[idx:]

    title = "Asynchronous API"
    include_before_lines = []
    in_include_before = False
    for line in frontmatter_lines:
        if line.startswith("title:"):
            title = line.split(":", 1)[1].strip()
        elif line.startswith("include-before:"):
            in_include_before = True
        elif in_include_before:
            if line.startswith("    "):
                include_before_lines.append(line[4:])
            elif line.strip() == "":
                include_before_lines.append("\n")
            else:
                in_include_before = False

    preface = "".join(include_before_lines).strip()
    return title, preface, content_lines


def split_sections(content_lines):
    sections = []
    current_section = None
    in_code = False

    for line in content_lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            if current_section is not None:
                current_section["raw_lines"].append(line)
            continue

        if not in_code and line.startswith("# "):
            header_text = line[2:].strip()
            anchor_match = re.search(r"\{#([a-zA-Z0-9_\-]+)", header_text)
            anchor = anchor_match.group(1) if anchor_match else None
            clean_title = re.sub(r"\{[^}]*\}", "", header_text).strip()

            current_section = {
                "title": clean_title,
                "anchor": anchor,
                "raw_lines": []
            }
            sections.append(current_section)
        else:
            if current_section is not None:
                current_section["raw_lines"].append(line)

    return sections


def clean_line_markup(line: str) -> str:
    # Convert [Text]{.mark} to <mark>Text</mark>
    line = re.sub(r'\[([^\]]+)\]\{\.mark\}', r'<mark>\1</mark>', line)
    # Remove Pandoc classes {.unlisted .unnumbered}
    line = re.sub(r'\s*\{\.unlisted\s+\.unnumbered\}', '', line)
    # Convert 80-hyphen rules to standard markdown ---
    if re.match(r'^-{20,}$', line.strip()):
        return '---\n'
    # Clean code fences: ``` cpp {.numberLines} -> ```cpp
    code_fence_match = re.match(r'^```\s*([a-zA-Z0-9_-]*)\s*\{[^}]*\}', line)
    if code_fence_match:
        lang = code_fence_match.group(1).strip()
        return f"```{lang}\n"
    return line


def format_title(title: str) -> str:
    title = title.strip()
    if not title:
        return title
    special = {
        "SAMPLES": "Samples",
        "introduction": "Introduction",
        "setup with CMake + libcurl": "Setup with CMake + libcurl",
        "building blocking API": "Building blocking API",
        "building C-style callbacks API": "Building C-style callbacks API",
        "building C++20 coroutines API": "Building C++20 coroutines API",
        "building Fibers API": "Building Fibers API",
        "building std::future API": "Building std::future API",
        "building task API with .then() support": "Building Task API with .then() support",
        "building C++26 senders": "Building C++26 senders",
        "reactive streams": "Reactive streams",
        "synchronous requests": "Synchronous requests",
        "requests with callbacks": "Requests with callbacks",
        "requests with coroutines": "Requests with coroutines",
        "requests with fibers": "Requests with fibers",
        "polling requests with std::futures": "Polling requests with std::futures",
        "requests with Tasks .then()": "Requests with Tasks .then()",
        "requests with senders/std::execution": "Requests with senders / std::execution",
    }
    if title in special:
        return special[title]
    return title[0].upper() + title[1:]


def get_git_repo_url(root_dir: str) -> str:
    try:
        res = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=root_dir, capture_output=True, text=True, check=True
        )
        url = res.stdout.strip()
        if url.endswith(".git"):
            url = url[:-4]
        if url.startswith("git@github.com:"):
            url = "https://github.com/" + url[len("git@github.com:"):]
        return url or "https://github.com/zimnicky/async_api_styles"
    except Exception:
        return "https://github.com/zimnicky/async_api_styles"


def generate_book_sources(input_file: str, temp_build_dir: str, repo_url: str):
    """Generates the mdBook structure inside a temporary build directory."""
    src_dir = os.path.join(temp_build_dir, "src")
    os.makedirs(src_dir, exist_ok=True)

    title, preface, content_lines = parse_frontmatter_and_content(input_file)
    sections = split_sections(content_lines)

    known_filenames = {
        "intro": "intro.md",
        "cmake": "cmake.md",
        "libcurl_easy": "libcurl_easy.md",
        "libcurl_multi": "libcurl_multi.md",
        "coro_api": "coro_api.md",
        "fibers_api": "fibers_api.md",
        "futures_api": "futures_api.md",
        "then_api": "then_api.md",
        "senders_api": "senders_api.md",
    }

    title_slug_mapping = {
        "async with statefull/implicit callback (state.on_X.subscribe/delegates)": "stateful_callbacks.md",
        "coroutines on top polling tasks": "coro_polling.md",
        "reactive streams": "reactive_streams.md",
    }

    chapters = []
    anchor_to_loc = {}

    # Pass 1: register filenames and anchors
    for sec in sections:
        t = sec["title"]
        a = sec["anchor"]

        if t.upper() == "SAMPLES":
            samples_rel = "samples/README.md"
            anchor_to_loc["samples"] = (samples_rel, True)

            in_code = False
            current_sub = None
            sub_chapters = []

            for line in sec["raw_lines"]:
                stripped = line.strip()
                if stripped.startswith("```"):
                    in_code = not in_code
                    if current_sub:
                        current_sub["lines"].append(line)
                    continue

                if not in_code and line.startswith("## "):
                    h2_text = line[3:].strip()
                    sub_anchor_m = re.search(r"\{#([a-zA-Z0-9_\-]+)", h2_text)
                    sub_anchor = sub_anchor_m.group(1) if sub_anchor_m else None
                    sub_title = re.sub(r"\{[^}]*\}", "", h2_text).strip()
                    sub_fname = f"samples/{sub_anchor if sub_anchor else slugify(sub_title)}.md"
                    current_sub = {
                        "title": sub_title,
                        "anchor": sub_anchor,
                        "rel_path": sub_fname,
                        "lines": [f"# {format_title(sub_title)}\n\n"],
                        "is_sub": True
                    }
                    if sub_anchor:
                        anchor_to_loc[sub_anchor] = (sub_fname, True)
                    sub_chapters.append(current_sub)
                elif current_sub:
                    current_sub["lines"].append(line)

            readme_body = ["# Samples\n\nComplete sample applications demonstrating various asynchronous styles:\n\n"]
            for sub in sub_chapters:
                sub_name = format_title(sub["title"])
                sub_file = os.path.basename(sub["rel_path"])
                readme_body.append(f"- [{sub_name}]({sub_file})\n")
            readme_body.append("\n")

            chapters.append({
                "title": "Samples",
                "anchor": "samples",
                "rel_path": samples_rel,
                "lines": readme_body,
                "is_sub": False
            })
            chapters.extend(sub_chapters)
        else:
            if a in known_filenames:
                fname = known_filenames[a]
            elif t in title_slug_mapping:
                fname = title_slug_mapping[t]
            elif a:
                fname = f"{a}.md"
            else:
                fname = f"{slugify(t)}.md"

            if a:
                anchor_to_loc[a] = (fname, True)

            in_code = False
            for line in sec["raw_lines"]:
                stripped = line.strip()
                if stripped.startswith("```"):
                    in_code = not in_code
                    continue
                if not in_code and (line.startswith("## ") or line.startswith("### ")):
                    anchors_in_line = re.findall(r"\{#([a-zA-Z0-9_\-]+)", line)
                    for sub_a in anchors_in_line:
                        anchor_to_loc[sub_a] = (fname, False)

            sec_lines = [f"# {format_title(t)}\n\n"]
            if sec["anchor"]:
                sec_lines.insert(0, f'<a id="{sec["anchor"]}"></a>\n')

            if a == "intro" and preface:
                preface_block = f"# {title}\n\n{preface}\n\n---\n\n"
                sec_lines.insert(0, preface_block)

            content_text = "".join(sec["raw_lines"]).strip()
            if not content_text:
                sec_lines.append("*Work in progress.*\n")
            else:
                sec_lines.extend(sec["raw_lines"])

            chapters.append({
                "title": t,
                "anchor": a,
                "rel_path": fname,
                "lines": sec_lines,
                "is_sub": False
            })

    # Pass 2: write chapters and rewrite links
    for ch in chapters:
        ch_path = ch["rel_path"]
        ch_dir = os.path.dirname(ch_path)
        new_lines = []

        in_code = False
        for line in ch["lines"]:
            stripped = line.strip()
            if stripped.startswith("```"):
                in_code = not in_code
                new_lines.append(clean_line_markup(line))
                continue

            if in_code:
                new_lines.append(line)
                continue

            if line.startswith("#"):
                m = re.search(r"\{#([a-zA-Z0-9_\-]+)", line)
                if m:
                    heading_anchor = m.group(1)
                    clean_h = re.sub(r"\s*\{[^}]*\}", "", line)
                    line = f'<a id="{heading_anchor}"></a>\n{clean_h}'

            line = clean_line_markup(line)

            def replace_link(match):
                link_text = match.group(1)
                anchor = match.group(2)
                if anchor in anchor_to_loc:
                    target_file, is_file_top = anchor_to_loc[anchor]
                    if target_file == ch_path:
                        if is_file_top:
                            return f"[{link_text}]({os.path.basename(ch_path)})"
                        else:
                            return f"[{link_text}](#{anchor})"
                    else:
                        rel = os.path.relpath(target_file, ch_dir).replace("\\", "/")
                        if is_file_top:
                            return f"[{link_text}]({rel})"
                        else:
                            return f"[{link_text}]({rel}#{anchor})"
                return match.group(0)

            line = re.sub(r'\[([^\]]+)\]\(#([a-zA-Z0-9_\-]+)\)', replace_link, line)
            new_lines.append(line)

        full_dest = os.path.join(src_dir, ch_path)
        os.makedirs(os.path.dirname(full_dest), exist_ok=True)
        with open(full_dest, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

    # Pass 3: write SUMMARY.md
    summary_lines = ["# Summary\n\n"]
    for ch in chapters:
        title_disp = format_title(ch["title"])
        if ch.get("is_sub"):
            summary_lines.append(f"  - [{title_disp}]({ch['rel_path']})\n")
        else:
            summary_lines.append(f"- [{title_disp}]({ch['rel_path']})\n")

    with open(os.path.join(src_dir, "SUMMARY.md"), "w", encoding="utf-8") as f:
        f.writelines(summary_lines)

    # Pass 4: write book.toml inside temp build dir
    book_toml_content = f"""[book]
title = "{title}"
authors = ["Grisha Vanika"]
language = "en"
src = "src"

[build]
create-missing = false

[output.html]
git-repository-url = "{repo_url}"
default-theme = "light"
preferred-dark-theme = "navy"
smart-punctuation = true
mathjax-support = false

[output.html.search]
enable = true
limit-results = 30
use-boolean-and = true
boost-title = 2
boost-hierarchy = 1
boost-paragraph = 1
expand = true
heading-split-level = 3

[output.html.fold]
enable = true
level = 1
"""
    with open(os.path.join(temp_build_dir, "book.toml"), "w", encoding="utf-8") as f:
        f.write(book_toml_content)


def build_book(input_file="async_api.md", book_dir="book",
               open_browser=False, serve=False, clean=False):
    root_dir = os.path.dirname(os.path.abspath(input_file)) or "."
    repo_url = get_git_repo_url(root_dir)

    mdbook_cmd = shutil.which("mdbook")
    if not mdbook_cmd:
        print("[ERROR] 'mdbook' executable was not found in PATH.", file=sys.stderr)
        print("Please install it using one of the following commands:", file=sys.stderr)
        print("  winget install Rustlang.mdBook", file=sys.stderr)
        print("  cargo install mdbook", file=sys.stderr)
        sys.exit(1)

    full_book_dir = os.path.abspath(os.path.join(root_dir, book_dir))

    if clean:
        print(f"Cleaning '{book_dir}/' folder...")
        if os.path.exists(full_book_dir):
            shutil.rmtree(full_book_dir)

    # Use a temporary directory for intermediate mdBook files
    temp_dir_obj = tempfile.TemporaryDirectory(prefix="mdbook_build_")
    temp_dir = temp_dir_obj.name

    try:
        print(f"Generating book structure directly from '{input_file}'...")
        generate_book_sources(input_file, temp_dir, repo_url)

        if serve:
            print(f"Starting mdBook live-reload server at http://localhost:3000 ...")
            cmd = ["mdbook", "serve", temp_dir, "-d", full_book_dir]
            subprocess.run(cmd)
        else:
            print(f"Building book with mdBook into '{book_dir}/'...")
            cmd = ["mdbook", "build", temp_dir, "-d", full_book_dir]
            if open_browser:
                cmd.append("--open")
            res = subprocess.run(cmd, text=True)
            if res.returncode != 0:
                print(f"[ERROR] mdBook build failed with exit code {res.returncode}", file=sys.stderr)
                sys.exit(res.returncode)

            print(f"\n[SUCCESS] Book successfully generated in '{book_dir}/' folder from '{input_file}'!")
            print(f"Open '{os.path.join(full_book_dir, 'index.html')}' in your browser to view it.")
    finally:
        # Clean up temporary directory
        if not serve:
            temp_dir_obj.cleanup()


def main():
    parser = argparse.ArgumentParser(
        description="Build mdBook directly from async_api.md into book/ folder without leaving intermediate files."
    )
    parser.add_argument(
        "-i", "--input", default="async_api.md",
        help="Path to source markdown file (default: async_api.md)"
    )
    parser.add_argument(
        "-b", "--book-dir", default="book",
        help="Output directory for generated book (default: book)"
    )
    parser.add_argument(
        "-o", "--open", action="store_true",
        help="Open the built book in your default web browser"
    )
    parser.add_argument(
        "--serve", action="store_true",
        help="Start live-reloading dev server at http://localhost:3000"
    )
    parser.add_argument(
        "--clean", action="store_true",
        help="Clean book/ folder before building"
    )

    args = parser.parse_args()
    build_book(
        input_file=args.input,
        book_dir=args.book_dir,
        open_browser=args.open,
        serve=args.serve,
        clean=args.clean
    )


if __name__ == "__main__":
    main()
