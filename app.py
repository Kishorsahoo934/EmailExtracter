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

# -------------------------------------------------
# CONFIG
# -------------------------------------------------
EMAIL_REGEX = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
COMMON_PATHS = ["", "/contact", "/about", "/support", "/team", "/info"]

# -------------------------------------------------
# APP INIT
# -------------------------------------------------
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # tighten later if needed
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------
# HEALTH CHECK (Render cold start)
# -------------------------------------------------
@app.get("/")
def health():
    return {"status": "ok"}

# -------------------------------------------------
# EMAIL EXTRACTION
# -------------------------------------------------
def extract_emails_from_html(html: str) -> set:
    if not html:
        return set()

    soup = BeautifulSoup(html, "html.parser")
    emails = set()

    # mailto links
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("mailto:"):
            email = href.replace("mailto:", "").split("?")[0].strip()
            if re.match(EMAIL_REGEX, email):
                emails.add(email)

    # visible text
    emails.update(re.findall(EMAIL_REGEX, soup.get_text(" ")))

    return emails

# -------------------------------------------------
# FETCH PAGE
# -------------------------------------------------
async def fetch_page(client: httpx.AsyncClient, url: str) -> str:
    try:
        r = await client.get(url, follow_redirects=True)
        if r.status_code == 200:
            return r.text
    except Exception:
        pass
    return ""

# -------------------------------------------------
# FETCH DOMAIN (MULTI-PAGE)
# -------------------------------------------------
async def fetch_domain_emails(client: httpx.AsyncClient, domain: str) -> dict:
    domain = domain.strip()
    if not domain:
        return {"domain": domain, "emails": ""}

    if not domain.startswith("http"):
        domain = "https://" + domain

    urls = [urljoin(domain, path) for path in COMMON_PATHS]
    tasks = [fetch_page(client, url) for url in urls]

    pages = await asyncio.gather(*tasks, return_exceptions=True)

    all_emails = set()
    for html in pages:
        if isinstance(html, str):
            all_emails.update(extract_emails_from_html(html))

    return {
        "domain": domain.replace("https://", "").replace("http://", ""),
        "emails": ", ".join(sorted(all_emails))
    }

# -------------------------------------------------
# API ENDPOINT
# -------------------------------------------------
@app.post("/extract")
async def extract(domains: str = Form(...)):
    domain_list = [d.strip() for d in domains.splitlines() if d.strip()]

    timeout = httpx.Timeout(8.0)
    limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)

    async with httpx.AsyncClient(
        timeout=timeout,
        limits=limits,
        headers={"User-Agent": "Mozilla/5.0"}
    ) as client:

        results = []
        for domain in domain_list:
            try:
                data = await fetch_domain_emails(client, domain)
                results.append(data)
            except Exception:
                results.append({"domain": domain, "emails": ""})

    df = pd.DataFrame(results)
    output = BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename=extracted_emails.xlsx"
        }
    )
