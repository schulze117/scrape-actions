"""Daily pipeline summary report. Run as: python -m report.daily"""

import os
import smtplib
import zoneinfo
from contextlib import contextmanager
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import psycopg
import psycopg.rows
from dotenv import dotenv_values

BERLIN_TZ = zoneinfo.ZoneInfo("Europe/Berlin")
BASE_DIR = Path(__file__).resolve().parent.parent

SOURCES = ["kleinanzeigen", "immoscout", "immowelt"]
SOURCE_LABELS = {
    "kleinanzeigen": "Kleinanzeigen",
    "immoscout": "Immoscout24",
    "immowelt": "Immowelt",
}


def load_env() -> dict:
    env_path = BASE_DIR / ".env"
    secrets = dict(dotenv_values(env_path))
    for key in list(secrets):
        if key in os.environ:
            secrets[key] = os.environ[key]
    return secrets


@contextmanager
def get_db(env: dict):
    conn = psycopg.connect(
        host=env["DATABASE__HOST"],
        port=int(env["DATABASE__PORT"]),
        dbname=env["DATABASE__NAME"],
        user=env["DATABASE__USER"],
        password=env["DATABASE__PASSWORD"],
        row_factory=psycopg.rows.dict_row,
    )
    try:
        with conn.cursor() as cur:
            yield cur
    finally:
        conn.close()


def fetch_stats(env: dict) -> dict:
    with get_db(env) as cur:
        cur.execute("""
            SELECT source, COUNT(*) AS count
            FROM fixnflip_v2.property
            WHERE created_at >= NOW() - INTERVAL '24 hours'
            GROUP BY source
        """)
        new_found = {r["source"]: r["count"] for r in cur.fetchall()}

        cur.execute("""
            SELECT source, COUNT(*) AS count
            FROM fixnflip_v2.property
            GROUP BY source
        """)
        total_found = {r["source"]: r["count"] for r in cur.fetchall()}

        cur.execute("""
            SELECT p.source, COUNT(*) AS count
            FROM fixnflip_v2.system s
            JOIN fixnflip_v2.property p ON p.id = s.property_id
            WHERE s.last_scraped_at >= NOW() - INTERVAL '24 hours'
            GROUP BY p.source
        """)
        scraped_24h = {r["source"]: r["count"] for r in cur.fetchall()}

        # Kleinanzeigen: re-scrapes everything every 12h — count due in that cycle
        cur.execute("""
            SELECT COUNT(*) AS count
            FROM fixnflip_v2.system s
            JOIN fixnflip_v2.property p ON p.id = s.property_id
            LEFT JOIN fixnflip_v2.general g ON g.property_id = p.id
            WHERE p.source = 'kleinanzeigen'
              AND (g.active = TRUE OR g.active IS NULL)
              AND s.last_scraped_at IS NOT NULL
              AND s.last_scraped_at < NOW() - INTERVAL '12 hours'
        """)
        ka_modified = cur.fetchone()["count"]

        # Immoscout/Immowelt: only re-scrape when modified_at changed in last 24h
        cur.execute("""
            SELECT p.source, COUNT(*) AS count
            FROM fixnflip_v2.system s
            JOIN fixnflip_v2.property p ON p.id = s.property_id
            LEFT JOIN fixnflip_v2.general g ON g.property_id = p.id
            WHERE p.source IN ('immoscout', 'immowelt')
              AND (g.active = TRUE OR g.active IS NULL)
              AND s.last_scraped_at IS NOT NULL
              AND p.modified_at >= NOW() - INTERVAL '24 hours'
              AND p.modified_at > s.last_scraped_at
            GROUP BY p.source
        """)
        modified = {"kleinanzeigen": ka_modified}
        modified.update({r["source"]: r["count"] for r in cur.fetchall()})

        cur.execute("""
            SELECT p.source, COUNT(*) AS count
            FROM fixnflip_v2.system s
            JOIN fixnflip_v2.property p ON p.id = s.property_id
            LEFT JOIN fixnflip_v2.general g ON g.property_id = p.id
            WHERE (g.active = TRUE OR g.active IS NULL)
              AND s.last_scraped_at IS NULL
            GROUP BY p.source
        """)
        never_scraped = {r["source"]: r["count"] for r in cur.fetchall()}

        cur.execute("""
            SELECT p.source, COUNT(*) AS count
            FROM fixnflip_v2.general g
            JOIN fixnflip_v2.property p ON p.id = g.property_id
            WHERE g.active = TRUE
            GROUP BY p.source
        """)
        active = {r["source"]: r["count"] for r in cur.fetchall()}

    return {
        "new_found": new_found,
        "total_found": total_found,
        "scraped_24h": scraped_24h,
        "modified": modified,
        "never_scraped": never_scraped,
        "active": active,
    }


def fmt(n) -> str:
    if n is None:
        return "—"
    return f"{int(n):,}"


def total(d: dict) -> int:
    return sum(d.get(s, 0) for s in SOURCES)


