import json
import logging
import re
import requests
from langdetect import detect
from config import Config
from graph.state import GraphState, Job

logger = logging.getLogger(__name__)

def call_llm(prompt: str, json_mode: bool = False) -> str:
    """Make a direct API call to OpenRouter LLM and return the response text."""
    headers = {
        "Authorization": f"Bearer {Config.OPENROUTER_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": Config.MODEL,
        "messages": [{"role": "user", "content": prompt}]
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    try:
        response = requests.post(url=Config.API_URL, headers=headers, json=payload, timeout=30)
        if response.status_code != 200:
            logger.error(f"LLM API error: {response.status_code} - {response.text}")
            raise requests.HTTPError(
                f"LLM API returned {response.status_code}", response=response
            )
        return response.json()['choices'][0]['message']['content'].strip()
    except requests.RequestException as e:
        logger.error(f"LLM request failed: {e}")
        raise

def extract_pain_points(job: Job) -> list:
    """LLM Step 1: Extract manual pain points from job description."""
    prompt = f"""Analysiere die folgende Stellenausschreibung und extrahiere ALLE manuellen,
repetitiven oder zeitaufwändigen Aufgaben, die explizit oder implizit erwähnt werden.

Gib eine JSON-Liste mit kurzen deutschen Stichpunkten zurück.

Stelle:
{job["description"]}

Ausgabe (nur JSON):
{{"pain_points": ["...", "...", "..."]}}"""

    logger.info("Extracting pain points via LLM...")
    try:
        response_text = call_llm(prompt, json_mode=True)
    except requests.RequestException:
        return []

    try:
        data = json.loads(response_text)
        return data.get("pain_points", [])
    except Exception as e:
        logger.error(f"Failed to parse pain points JSON: {e}. Raw response: {response_text}")
        matches = re.findall(r'"([^"]*)"', response_text)
        if matches:
            return [m for m in matches if m not in ("pain_points", "pain", "points")]
        return []

def write_pitch_email(job: Job, pain_points: list, user_feedback: str = "") -> str:
    """LLM Step 2: Write pitch email in German using pain points."""
    feedback_section = ""
    if user_feedback:
        feedback_section = f"\n# FEEDBACK VOM NUTZER\n{user_feedback}\nPasse die E-Mail entsprechend an.\n"
        
    prompt = f"""# ROLLE
Du bist Yassir Chakour, Gründer von Shinobi Automation.
Du schreibst kurze, präzise B2B-Kaltakquise-E-Mails auf Deutsch.

# AUFGABE
Schreibe eine personalisierte Pitch-E-Mail an das Unternehmen, das die folgende
Stelle ausgeschrieben hat. Ziel: Automatisierung als Lösung anbieten.

# REGELN
- Schreibe ALS Yassir Chakour. Du bewirbst dich NICHT auf die Stelle.
- Keine Platzhalter wie [Name] oder [Unternehmen] oder [Stelle]. Wenn kein Name: "Sehr geehrte Damen und Herren,"
- Kein Tech-Jargon. Nutze: "Automatisierung", "Prozesse", "Abläufe". Niemals "n8n" oder "API".
- Maximal 90 Wörter. Kurz und prägnant.
- Exakt diesen Aufbau — kein anderes Format.

# AUFBAU
1. Anrede
2. "Ich habe gesehen, dass Sie Unterstützung für [Stelle] suchen."
3. Nenne 1-2 manuelle Aufgaben aus der Liste und zeige, dass sie Zeit fressen.
4. "Genau diese Abläufe automatisieren wir — [konkreter Nutzen]."
5. "Haben Sie die nächsten 5 Minuten für einen kurzen Austausch?"
6. "Beste Grüße,\\nYassir Chakour\\nShinobi Automation"

# BEISPIEL
Sehr geehrte Damen und Herren,

ich habe gesehen, dass Sie Unterstützung für Office Management suchen.
Kalender koordinieren, Reisen buchen, Belege erfassen — das kostet täglich
mehrere Stunden manueller Arbeit. Genau diese Abläufe automatisieren wir,
sodass Ihr Team sich auf das Wesentliche konzentrieren kann.

Haben Sie die nächsten 5 Minuten für einen kurzen Austausch?

Beste Grüße,
Yassir Chakour
Shinobi Automation

# EINGABE
Stelle: {job["title"]}
Unternehmen: {job["company_name"]}
Gehaltsrahmen: {job["salary_range"]}
Manuelle Aufgaben: {', '.join(pain_points)}
{feedback_section}
# AUSGABE
Nur der E-Mail-Text. Kein Betreff. Kein Markdown."""

    logger.info("Generating pitch email via LLM...")
    return call_llm(prompt)

def validate_pitch(pitch: str) -> tuple[bool, str]:
    """Validate word count, placeholder presence, and language."""
    if not pitch:
        return False, "Pitch is empty."
        
    # Check word count
    words = pitch.split()
    word_count = len(words)
    if word_count > 120:
        return False, f"Pitch exceeds word limit ({word_count} words)."
        
    # Check placeholders
    if "[" in pitch or "]" in pitch or "{" in pitch or "}" in pitch:
        return False, "Pitch contains placeholder brackets."
        
    # Check language
    try:
        lang = detect(pitch)
        if lang != "de":
            return False, f"Pitch is not in German (detected language: {lang})."
    except Exception as e:
        logger.warning(f"Language detection failed: {e}")
        # If detection fails, we don't necessarily fail validation but log it
        
    return True, ""

def pitch_writer_node(state: GraphState) -> GraphState:
    if state.get("errors"):
        logger.warning("Skipping pitch_writer node due to existing errors.")
        return state
        
    idx = state.get("current_job_index", 0)
    jobs = state.get("jobs", [])
    if idx >= len(jobs):
        logger.warning("No job to process at index.")
        return state
        
    job = jobs[idx]
    
    # If the job has already been applied or skipped or errored out, skip
    if job.get("status") in ("applied", "rejected", "error"):
        logger.info(f"Job status is {job['status']}, skipping pitch writer.")
        return state

    # Step 1: Extract pain points if not already extracted
    if not job.get("pain_points"):
        job["pain_points"] = extract_pain_points(job)

    pitch = ""
    valid = False
    error_msg = ""

    for round_num in (1, 2):
        logger.info(f"Pitch writing generation round {round_num}...")
        try:
            pitch = write_pitch_email(job, job["pain_points"], job.get("user_feedback", ""))
        except requests.RequestException as e:
            logger.error(f"LLM call failed in round {round_num}: {e}")
            break
        valid, error_msg = validate_pitch(pitch)

        if valid:
            logger.info("Pitch validation passed.")
            break

        logger.warning(f"Pitch validation failed in round {round_num}: {error_msg}")
        if round_num == 1:
            # Embed the validation failure as correction instructions for the next round.
            job["user_feedback"] = (
                f"Please correct this issue: {error_msg}. "
                "Make sure it is in German, has no placeholders like [brackets], and is under 90 words."
            )

    job["pitch"] = pitch
    if not valid:
        logger.error(f"Pitch validation permanently failed: {error_msg}")
        job["pitch"] = f"\u26a0\ufe0f WARNING: Validation failed ({error_msg})\n\n{pitch}"

    return state
