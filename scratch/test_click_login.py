from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("https://osourced.is/jobs/")
    page.wait_for_timeout(3000)
    
    print("Clicking 'text=Log-in'...")
    try:
        # Click the element containing 'Log-in' that is visible
        page.locator("a:has-text('Log-in')").first.click()
        print("Click successful!")
    except Exception as e:
        print("Click failed:", e)
        
    page.wait_for_timeout(2000)
    
    # Check if input fields are visible
    print("Checking input fields:")
    user_login = page.query_selector('input[name="user_login"]')
    if user_login:
        print(f"user_login visible: {user_login.is_visible()}")
    else:
        print("user_login not found")
        
    browser.close()
