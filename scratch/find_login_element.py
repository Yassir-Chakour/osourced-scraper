from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("https://osourced.is/jobs/")
    page.wait_for_timeout(3000)
    
    # Let's find any element containing text 'Log' or 'in' or 'Anmeldung'
    print("Searching for elements by text...")
    for tag in ["a", "button", "div", "span"]:
        elements = page.query_selector_all(tag)
        for el in elements:
            text = el.inner_text().strip()
            if text in ("Log-in", "Login", "Log in", "Anmeldung"):
                visible = el.is_visible()
                id_attr = el.get_attribute("id")
                cls = el.get_attribute("class")
                tag_name = el.evaluate("node => node.tagName")
                print(f"Tag: {tag_name}, Text: '{text}', Visible: {visible}, ID: {id_attr}, Class: {cls}")
                
    browser.close()
