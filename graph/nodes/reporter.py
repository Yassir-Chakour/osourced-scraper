import random
import logging
from graph.state import GraphState
from telegram_bot.bot import send_message_sync

logger = logging.getLogger(__name__)

def reporter_node(state: GraphState) -> GraphState:
    logger.info("Generating final run report...")

    jobs = state.get("jobs", [])
    applied_jobs = [j for j in jobs if j.get("status") == "applied"]
    error_jobs = [j for j in jobs if j.get("status") == "error"]

    if not applied_jobs:
        # User requirement: If no new jobs applied today
        logger.info("No new jobs applied today. Sending empty notification.")
        send_message_sync("hello shinobi no job today found 9awadnaha")
        return state

    # User requirement: If jobs applied, pick 1 random sample to inspect
    sample = random.choice(applied_jobs)
    count = len(applied_jobs)

    report_lines = [
        f"🚀 **Osourced Autopilot:** {count} neue Bewerbung(en) heute automatisch versendet!\n",
        "🎲 **Zufälliges Bewerbungsbeispiel zur Überprüfung:**",
        f"📌 **{sample.get('title', 'Stelle')}**",
        f"🏢 Firma: {sample.get('company_name', 'Unbekannt')}",
        f"🔗 Link: {sample.get('link', '')}\n",
        "✉️ **Gesendeter Pitch:**",
        "─────────────────────",
        sample.get("pitch", "(Kein Pitch-Text vorhanden)"),
        "─────────────────────\n",
        "💡 **Prompt anpassen?**",
        "Antworte einfach direkt auf diese Nachricht mit deinen Wünschen (z. B. *\"Verwende immer Du statt Sie\"* oder *\"Erwähne kein n8n mehr\"*). Ich übernehme das sofort als feste Regel für zukünftige Bewerbungen."
    ]

    if error_jobs:
        report_lines.append(f"\n⚠️ ({len(error_jobs)} Bewerbung(en) fehlgeschlagen)")

    report_text = "\n".join(report_lines)
    logger.info(f"Sending final report with random sample ('{sample.get('title')}') to Telegram...")
    send_message_sync(report_text)

    return state

