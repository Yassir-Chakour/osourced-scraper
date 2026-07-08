from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("https://osourced.is/jobs/")
    page.wait_for_timeout(3000)
    
    print("Listing links:")
    links = page.query_selector_all("a")
    for link in links:
        text = link.inner_text().strip().replace("\n", " ")
        href = link.get_attribute("href")
        cls = link.get_attribute("class")
        id_attr = link.get_attribute("id")
        if text or id_attr:
            print(f"Text: '{text}', ID: '{id_attr}', Class: '{cls}', Href: '{href}'")
            
    print("\nListing buttons:")
    buttons = page.query_selector_all("button")
    for btn in buttons:
        text = btn.inner_text().strip().replace("\n", " ")
        id_attr = btn.get_attribute("id")
        cls = btn.get_attribute("class")
        print(f"Text: '{text}', ID: '{id_attr}', Class: '{cls}'")
        
    browser.close()
