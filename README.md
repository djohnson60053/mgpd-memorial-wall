# Morton Grove Police — ODMP Memorial Wall

Static 16:9 display for Yodeck Fire TV Stick, hosted with GitHub Pages. GitHub Actions attempts to collect the **first ten officer memorial links on the ODMP homepage** daily at 12:17 UTC. Each slide runs for **30 seconds**. The browser refreshes its feed every 24 hours (a page reload also refreshes it).

## Setup (no new hosting account beyond GitHub)

1. Sign in to GitHub and create a **public** repository, for example `mgpd-memorial-wall`.
2. Upload **all files and folders from this ZIP** to the repository's root. Hidden `.github/workflows/update.yml` must be preserved. Easiest: unzip locally, use GitHub **Add file → Upload files** and verify the `.github` workflow is present; if GitHub's web uploader omits hidden files, create `.github/workflows/update.yml` through GitHub's **Create new file** option and paste its contents.
3. Go to **Settings → Pages → Build and deployment → Deploy from a branch**, choose `main`, folder `/docs`, then Save.
4. Go to **Actions → Update ODMP memorials → Run workflow** to attempt the first feed update. Watch its logs. If the job fails, do not assume the data is live.
5. When the workflow succeeds, open `https://YOUR-USERNAME.github.io/YOUR-REPOSITORY/` in a browser. Confirm all 10 entries and images match ODMP's homepage.
6. In Yodeck, add a **Web Page** with that GitHub Pages URL. Assign it to your Fire Stick screen and **Push Changes**. Use fullscreen display.

## Important limitations

- **Not tested against ODMP's live markup.** The collector uses heuristics for links, agencies, dates, images, and narratives. ODMP may block GitHub Actions or change HTML. The workflow will fail rather than fabricate entries when fewer than 10 complete records are found.
- **No automatic bypass of access controls.** If ODMP blocks automated access, contact ODMP about an authorized API/feed or obtain permission to syndicate content.
- **Photographs and stories may be copyrighted.** Obtain appropriate authorization from ODMP/rights holders before publishing or redistributing content. GitHub Pages is public, not a private intranet. The updater downloads photographs when possible; remove this behavior if reuse is not authorized.
- GitHub scheduled workflows can be delayed or suspended for inactive public repositories. Check the Actions logs periodically.
- The displayed stories are short excerpts, not the complete ODMP biographies. Check accuracy and permission before use.
- The page intentionally starts empty; no real officers are invented or hard-coded.

## Troubleshooting

- `Feed not yet populated`: run the workflow manually and inspect errors.
- `Found X homepage officer links`: ODMP homepage structure changed or was blocked; adjust `homepage_links` after reviewing the live HTML.
- `Incomplete officer record`: inspect selectors in `extract` and verify each field.
- Missing photo: ODMP may block image downloads; obtain licensed image assets.
- The homepage order is used as shown, not re-sorted by date.
