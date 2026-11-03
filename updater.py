
"""MGPD ODMP Memorial Wall daily updater.

Reads the first 10 officer cards from the ODMP homepage.
Does not invent officer information.
Preserves the existing feed if an update fails.

Confirm ODMP permission before automated use or redistribution.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

BASE = "https://www.odmp.org/"
OUT = Path("docs")
DATA = OUT / "memorials.json"

OUT.mkdir(parents=True, exist_ok=True)


def clean(element):
    if element is None:
        return ""
    return element.get_text(" ", strip=True)


def valid_photo(url):
    if not url:
        return ""

    url = urljoin(BASE, url)
    parsed = urlparse(url)

    if parsed.scheme != "https":
        return ""

    if parsed.netloc not in ("odmp.org", "www.odmp.org"):
        return ""

    return url


def collect_cards(soup):
    """Read officer cards in their homepage DOM order."""

    records = []
    seen = set()

    for card in soup.select("app-officercard"):
        name = clean(card.select_one(".rank-name"))
        agency = clean(card.select_one(".agency"))
        eow = clean(card.select_one(".eow-date"))

        image = card.select_one(
            ".card-image-container img"
        )

        photo = ""

        if image:
            photo = valid_photo(
                image.get("src")
                or image.get("data-src")
                or ""
            )

        if not (name and agency and eow and photo):
            continue

        # Use the officer's photograph URL as a unique key.
        # The carousel may contain duplicate cards.
        officer_id = photo

        if officer_id in seen:
            continue

        seen.add(officer_id)

        records.append({
            "name": name,
            "agency": agency,
            "eow": eow,
            "photo": photo,
            "story": (
                "We honor this officer's life, "
                "service, and sacrifice. "
                "Visit ODMP.org for the full memorial."
            ),
            "url": BASE
        })

        if len(records) == 10:
            break

    return records


def save_diagnostics(page, reason):
    print("DIAGNOSTIC:", reason)
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


def validate(records):
    if len(records) != 10:
        raise RuntimeError(
            f"Expected 10 officers; found {len(records)}."
        )

    for index, officer in enumerate(records, start=1):
        if not all([
            officer["name"],
            officer["agency"],
            officer["eow"],
            officer["photo"]
        ]):
            raise RuntimeError(
                f"Officer {index} has missing information."
            )

        if not re.search(
            r"\b\d{4}\b",
            officer["eow"]
        ):
            raise RuntimeError(
                f"Officer {index} has an invalid EOW date."
            )


def main():
    print("Starting ODMP homepage update.")

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
            response = page.goto(
                BASE,
                wait_until="domcontentloaded",
                timeout=45000
            )

            if response and response.status >= 400:
                raise RuntimeError(
                    f"ODMP HTTP error: {response.status}"
                )

            # ODMP renders its cards using JavaScript.
            page.locator(
                "app-officercard"
            ).first.wait_for(
                state="attached",
                timeout=30000
            )

            page.wait_for_timeout(3000)

            soup = BeautifulSoup(
                page.content(),
                "html.parser"
            )

            records = collect_cards(soup)

            print(
                "Valid homepage cards found:",
                len(records)
            )

            if len(records) != 10:
                save_diagnostics(
                    page,
                    "Could not collect 10 valid officer cards."
                )

            validate(records)

        except Exception as error:
            save_diagnostics(
                page,
                f"Update failed: {error}"
            )
            raise

        finally:
            browser.close()

    payload = {
        "source": BASE,
        "updated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "officers": records
    }

    temporary = DATA.with_suffix(".tmp")

    temporary.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

    temporary.replace(DATA)

    print("SUCCESS: Updated 10 ODMP officers.")

    for index, officer in enumerate(records, start=1):
        print(
            f"{index}. {officer['name']} | "
            f"{officer['agency']} | "
            f"EOW: {officer['eow']}"
        )


if __name__ == "__main__":
    main()