def build_html(stats: dict, now: datetime) -> str:
    s = stats
    date_str = now.strftime("%d %b %Y, %H:%M CET")

    th = "padding:6px 10px;border:1px solid #ddd;background:#f5f5f5;text-align:{align};"
    td = "padding:5px 10px;border:1px solid #eee;text-align:{align};"
    td_bold = "padding:5px 10px;border:1px solid #ddd;background:#fafafa;font-weight:600;text-align:{align};"

    def header_row(*cols, first_align="left"):
        cells = f'<th style="{th.format(align=first_align)}">{cols[0]}</th>'
        cells += "".join(f'<th style="{th.format(align="right")}">{c}</th>' for c in cols[1:])
        return f"<tr>{cells}</tr>"

    def data_row(label, *vals):
        cells = f'<td style="{td.format(align="left")}">{label}</td>'
        cells += "".join(f'<td style="{td.format(align="right")}">{v}</td>' for v in vals)
        return f"<tr>{cells}</tr>"

    def total_row(*vals):
        cells = f'<td style="{td_bold.format(align="left")}">Total</td>'
        cells += "".join(f'<td style="{td_bold.format(align="right")}">{v}</td>' for v in vals)
        return f"<tr>{cells}</tr>"

    def section(title, table_html):
        return f"""
<h3 style="margin:24px 0 8px;font-size:12px;font-weight:700;letter-spacing:1.2px;
           text-transform:uppercase;color:#555;border-bottom:2px solid #eee;padding-bottom:5px;">
  {title}
</h3>
<table style="width:100%;border-collapse:collapse;font-size:12px;margin-bottom:4px;">
  {table_html}
</table>"""

    # --- Finder table ---
    finder_rows = "\n".join(
        data_row(SOURCE_LABELS[src], fmt(s["new_found"].get(src, 0)), fmt(s["total_found"].get(src, 0)))
        for src in SOURCES
    )
    finder_table = (
        header_row("Platform", "New (24h)", "Total Found")
        + finder_rows
        + total_row(fmt(total(s["new_found"])), fmt(total(s["total_found"])))
    )

    # --- Scraper table ---
    scraper_rows = "\n".join(
        data_row(
            SOURCE_LABELS[src],
            fmt(s["scraped_24h"].get(src, 0)),
            fmt(s["modified"].get(src, 0)),
            fmt(s["never_scraped"].get(src, 0)),
        )
        for src in SOURCES
    )
    scraper_table = (
        header_row("Platform", "Scraped (24h)", "Modified (24h)", "Never Scraped")
        + scraper_rows
        + total_row(
            fmt(total(s["scraped_24h"])),
            fmt(total(s["modified"])),
            fmt(total(s["never_scraped"])),
        )
    )

    # --- Database table ---
    db_rows = "\n".join(
        data_row(SOURCE_LABELS[src], fmt(s["active"].get(src, 0)))
        for src in SOURCES
    )
    db_table = (
        header_row("Platform", "Active Listings")
        + db_rows
        + total_row(fmt(total(s["active"])))
    )

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
             font-size:13px;color:#222;background:#f0f0f0;padding:24px;margin:0;">
<div style="max-width:600px;margin:0 auto;background:#fff;
            border:1px solid #ddd;border-radius:8px;padding:28px 32px;">

  <h2 style="margin:0 0 2px;font-size:20px;color:#111;font-weight:700;">
    ImmoFinder Daily Report
  </h2>
  <p style="margin:0 0 8px;color:#888;font-size:12px;">{date_str}</p>

  {section("Finder", finder_table)}
  {section("Scraper", scraper_table)}
  {section("Database", db_table)}

  <p style="margin:24px 0 0;font-size:11px;color:#bbb;border-top:1px solid #f0f0f0;padding-top:12px;">
    ImmoFinder · scrape-actions · automated report
  </p>
</div>
</body>
</html>"""


def send_email(env: dict, subject: str, html: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = env["EMAIL__USER"]
    msg["To"] = env["EMAIL__TO"]
    msg.attach(MIMEText(html, "html", "utf-8"))

    host = env["EMAIL__SMTP_HOST"]
    port = int(env["EMAIL__SMTP_PORT"])

    with smtplib.SMTP(host, port) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(env["EMAIL__USER"], env["EMAIL__PASSWORD"])
        smtp.sendmail(env["EMAIL__USER"], env["EMAIL__TO"].split(","), msg.as_string())


def main() -> None:
    env = load_env()
    now = datetime.now(BERLIN_TZ)
    print(f"[report] Fetching stats at {now.isoformat()}")

    stats = fetch_stats(env)

    subject = f"ImmoFinder Daily Report — {now.strftime('%d %b %Y')}"
    html = build_html(stats, now)

    recipients = env["EMAIL__TO"]
    print(f"[report] Sending email to {recipients}")
    send_email(env, subject, html)
    print("[report] Done.")


if __name__ == "__main__":
    main()
