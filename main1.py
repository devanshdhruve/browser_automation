import time, random, re
from pathlib import Path
from typing import List, Dict, Set, Tuple
import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ------------------ CONFIG ------------------
KEYWORDS = [
    "software developer", "fullstack developer", "frontend developer",
    "backend developer", "blockchain developer", "consultant",
    "data analyst", "associate analyst"
]
LOCATION = "India"  # change/empty "" for global

# include only entry/fresher-ish; we still locally filter after scraping
INCLUDE_HINTS = ["fresher", "entry", "junior", "graduate", "0-1", "0 – 1", "0 to 1", "trainee", "intern"]

# exclude senior roles
EXCLUDE_HINTS = ["senior", "sr.", "lead", "principal", "head", "manager", "director", "vp", "chief"]

# random user-agents for anti-bot
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

OUTPUT_CSV = "jobs_batch1.csv"
MAX_PER_SITE_PER_KEYWORD = 40  # light throttle per keyword/site
HEADLESS = True

# ------------------ UTILS ------------------
def human_delay(a=0.8, b=2.2):
    time.sleep(random.uniform(a, b))

def looks_entry_level(title: str) -> bool:
    t = title.lower()
    if any(x in t for x in EXCLUDE_HINTS):
        return False
    # If the title contains an entry hint or is generic (e.g. "Associate", "Analyst") we keep it
    return any(x in t for x in INCLUDE_HINTS) or True  # keep broad titles; we already exclude seniors

def unique_key(job: Dict) -> Tuple[str, str, str]:
    return (job.get("title","").strip().lower(),
            job.get("company","").strip().lower(),
            job.get("location","").strip().lower())

def clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

# ------------------ SCRAPERS ------------------
def scrape_linkedin(page, keyword: str) -> List[Dict]:
    """Public LinkedIn listings (limited without login). Uses entry-level filter f_E=2 when possible."""
    jobs = []
    q = f"{keyword} {LOCATION}".strip().replace(" ", "%20")
    url = f"https://www.linkedin.com/jobs/search/?keywords={q}&f_E=2"  # Entry level
    try:
        page.goto(url, timeout=60000)
        human_delay(2, 3.5)
        # Accept cookie banner if shown
        try:
            page.locator("button:has-text('Accept')").first.click(timeout=3000)
        except PWTimeout:
            pass

        cards = page.locator("ul.jobs-search__results-list li")
        count = min(cards.count(), MAX_PER_SITE_PER_KEYWORD)
        for i in range(count):
            card = cards.nth(i)
            title = clean_text(card.locator("h3").inner_text())
            company = clean_text(card.locator(".base-search-card__subtitle").inner_text())
            location = clean_text(card.locator(".job-search-card__location").inner_text())
            link = clean_text(card.locator("a.base-card__full-link").first.get_attribute("href"))
            if title and company and link and looks_entry_level(title):
                jobs.append({
                    "title": title, "company": company, "location": location,
                    "link": link, "source": "LinkedIn"
                })
    except Exception:
        # Some regions may block; continue gracefully
        pass
    return jobs

def scrape_naukri(page, keyword: str) -> List[Dict]:
    jobs = []
    q_for_url = keyword.replace(" ", "-")
    url = f"https://www.naukri.com/{q_for_url}-jobs?experience=0&k={keyword.replace(' ','+')}"

    try:
        page.goto(url, timeout=60000)
        human_delay(1.5, 2.5)
        # dismiss popups if any
        for sel in ["#block", ".accept", "button:has-text('Got it')"]:
            try:
                page.locator(sel).first.click(timeout=1000)
            except PWTimeout:
                pass

        # New Naukri layout: .cust-job-tuple or .jobTuple
        cards = page.locator(".cust-job-tuple, .jobTuple")
        count = min(cards.count(), MAX_PER_SITE_PER_KEYWORD)
        for i in range(count):
            c = cards.nth(i)
            title = clean_text((c.locator("a.title").inner_text() if c.locator("a.title").count()
                               else c.locator("a").first.inner_text()))
            company = clean_text((c.locator(".subTitle").inner_text() if c.locator(".subTitle").count()
                                 else c.locator(".companyInfo a").first.inner_text() if c.locator(".companyInfo a").count()
                                 else ""))
            location = clean_text((c.locator(".loc").inner_text() if c.locator(".loc").count()
                                  else c.locator(".location").first.inner_text() if c.locator(".location").count()
                                  else LOCATION))
            link = clean_text((c.locator("a.title").first.get_attribute("href") if c.locator("a.title").count()
                               else c.locator("a").first.get_attribute("href")))
            if title and company and link and looks_entry_level(title):
                jobs.append({
                    "title": title, "company": company, "location": location,
                    "link": link, "source": "Naukri"
                })
    except Exception:
        pass
    return jobs

