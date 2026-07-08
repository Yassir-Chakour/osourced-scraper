from playwright.sync_api import sync_playwright
import os

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("https://osourced.is/jobs/")
    page.wait_for_timeout(3000)
    
    print("Clicking btn-header-main-login...")
    try:
        page.click("#btn-header-main-login", timeout=5000)
        print("Click successful!")
    except Exception as e:
        print("Click failed:", e)
        
    page.wait_for_timeout(2000)
    
    # Check if input fields are visible
    print("Checking input fields:")
    user_login = page.query_selector('input[name="user_login"]')
    user_pass = page.query_selector('input[name="user_pass"]')
    print(f"user_login found: {user_login is not None}")
    if user_login:
        print(f"user_login visible: {user_login.is_visible()}")
    print(f"user_pass found: {user_pass is not None}")
    
    browser.close()
