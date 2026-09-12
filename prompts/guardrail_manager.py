import os
import json
import logging
from typing import List

logger = logging.getLogger(__name__)
GUARDRAILS_PATH = "data/guardrails.json"


def get_guardrails() -> List[str]:
    """Retrieve the list of active guardrail strings from storage."""
    if not os.path.exists(GUARDRAILS_PATH):
        return []
    try:
        with open(GUARDRAILS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                return data.get("guardrails", [])
    except Exception as e:
        logger.error(f"Error loading guardrails: {e}")
    return []


def save_guardrails(rules: List[str]) -> bool:
    """Save the list of guardrails to storage."""
    os.makedirs(os.path.dirname(GUARDRAILS_PATH), exist_ok=True)
    try:
        with open(GUARDRAILS_PATH, "w", encoding="utf-8") as f:
            json.dump(rules, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Error saving guardrails: {e}")
        return False


def reset_guardrails() -> str:
    """Clear all active guardrails."""
    save_guardrails([])
    return "🧹 Alle benutzerdefinierten Prompt-Guardrails wurden zurückgesetzt."


def process_user_feedback(user_feedback: str) -> str:
    """
    Takes natural language instructions/feedback from the user.
    Handles:
    - Adding companies to blacklist / ignored list
    - Removing companies from blacklist
    - Updating prompt guardrail rules
    - General questions or fallback
    """
    from graph.nodes.pitch_writer import call_llm
    from db.ignored_companies import get_ignored_companies, add_ignored_company, remove_ignored_company

    current_rules = get_guardrails()
    current_rules_text = "\n".join(f"- {r}" for r in current_rules) if current_rules else "(Keine bisherigen Regeln)"
    ignored_companies = get_ignored_companies()
    ignored_companies_text = ", ".join(f"'{c}'" for c in ignored_companies) if ignored_companies else "(Keine)"

    prompt = f"""Du bist der persönliche KI-Assistent für ein automatisiertes Bewerbungssystem auf Deutsch.
Der Benutzer sendet dir Anweisungen, Feedback oder Befehle im Telegram-Chat.

Aktuelle Prompt-Regeln (Guardrails für Anschreiben):
{current_rules_text}

Aktuell blockierte Firmen (Blacklist - keine Bewerbungen an diese Firmen):
{ignored_companies_text}

Nachricht des Benutzers:
"{user_feedback}"

AUFGABE:
Analysiere die Absicht des Benutzers und extrahiere im JSON-Format:
1. "blacklist_add": Liste von Firmennamen, die gesperrt / ignoriert werden sollen (z. B. ["World Bite GmbH"]). Falls keine, [].
2. "blacklist_remove": Liste von Firmennamen, die entsperrt werden sollen. Falls keine, [].
3. "new_rules": Liste von neuen oder angepassten Regeln für Anschreiben (z. B. ["Verwende immer Du statt Sie", "Erwähne kein n8n"]). Falls keine, [].
4. "summary_for_user": Eine kurze, freundliche Erklärung auf Deutsch für den Benutzer, was ausgeführt wurde.

Antworte ausschließlich im JSON-Format:
{{
  "blacklist_add": [],
  "blacklist_remove": [],
  "new_rules": [],
  "summary_for_user": "..."
}}
"""
    try:
        response_text = call_llm(prompt, json_mode=True)
        data = json.loads(response_text)
        
        blacklist_add = data.get("blacklist_add", [])
        blacklist_remove = data.get("blacklist_remove", [])
        new_rules = data.get("new_rules", [])
        summary = data.get("summary_for_user", "")

        added_companies = []
        for comp in blacklist_add:
            comp_clean = comp.strip()
            if comp_clean:
                add_ignored_company(comp_clean)
                added_companies.append(comp_clean)

        removed_companies = []
        for comp in blacklist_remove:
            comp_clean = comp.strip()
            if comp_clean:
                remove_ignored_company(comp_clean)
                removed_companies.append(comp_clean)

        merged_rules = list(current_rules)
        if new_rules:
            for r in new_rules:
                r_clean = r.strip("- ").strip()
                if r_clean and r_clean not in merged_rules:
                    merged_rules.append(r_clean)
            save_guardrails(merged_rules)

        parts = []
        if summary:
            parts.append(summary)
        if added_companies:
            parts.append("🚫 **Firma(en) blockiert:** " + ", ".join(f"`{c}`" for c in added_companies))
        if removed_companies:
            parts.append("✅ **Firma(en) freigegeben:** " + ", ".join(f"`{c}`" for c in removed_companies))
        if new_rules:
            rules_bullet_list = "\n".join(f"• {r}" for r in merged_rules)
            parts.append(f"📋 **Aktive Prompt-Guardrails ({len(merged_rules)}):**\n{rules_bullet_list}")

        return "\n\n".join(parts) if parts else "ℹ️ Anweisung ausgeführt."

    except Exception as e:
        logger.error(f"Failed to process user message via LLM: {e}")
        clean_fb = user_feedback.strip()
        if clean_fb:
            current_rules.append(clean_fb)
            save_guardrails(current_rules)
            return (
                f"✅ **Regel hinzugefügt (Fallback):**\n"
                f"• {clean_fb}\n\n"
                f"_Gespeichert in Guardrails._"
            )
        return "❌ Fehler beim Verarbeiten der Anweisung."


def update_guardrails_from_feedback(user_feedback: str) -> str:
    """Backwards-compatible wrapper."""
    return process_user_feedback(user_feedback)
