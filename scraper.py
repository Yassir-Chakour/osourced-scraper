import time, requests, json
from playwright.sync_api import sync_playwright
from config import Config


class JobScraper:
    def __init__(self):
        Config.validate()
        self.jobs = []

    def generate_pitch(self, job_title, salary_range, description):
        clean_desc = description.replace("{", "(").replace("}", ")")

        full_prompt = f"""
        # ROLE
        You are Yassir Chakour, the founder of Shinobi Automation. You are an expert in B2B cold email outreach.
        
        # TASK
        Write a personalized B2B pitch email in German.
        Target: The company posting the job below.
        Goal: Pitch automation as a solution to their problem.
        
        # RULES
        1. **SNIPER MODE:** Identify manual tasks mentioned in the text. Use those exact task in your pitch.
        2. **PERSPECTIVE:** Write AS Yassir Chakour. You are NOT applying for the job.
        3. **NO PLACEHOLDERS:** Never use [brackets]. If no name is found, use "Sehr geehrte Damen und Herren,".
        4. **NO TECH JARGON:** No "n8n" or "API". Use words like "Automatisierung" or "Prozesse".
        5. **LENGTH:** Max 90 words. Short and punchy.
        
        # STRUCTURE
        1. **Salutation:** (Strict Logic: Name -> Company -> "Sehr geehrte Damen und Herren,")
        2. **The Hook:** "Ich habe gesehen, dass Sie Unterstützung für [Job Title] suchen."
        3. **The Sniper Pivot:** "show the weakpoint if those manuelle tasks doing them manuelly"
        4. **The Solution:** "Give a solution and that we can help them gain hours"
        5. **CTA:** "Haben Sie nächste 5 Minuten für einen kurzen Austausch?"
        6. **Sign-off:** "Beste Grüße,\nYassir Chakour"

        # INPUT DATA
        Job Title: {job_title}
        Salary Range: {salary_range}
        Job Post: {clean_desc}

        # OUTPUT
        German language only. Text only.
        """

        try:
            response = requests.post(
                url=Config.API_URL,
                headers={
                    "Authorization": f"Bearer {Config.OPENROUTER_KEY}",
                    "Content-Type": "application/json"
                },
                data=json.dumps({
                    "model": Config.MODEL,
                    "messages": [
                        {"role": "user", "content": full_prompt}
                    ]
                })
            )

            if response.status_code == 200:
                result = response.json()
                return result['choices'][0]['message']['content']
            else:
                print(f"API Error: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            print(f"Error generating pitch: {e}")
            return None

    def run(self):
        with sync_playwright() as p:
            print("Launching Browser...")
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            print("Navigating to osourced.is...")
            page.goto(Config.URL_LOGIN)

            print("Looking for Login button...")
            try:
                page.click('#btn-header-main-login:visible')
            except Exception as e:
                print(f"Login button click failed: {e}")

            print("Typing credentials...")
            try:
                page.fill('input[name="user_login"]', Config.USER_LOGIN)
                page.fill('input[name="user_pass"]', Config.USER_PASS)
            except:
                print("Failed to find fields...")

            print("Clicking Submit...")
            page.click('input[name="user-submit"]')

            print("Waiting for login to finish...")
            page.wait_for_timeout(5000)

            print("Login successful! Extracting jobs...")
            elements = page.query_selector_all('h3 a')

            for link in elements[:5]:
                self.jobs.append({
                    'title': link.inner_text(),
                    'salary-range': 'null',
                    'link': link.get_attribute('href'),
                    'applied': False
                })

            print(f"Found {len(self.jobs)} jobs, Checking if applied to....")

            for job in self.jobs:
                print(f"Checking details for: {job['title'][:30]}...")
                try:
                    page.goto(job['link'])
                    apply_btn = page.query_selector('div.cs-text button')

                    if not apply_btn:
                        job['applied'] = True
                        print(f"Already applied to: {job['title'][:30]} skipping to next one...")
                        continue

                    job_description = page.query_selector("div.job-description")
                    salary_range = page.query_selector_all("div.job-detail strong")

                    if job_description:
                        job['description'] = job_description.inner_text()
                    else:
                        job['description'] = "No description available"

                    if salary_range:
                        job['salary-range'] = f"{salary_range[0].inner_text()} - {salary_range[1].inner_text()}"

                    apply_btn.click()

                    anschreiben = self.generate_pitch(
                        job['title'],
                        job['salary-range'],
                        job['description']
                    )

                    if anschreiben:
                        print("Generated Pitch:")
                        print(anschreiben)
                        page.fill('textarea', anschreiben)
                        page.click("div.modal-body >> text=Jetzt Bewerben")
                        job['applied'] = True
                        print("Application Sent! 🚀")
                        time.sleep(3)

                except Exception as e:
                    print(f"Failed to scrape {job['link']}: {e}")

                time.sleep(30)

            print("\n--- Finished ---")
            for j in self.jobs:
                if j['applied']:
                    print(f"applied for: {j['title'][:30]}")