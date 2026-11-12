"""Check local rendered links and the retained migrator URL; no network required."""
from html.parser import HTMLParser
from pathlib import Path
import sys
from urllib.parse import unquote, urlsplit


BASE = "/tg-selfhost-botapi"
PRIVATE_CONTENT = ("Dockerfile", "Dockerfile.downloads", "nginx.conf", "docker-entrypoint.sh",
                   "docker-compose.yml", "docker-compose.build.yml", "docker-compose.files.yml",
                   "docker-compose.downloads.yml", "migrate_off_to_self.sh", "tools", "data",
                   "examples", "media", "secrets", "files", "logs")


def check_private_content(root):
    return [f"Non-documentation content published: {name}"
            for name in PRIVATE_CONTENT if (root / name).exists()]


def private_site_paths(root, sentinels=()):
    """Return relative private artifact paths accidentally copied into a site."""
    root = Path(root)
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part in (".migration-state", ".migration-private", "files", "secrets", "examples", "logs", ".issue-flow") for part in relative.parts) or (
            path.name == ".env" or path.name.startswith(".env.") and path.name != ".env.example"
        ) or path.name in ("binding.key", "migration-helper.env", "Dockerfile.downloads", "docker-compose.downloads.yml", "docker-compose.secrets.yml", "nginx-main.conf") or (
            path.name.startswith("downloads.config.")
        ):
            yield relative
        elif path.is_file():
            # Recognize renamed private journal envelopes as well as paths.
            import json
            try:
                if path.stat().st_size <= 4194304:
                    raw=path.read_bytes()
                    if any(value.encode('utf-8') in raw for value in sentinels if value):
                        yield relative
                        continue
                    if path.suffix != '.json':
                        continue
                    value = json.loads(raw.decode('utf-8'))
                    if isinstance(value, dict) and {'state', 'mac'} <= set(value):
                        yield relative
            except (ValueError, UnicodeError, OSError):
                pass


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.ids = set()
        self.links = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.add(attrs["id"])
        for attribute in ("href", "src"):
            if attrs.get(attribute):
                self.links.append(attrs[attribute])


def check(root):
    root = root.resolve()
    pages = {path.resolve(): Page(path.read_text(encoding="utf-8")) for path in root.rglob("*.html")}
    errors = []
    import os
    sentinels=[os.environ.get('DOCS_PRIVACY_SENTINEL','')]
    errors.extend(f"Private content published: {path}" for path in private_site_paths(root,sentinels))
    for path, page in pages.items():
        for link in page.links:
            parsed = urlsplit(link)
            if parsed.netloc or parsed.scheme:
                continue
            url = unquote(parsed.path)
            if url.startswith("/"):
                if not (url == BASE or url.startswith(BASE + "/")):
                    errors.append(f"{path.relative_to(root)}: missing project prefix: {link}")
                    continue
                target = root / url[len(BASE):].lstrip("/")
            else:
                target = path.parent / url if url else path
            target = target.resolve()
            if not target.is_relative_to(root):
                errors.append(f"{path.relative_to(root)}: escapes site: {link}")
                continue
            if target.is_dir():
                target /= "index.html"
            if not target.is_file():
                errors.append(f"{path.relative_to(root)}: broken link: {link}")
            elif parsed.fragment and target in pages:
                if unquote(parsed.fragment) not in pages[target].ids:
                    errors.append(f"{path.relative_to(root)}: broken anchor: {link}")

    required = ["index.html", "docs/index.html", "tg_selfhost_botapi_migrator.html", "contributing.html"]
    for language in ("en", "ru"):
        required.append(f"docs/{language}/index.html")
        required.extend(f"docs/{language}/{name}.html" for name in
                        ("getting-started", "configuration", "migration", "maintenance"))
    for name in required:
        if not (root / name).is_file():
            errors.append(f"Missing page: {name}")

    source = Path(__file__).resolve().parents[1] / "tg_selfhost_botapi_migrator.html"
    retained = root / source.name
    if retained.is_file() and retained.read_bytes() != source.read_bytes():
        errors.append("The original migrator must be copied without changes")
    errors.extend(check_private_content(root))
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"Checked {len(pages)} HTML pages, internal links, language navigation and migrator compatibility.")


if __name__ == "__main__":
    check(Path(sys.argv[1]))
