
"""ODMP memorial wall updater.

Collects the first 10 officer memorials from the ODMP homepage.
Preserves existing data if retrieval or validation fails.

Use only where automated access and image reuse are permitted.
"""

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

BASE = "https://www.odmp.org/"
OUT = Path("docs")
DATA = OUT / "memorials.json"
IMAGES = OUT / "images"

OUT.mkdir(parents=True, exist_ok=True)
IMAGES.mkdir(parents=True, exist_ok=True)


def text(node):
    return node.get_text(" ", strip=True) if node else ""


def officer_url(href):
    if not href:
        return None

    url = urljoin(BASE, href.split("#")[0])
    parsed = urlparse(url)

    if parsed.netloc not in ("www.odmp.org", "odmp.org"):
        return None

    if re.match(r"^/officer/\d+(?:/|$)", parsed.path):
        return url

    return None


def browse(page, url):
    response = page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=45000
    )

    page.wait_for_timeout(5000)

    if response and response.status >= 400:
        raise RuntimeError(
            f"ODMP returned HTTP {response.status} at {url}"
        )

    return BeautifulSoup(page.content(), "html.parser")


def homepage_links(soup):
    candidates = []

    for node in soup.select("section, main, div"):
        heading = node.find(["h1", "h2", "h3"])

        label = " ".join([
            str(node.get("id", "")),
            " ".join(node.get("class", [])),
            text(heading)
        ]).lower()

        if any(term in label for term in (
            "recent",
            "latest",
            "fallen officers",
            "recently fallen"
        )):
            links = [
                officer_url(a.get("href"))
                for a in node.select("a[href]")
            ]

            links = list(dict.fromkeys(
                url for url in links if url
            ))

            if len(links) >= 10:
                candidates.append((len(links), links))

    if candidates:
        return sorted(
            candidates,
            key=lambda item: item[0]
        )[0][1][:10]

    links = [
        officer_url(a.get("href"))
        for a in soup.select("a[href]")
    ]

    return list(dict.fromkeys(
        url for url in links if url
    ))[:10]


def meta(soup, key, attr="property"):
    tag = soup.find("meta", attrs={attr: key})
    return (tag.get("content") or "").strip() if tag else ""


def extract(page, url):
    soup = browse(page, url)

    heading = soup.find("h1")
    name = text(heading) or meta(soup, "og:title")

    name = re.sub(
        r"\s*[-|]\s*Officer Down Memorial Page.*$",
        "",
        name,
        flags=re.I
    ).strip()

    agency = ""

    for element in soup.select(
        '[class*="agency"], '
        '[class*="department"], '
        '[data-testid*="agency"]'
    ):
        value = text(element)

        if 4 < len(value) < 180:
            agency = value
            break

    full_text = text(soup)

    match = re.search(
        r"(?:End of Watch|EOW)\s*[:\-]?\s*"
        r"(?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|"
        r"Saturday|Sunday),?\s*)?"
        r"(?:January|February|March|April|May|June|July|"
        r"August|September|October|November|December)"
        r"\s+\d{1,2},?\s+\d{4}",
        full_text,
        re.I
    )

    eow = ""

    if match:
        eow = re.sub(
            r"^(?:End of Watch|EOW)\s*[:\- ]*",
            "",
            match.group(0),
            flags=re.I
        ).strip()

    photo = meta(soup, "og:image")

    if not photo:
        image = soup.select_one("main img, article img")

        if image:
            photo = (
                image.get("src")
                or image.get("data-src")
                or ""
            )

    photo = urljoin(BASE, photo) if photo else ""

    story = ""

    for element in soup.select(
        '[class*="bio"], '
        '[class*="incident"], '
        '[class*="narrative"], '
        "article p, main p"
    ):
        value = text(element)

        if (
            len(value) > 90
            and not any(term in value.lower() for term in (
                "cookie policy",
                "privacy policy",
                "sign up"
            ))
        ):
            story = value[:520]

            if len(value) > 520:
                story = story.rsplit(" ", 1)[0] + "…"

            break

    if not (name and agency and eow):
        raise ValueError(
            f"Incomplete officer record: {url}. "
            f"Name={bool(name)}, "
            f"Agency={bool(agency)}, "
            f"EOW={bool(eow)}"
        )

    return {
        "name": name,
        "agency": agency,
        "eow": eow,
        "story": story or (
            "Read the full memorial at ODMP.org."
        ),
        "photo": photo,
        "url": url
    }


def save_image(session, record):
    url = record.get("photo")

    if not url:
        return

    if urlparse(url).netloc not in (
        "www.odmp.org",
        "odmp.org"
    ):
        return

    try:
        response = session.get(url, timeout=15)
        response.raise_for_status()

        mime = response.headers.get(
            "content-type", ""
        ).split(";")[0]

        extension = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp"
        }.get(mime)

        if not extension:
            return

        if len(response.content) > 5_000_000:
            return

        filename = (
            hashlib.sha256(
                record["url"].encode()
            ).hexdigest()[:18]
            + extension
        )

        (IMAGES / filename).write_bytes(
            response.content
        )

        record["photo"] = "images/" + filename

    except requests.RequestException as error:
        print("Image unavailable:", error)


def save_diagnostics(page, reason):
    print("ODMP diagnostic:", reason)
    print("Current URL:", page.url)

    try:
        print("Page title:", page.title())

        page.screenshot(
            path=str(OUT / "odmp-debug.png"),
            full_page=True,
            timeout=15000
        )

        (OUT / "odmp-debug.html").write_text(
            page.content(),
            encoding="utf-8"
        )

        print("Diagnostic files saved.")

    except Exception as error:
        print("Diagnostic capture failed:", error)


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True
        )

        context = browser.new_context(
            viewport={
                "width": 1440,
                "height": 900
            }
        )

        page = context.new_page()

        try:
            soup = browse(page, BASE)
            urls = homepage_links(soup)

            print(
                "Homepage officer links found:",
                len(urls)
            )

            if len(urls) != 10:
                save_diagnostics(
                    page,
                    f"Expected 10 officer links, "
                    f"found {len(urls)}."
                )

                raise RuntimeError(
                    f"Found {len(urls)} homepage "
                    "officer links, expected exactly 10. "
                    "Existing data preserved."
                )

            records = []

            for url in urls:
                print("Retrieving:", url)

                try:
                    record = extract(page, url)
                    records.append(record)

                except Exception as error:
                    save_diagnostics(
                        page,
                        f"Officer extraction failed: {error}"
                    )
                    raise

        except Exception as error:
            print("ODMP update failed:", error)
            raise

        finally:
            browser.close()

    with requests.Session() as session:
        for record in records:
            save_image(session, record)

    payload = {
        "source": BASE,
        "updated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "officers": records
    }

    temporary_file = DATA.with_suffix(".tmp")

    temporary_file.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

    temporary_file.replace(DATA)

    print("Successfully updated 10 memorials.")

    for record in records:
        print("-", record["name"])


if __name__ == "__main__":
    main()
