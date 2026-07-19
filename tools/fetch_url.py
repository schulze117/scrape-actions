"""Ad-hoc fetch tester.

Fetch a single URL through the SAME fetch layer the finder/scraper use
(lib.fetch._seleniumbase / _curl_cffi) and report what came back: HTML length,
page title, whether bot detection tripped, plus the raw HTML and (for the
browser method) a screenshot saved to an output folder.

Run locally:
    python -m tools.fetch_url --url "https://www.immobilienscout24.de/..."
    python -m tools.fetch_url --url "https://www.kleinanzeigen.de/" --method curl_cffi

In CI it's driven by .github/workflows/test_fetch.yaml, which uploads the
output folder as an artifact. Exit code is 42 when the browser method hit
persistent bot detection (same signal the finder uses), else 0 on success.
"""
import argparse
import os
import sys
from datetime import datetime, timezone

from lib.helpers import has_bot_detection
from lib.logger import get_logger

logger = get_logger("fetch_url")


def _title(html: str) -> str:
    lower = html.lower()
    if "<title>" in lower:
        start = lower.index("<title>") + len("<title>")
        end = lower.index("</title>", start) if "</title>" in lower[start:] else len(html)
        return " ".join(html[start:end].split())[:200]
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch a URL via the scraper's fetch layer.")
    parser.add_argument("--url", required=True, help="URL to fetch")
    parser.add_argument(
        "--method",
        default="seleniumbase",
        choices=["seleniumbase", "curl_cffi"],
        help="Which fetcher to use (default: seleniumbase)",
    )
    parser.add_argument(
        "--out-dir",
        default="test_output",
        help="Folder for the saved HTML + screenshot (default: test_output)",
    )
    parser.add_argument("--proxy-url", default=None, help="Optional proxy (host:port or scheme://...)")
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    html_path = os.path.join(args.out_dir, f"page-{stamp}.html")
    shot_path = os.path.join(args.out_dir, f"page-{stamp}.png")

    logger.info(f"Fetching {args.url} via {args.method} ...")

    exit_code = 0
    try:
        if args.method == "seleniumbase":
            # Import here so curl-only runs don't pull in seleniumbase.
            from lib.fetch._seleniumbase import get_html_seleniumbase

            html = get_html_seleniumbase(
                args.url, proxy_url=args.proxy_url, screenshot_path=shot_path
            )
        else:
            from lib.fetch._curl_cffi import get_html_curlcffi

            html = get_html_curlcffi(args.url, proxy_url=args.proxy_url)
    except SystemExit as e:
        # get_html_seleniumbase does os._exit(42) on persistent bot detection,
        # which raises SystemExit before this normally; guard just in case.
        return int(getattr(e, "code", 1) or 0)

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    bot = has_bot_detection(html)
    title = _title(html)

    summary_lines = [
        f"URL:            {args.url}",
        f"Method:         {args.method}",
        f"HTML length:    {len(html):,} chars",
        f"Page title:     {title or '(none)'}",
        f"Bot detection:  {'YES (looks blocked)' if bot else 'no (looks OK)'}",
        f"HTML saved:     {html_path}",
    ]
    if args.method == "seleniumbase" and os.path.exists(shot_path):
        summary_lines.append(f"Screenshot:     {shot_path}")

    report = "\n".join(summary_lines)
    print("\n" + "=" * 60)
    print(report)
    print("=" * 60 + "\n")

    # Feed the GitHub Actions run summary when available.
    gh_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh_summary:
        with open(gh_summary, "a", encoding="utf-8") as f:
            f.write("### Fetch test result\n\n```\n" + report + "\n```\n")

    if bot:
        logger.warning("Result looks like a bot-detection / captcha page.")
        exit_code = 42
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
