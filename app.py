from fastapi import FastAPI, Form
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import re
from bs4 import BeautifulSoup
from io import BytesIO
import httpx
import asyncio
from urllib.parse import urljoin

EMAIL_REGEX = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

COMMON_PATHS = ["", "/contact", "/about", "/support", "/team", "/info"]

# ---------------- EMAIL EXTRACTION ----------------
def extract_emails_from_html(html: str) -> set:
    soup = BeautifulSoup(html, "html.parser")
    emails = set()

    # 1️⃣ mailto links
    for a in soup.find_all("a", href=True):
        if a["href"].startswith("mailto:"):
            email = a["href"].replace("mailto:", "").split("?")[0].strip()
            if re.match(EMAIL_REGEX, email):
                emails.add(email)

    # 2️⃣ visible text
    text_emails = set(re.findall(EMAIL_REGEX, soup.get_text(" ")))
    emails.update(text_emails)

    return emails

# ---------------- FETCH SINGLE PAGE ----------------
async def fetch_page(client: httpx.AsyncClient, url: str) -> str:
    try:
        r = await client.get(url, timeout=5, follow_redirects=True)
        return r.text
    except Exception:
        return ""

# ---------------- FETCH DOMAIN (MULTI-PAGE) ----------------
async def fetch_domain_emails(client: httpx.AsyncClient, domain: str) -> dict:
    domain = domain.strip()
    if not domain:
        return {"domain": domain, "emails": ""}

    base_url = domain
    if not base_url.startswith("http"):
        base_url = "https://" + base_url

    all_emails = set()
    tasks = []

    # Build full URLs for common paths
    urls = [urljoin(base_url, path) for path in COMMON_PATHS]

    for url in urls:
        tasks.append(fetch_page(client, url))

    pages = await asyncio.gather(*tasks)

    for html in pages:
        emails = extract_emails_from_html(html)
        all_emails.update(emails)

    return {"domain": domain, "emails": ", ".join(all_emails)}

# ---------------- API ----------------
@app.post("/extract")
async def extract(domains: str = Form(...)):
    domain_list = [d.strip() for d in domains.splitlines() if d.strip()]

    async with httpx.AsyncClient(verify=False) as client:
        tasks = [fetch_domain_emails(client, d) for d in domain_list]
        results = await asyncio.gather(*tasks)

    df = pd.DataFrame(results)
    output = BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=extracted_emails.xlsx"}
    )
