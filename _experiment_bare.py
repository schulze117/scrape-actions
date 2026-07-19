"""THROWAWAY experiment — will be deleted, reverting to current state.

Replicates mdmintz's exact raw_cdp_etsy.py CDP setup (ad_block=True, no
tzone/geoloc/incognito, proactive solve_captcha) but pointed at immoscout, to
check whether his bare config lands the silent challenge on a datacenter IP.
"""
import sys
from seleniumbase import sb_cdp

URL = sys.argv[1] if len(sys.argv) > 1 else (
    "https://www.immobilienscout24.de/Suche/shape/wohnung-mieten?shape="
    "dWZqcEhjYGVwQH5_SH1hQ256S312QWh2Tml_UWR3RHt1Un5jQ2N2X0B_dURtfU1lekRvfFN9"
    "aUB7eGJAfWxPYXtXYWFSd3RMX2NWX3hJe3BjQHRgT3t6SmhxekByek1_Y1p2d0Jwak9sdkxy"
    "YXtAfG9NaHVP&enteredFrom=result_list&sorting=2"
)

sb = sb_cdp.Chrome(ad_block=True)          # mdmintz's exact etsy call
sb.goto(URL)
sb.sleep(3)
sb.solve_captcha()                          # proactive, like his script
sb.sleep(6)
html = sb.get_page_source()
title = html.split("<title>")[1].split("</title>")[0] if "<title>" in html else "?"
blocked = "awswaf" in html.lower() or "ich bin kein roboter" in html.lower()
real = "IS24.resultList" in html
print("=" * 60)
print(f"len:     {len(html):,}")
print(f"title:   {title.strip()[:120]}")
print(f"blocked: {blocked}")
print(f"real content (IS24.resultList): {real}")
print("=" * 60)
try:
    sb.save_screenshot("bare.png", folder="bare_out")
    with open("bare_out/bare.html", "w", encoding="utf-8") as f:
        f.write(html)
except Exception as e:
    print("save err:", e)
sb.quit()
