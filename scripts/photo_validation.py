"""Screenshot validation of the ArtistLedger certificate photo pipeline.

Renders the committed certificate view for a validation set of artists by
calling the page's own renderCertificate() (no wallet, no on-chain tx) and
captures what fetchArtistPortrait() actually displays + which photo credit
appears. Tests the feature commit 7095450 exactly as parked.
"""
import json
import pathlib
import sys
from playwright.sync_api import sync_playwright

FRONTEND = pathlib.Path("/root/projects/ArtistLedger/frontend")
OUT = pathlib.Path("/root/projects/ArtistLedger/screenshots/photo-validation")
OUT.mkdir(parents=True, exist_ok=True)

# (artist, sources claimed) — mix of WIKI_TITLES entries, non-map names, a
# disambiguation trap, and a nobody (exercises every fallback + rejection).
CASES = [
    ("Burial", "apple_music, bandcamp"),
    ("Aphex Twin", "spotify, soundcloud"),
    ("Four Tet", "apple_music, bandcamp"),
    ("Jamie xx", "spotify, lastfm"),
    ("Skrillex", "apple_music, soundcloud"),
    ("deadmau5", "spotify, bandcamp"),
    ("Boards of Canada", "lastfm, bandcamp"),
    ("Totally Fictitious Artist QZ", "instagram, website"),
]

# CLI override: python3 photo_validation.py "Mala" "Coki" ...
if len(sys.argv) > 1:
    CASES = [(n, "apple_music, bandcamp") for n in sys.argv[1:]]
OUT_USER = len(sys.argv) > 1

APP_JS = (FRONTEND / "app.js").read_text()
CERT_HTML = FRONTEND.joinpath("index.html").read_text()

results = []

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.goto(FRONTEND.joinpath("index.html").as_uri())
    page.wait_for_timeout(1500)

    for name, sources in CASES:
        slug = name.lower().replace(" ", "-").replace(".", "")[:24]
        script = f"""
        (() => {{
          const name = {json.dumps(name)};
          $("f-name").value = name;
          walletAddr = "0x000000000000000000000000000000000000d34d";
          picked[0] = {{ id: "apple_music", label: "Apple Music", handle: "{sources.split(',')[0].strip()}" }};
          picked[1] = {{ id: "bandcamp", label: "Bandcamp", handle: "{sources.split(',')[1].strip() if ',' in sources else sources}" }};
          renderCertificate(
            {{
              verdict: "AGREE", score: 88, matchCount: 2,
              matched: [
                {{ label: "Apple Music", verdict: "artist", detail: "id 12345" }},
                {{ label: "Bandcamp", verdict: "claimed", detail: "{sources.split(',')[0].strip()}" }},
              ],
              evidence: {{ apple_music_artist_id: "12345", bandcamp_handle: "{sources.split(',')[0].strip()}" }},
            }},
            {{ status_name: "AGREE", result_name: "FINALIZED", hash: "0x" + "a".repeat(64) }}
          );
          go("B");
          return "rendered";
        }})()
        """
        page.evaluate(script)
        # photo fetch is async: give the source chain up to 12s
        page.wait_for_timeout(12000)
        info = page.evaluate(
            """() => {
              const cert = document.getElementById("cert");
              const img = document.getElementById("cert-photo-img");
              const credit = document.getElementById("cert-photo-credit");
              const holder = document.getElementById("cert-photo-holder");
              return {
                certActive: cert && cert.classList.contains("active"),
                imgVisible: !!img && img.style.display === "block" && !!img.src,
                src: img && img.src ? img.src : "",
                credit: credit ? credit.textContent : "",
                placeholderShown: !!holder && holder.style.display === "flex",
                alt: img ? img.alt : "",
              };
            }"""
        )
        page.screenshot(path=str(OUT / f"{slug}.png"), full_page=False)
        results.append({"artist": name, **info})
        print(f"{name:32s} img={info['imgVisible']} credit={info['credit'] or '—':12s} {info['src'][:60]}")
        # reset for next case
        page.evaluate('(() => { go("A"); return "reset"; })()')
        page.wait_for_timeout(400)

    browser.close()

print("\n--- SUMMARY ---")
ok = sum(1 for r in results if r["imgVisible"])
print(f"{ok}/{len(results)} artists rendered with a photo")
for r in results:
    print(f"  {r['artist']:32s} visible={r['imgVisible']} credit={r['credit'] or 'NONE'}")
(OUT / "results.json").write_text(json.dumps(results, indent=2))
print(f"saved: {OUT}/results.json + {len(results)} screenshots")
