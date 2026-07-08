from playwright.sync_api import sync_playwright
import os

os.makedirs("scratch", exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    try:
        print("Navigating to https://osourced.is/jobs/...")
        page.goto("https://osourced.is/jobs/")
        page.wait_for_timeout(5000)
        print("URL after navigation:", page.url)
        page.screenshot(path="scratch/osourced_homepage.png")
        print("Screenshot saved to scratch/osourced_homepage.png")
    except Exception as e:
        print("Error:", e)
    browser.close()