def scrape_indeed(page, keyword: str) -> List[Dict]:
    jobs = []
    q = keyword.replace(" ", "+")
    loc = LOCATION.replace(" ", "+")
    # entry level filter via explvl sometimes works; else we locally filter
    url = f"https://in.indeed.com/jobs?q={q}+fresher&l={loc}"
    try:
        page.goto(url, timeout=60000)
        human_delay(1.5, 2.5)
        try:
            page.locator("button:has-text('Accept')").click(timeout=2000)
        except PWTimeout:
            pass

        # cards: .job_seen_beacon
        # Scroll a bit to load more
        for _ in range(3):
            page.mouse.wheel(0, random.randint(600, 1000))
            human_delay(0.8, 1.8)

        cards = page.locator(".job_seen_beacon")
        count = min(cards.count(), MAX_PER_SITE_PER_KEYWORD)
        for i in range(count):
            c = cards.nth(i)
            title = clean_text(c.locator("h2 a").inner_text() if c.locator("h2 a").count() else c.locator("h2").inner_text())
            company = clean_text(c.locator(".companyName").inner_text() if c.locator(".companyName").count() else "")
            location = clean_text(c.locator(".companyLocation").inner_text() if c.locator(".companyLocation").count() else LOCATION)
            link = c.locator("h2 a").first.get_attribute("href") if c.locator("h2 a").count() else ""
            if link and not link.startswith("http"):
                link = "https://in.indeed.com" + link
            if title and company and link and looks_entry_level(title):
                jobs.append({
                    "title": title, "company": company, "location": location,
                    "link": link, "source": "Indeed"
                })
    except Exception:
        pass
    return jobs

def scrape_glassdoor(page, keyword: str) -> List[Dict]:
    jobs = []
    q = keyword.replace(" ", "+")
    url = f"https://www.glassdoor.co.in/Job/jobs.htm?sc.keyword={q}&fromAge=3"
    try:
        page.goto(url, timeout=60000)
        human_delay(2, 3)
        try:
            page.locator("button:has-text('Accept All')").click(timeout=2000)
        except PWTimeout:
            pass

        # Scroll to load more
        for _ in range(3):
            page.mouse.wheel(0, random.randint(600, 1000))
            human_delay(0.9, 1.6)

        cards = page.locator("[data-test='jobListing']")
        count = min(cards.count(), MAX_PER_SITE_PER_KEYWORD)
        for i in range(count):
            c = cards.nth(i)
            title = clean_text(c.locator("[data-test='job-title']").inner_text() if c.locator("[data-test='job-title']").count() else "")
            company = clean_text(c.locator("[data-test='job-card-company-name']").inner_text() if c.locator("[data-test='job-card-company-name']").count() else "")
            location = clean_text(c.locator("[data-test='job-location']").inner_text() if c.locator("[data-test='job-location']").count() else LOCATION)
            link = ""
            try:
                link = c.locator("a").first.get_attribute("href") or ""
            except:
                pass
            if link and link.startswith("/"):
                link = "https://www.glassdoor.co.in" + link
            if title and company and link and looks_entry_level(title):
                jobs.append({
                    "title": title, "company": company, "location": location,
                    "link": link, "source": "Glassdoor"
                })
    except Exception:
        pass
    return jobs

# ------------------ MAIN ------------------
def main():
    all_rows: List[Dict] = []
    seen: Set[Tuple[str, str, str]] = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        context = browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": random.randint(1200, 1440), "height": random.randint(800, 1000)},
            locale="en-US"
        )
        page = context.new_page()

        for kw in KEYWORDS:
            print(f"🔎 Searching: {kw}")

            # LinkedIn
            human_delay(1.2, 2.5)
            for row in scrape_linkedin(page, kw):
                key = unique_key(row)
                if key not in seen:
                    seen.add(key); all_rows.append(row)

            # Naukri
            human_delay(1.2, 2.5)
            for row in scrape_naukri(page, kw):
                key = unique_key(row)
                if key not in seen:
                    seen.add(key); all_rows.append(row)

            # Indeed
            human_delay(1.2, 2.5)
            for row in scrape_indeed(page, kw):
                key = unique_key(row)
                if key not in seen:
                    seen.add(key); all_rows.append(row)

            # Glassdoor
            human_delay(1.2, 2.5)
            for row in scrape_glassdoor(page, kw):
                key = unique_key(row)
                if key not in seen:
                    seen.add(key); all_rows.append(row)

        browser.close()

    if not all_rows:
        print("No jobs found (sites may have blocked requests or changed markup). Try running again or reduce HEADLESS to see what happens.")
        return

    df = pd.DataFrame(all_rows, columns=["title","company","location","link","source"])
    df.drop_duplicates(subset=["title","company","location"], inplace=True)
    Path(OUTPUT_CSV).write_text("", encoding="utf-8")  # ensure file is fresh
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")
    print(f"✅ Saved {len(df)} unique jobs to {OUTPUT_CSV}")

if __name__ == "__main__":
    main()
