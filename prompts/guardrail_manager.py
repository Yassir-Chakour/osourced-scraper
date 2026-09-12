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


def update_guardrails_from_feedback(user_feedback: str) -> str:
    """
    Takes natural language feedback from the user, uses LLM to synthesize
    it into crisp, permanent prompt rules, and updates data/guardrails.json.
    """
    from graph.nodes.pitch_writer import call_llm

    current_rules = get_guardrails()
    current_rules_text = "\n".join(f"- {r}" for r in current_rules) if current_rules else "(Keine bisherigen Regeln)"

    prompt = f"""Du bist ein Prompt-Engineering-Assistent für ein automatisches Bewerbungssystem auf Deutsch.
Der Benutzer hat Feedback zu einer Bewerbung oder allgemeine Anweisungen gegeben.

Bisherige aktive Regeln / Guardrails:
{current_rules_text}

Neues Feedback vom Benutzer:
"{user_feedback}"

AUFGABE:
Analysiere das Feedback und formuliere 1 bis 3 prägnante, klare Regeln auf Deutsch, die in zukünftigen Bewerbungen beachtet werden müssen (z. B. "Verwende immer Du statt Sie", "Erwähne kein n8n mehr", "Fasse die E-Mail auf maximal 80 Wörter zusammen").
Wenn das Feedback einer alten Regel widerspricht, ersetze die alte Regel.

Antworte ausschließlich im JSON-Format:
{{
  "action": "added" | "updated" | "clarified",
  "new_rules": ["Regel 1", "Regel 2"],
  "summary_for_user": "Kurze, freundliche Erklärung auf Deutsch für den Benutzer in Telegram, was geändert wurde."
}}
"""
    try:
        response_text = call_llm(prompt, json_mode=True)
        data = json.loads(response_text)
        new_rules = data.get("new_rules", [])
        summary = data.get("summary_for_user", "Regeln wurden aktualisiert.")

        if new_rules:
            # Merge while avoiding exact duplicates
            merged = list(current_rules)
            for r in new_rules:
                r_clean = r.strip("- ").strip()
                if r_clean and r_clean not in merged:
                    merged.append(r_clean)
            save_guardrails(merged)
            
            rules_bullet_list = "\n".join(f"• {r}" for r in merged)
            return (
                f"✅ **Prompt-Guardrails aktualisiert!**\n\n"
                f"{summary}\n\n"
                f"📋 **Aktive Regeln ({len(merged)}):**\n"
                f"{rules_bullet_list}\n\n"
                f"_Alle zukünftigen Bewerbungen werden diese Regeln automatisch beachten._"
            )
        else:
            return f"ℹ️ {summary}"

    except Exception as e:
        logger.error(f"Failed to update guardrails via LLM: {e}")
        # Fallback: add raw feedback as a direct rule
        clean_fb = user_feedback.strip()
        if clean_fb:
            current_rules.append(clean_fb)
            save_guardrails(current_rules)
            return (
                f"✅ **Regel hinzugefügt (Fallback):**\n"
                f"• {clean_fb}\n\n"
                f"_Gespeichert in Guardrails._"
            )
        return "❌ Fehler beim Verarbeiten des Feedbacks. Bitte versuche es erneut."
