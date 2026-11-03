
"""MGPD ODMP Memorial Wall updater.

Collects the first 10 homepage officer cards and matches them
to ODMP incident records. Preserves existing data on failure.

Automated access and content reuse require ODMP authorization.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

BASE = "https://www.odmp.org/"
FEED = "https://www.odmp.org/get/get_recent"
OUT = Path("docs")
DATA = OUT / "memorials.json"

OUT.mkdir(parents=True, exist_ok=True)


def clean(element):
    return element.get_text(" ", strip=True) if element else ""


def officer_id_from_photo(photo):
    match = re.search(
        r"/media/image/officer/(\d+)/",
        photo or ""
    )
    return match.group(1) if match else None


def homepage_officers(page):
    response = page.goto(
        BASE,
        wait_until="domcontentloaded",
        timeout=45000
    )

    if response and response.status >= 400:
        raise RuntimeError(
            f"Homepage HTTP {response.status}"
        )

    page.locator("app-officercard").first.wait_for(
        state="attached",
        timeout=30000
    )

    page.wait_for_timeout(3000)

    soup = BeautifulSoup(
        page.content(),
        "html.parser"
    )

    officers = []
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
            photo = urljoin(
                BASE,
                image.get("src")
                or image.get("data-src")
                or ""
            )

        officer_id = officer_id_from_photo(photo)

        if not all([
            name, agency, eow, photo, officer_id
        ]):
            continue

        if officer_id in seen:
            continue

        seen.add(officer_id)

        officers.append({
            "id": officer_id,
            "name": name,
            "agency": agency,
            "eow": eow,
            "photo": photo
        })

        if len(officers) == 10:
            break

    return officers


def get_incident_records():
    response = requests.get(
        FEED,
        timeout=45,
        headers={
            "Accept": "application/json"
        }
    )

    response.raise_for_status()
    payload = response.json()

    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        records = payload.get("data") or []
    else:
        records = []

    if not isinstance(records, list):
        raise RuntimeError(
            "Unexpected ODMP incident data format."
        )

    return {
        str(record["id"]): record
        for record in records
        if isinstance(record, dict)
        and record.get("id") is not None
    }


def short_story(description):
    """Use a short incident excerpt, not the full biography."""

    description = re.sub(
        r"\s+",
        " ",
        description or ""
    ).strip()

    if not description:
        return ""

    sentences = re.split(
        r"(?<=[.!?])\s+",
        description
    )

    story = ""

    for sentence in sentences:
        candidate = (
            story + " " + sentence
        ).strip()

        if len(candidate) > 330:
            break

        story = candidate

        if len(story) >= 150:
            break

    if not story:
        words = description.split()
        story = " ".join(words[:35]).rstrip(
            " ,;:"
        )

        if len(words) > 35:
            story += "…"

    return story


def build_records(homepage, incidents):
    result = []

    for officer in homepage:
        record = incidents.get(officer["id"])

        if not record:
            raise RuntimeError(
                "No incident record for "
                + officer["name"]
            )

        incident = record.get(
            "incident_description"
        ) or ""

        story = short_story(incident)

        if not story:
            raise RuntimeError(
                "Missing incident story for "
                + officer["name"]
            )

        full_name = (
            record.get("full_name") or ""
        ).strip()

        homepage_name = officer["name"].lower()

        # Verify that the ID corresponds to the
        # same officer, not another incident record.
        if full_name:
            last_name = full_name.split()[-1].lower()

            if last_name not in homepage_name:
                raise RuntimeError(
                    "Officer identity mismatch: "
                    + officer["name"]
                )

        memorial_path = record.get("url") or ""

        if not re.match(
            r"^/officer/\d+",
            memorial_path
        ):
            raise RuntimeError(
                "Missing memorial URL for "
                + officer["name"]
            )

        result.append({
            "name": officer["name"],
            "agency": officer["agency"],
            "eow": officer["eow"],
            "photo": officer["photo"],
            "story": story,
            "url": urljoin(BASE, memorial_path)
        })

    return result


def save_diagnostics(page, message):
    print("DIAGNOSTIC:", message)

    try:
        page.screenshot(
            path=str(OUT / "odmp-debug.png"),
            full_page=True
        )

        (OUT / "odmp-debug.html").write_text(
            page.content(),
            encoding="utf-8"
        )

    except Exception as error:
        print("Diagnostic capture failed:", error)


def main():
    print("Collecting ODMP homepage officers.")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True
        )

        page = browser.new_page(
            viewport={
                "width": 1440,
                "height": 900
            }
        )

        try:
            homepage = homepage_officers(page)

            if len(homepage) != 10:
                raise RuntimeError(
                    f"Expected 10 officers, "
                    f"found {len(homepage)}."
                )

        except Exception as error:
            save_diagnostics(page, str(error))
            raise

        finally:
            browser.close()

    print("Retrieving ODMP incident descriptions.")

    incidents = get_incident_records()

    records = build_records(
        homepage,
        incidents
    )

    if len(records) != 10:
        raise RuntimeError(
            "Incomplete memorial collection."
        )

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

    print("SUCCESS: Updated 10 memorials with stories.")

    for index, record in enumerate(
        records,
        start=1
    ):
        print(
            f"{index}. {record['name']} - "
            f"{record['story']}"
        )


if __name__ == "__main__":
    main()
