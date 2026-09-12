import os
import json
import logging
from typing import List

logger = logging.getLogger(__name__)
IGNORED_COMPANIES_PATH = "data/ignored_companies.json"

DEFAULT_IGNORED_COMPANIES = [
    "MyTalent",
    "My Talent",
    "mytalent.io"
]


def get_ignored_companies() -> List[str]:
    """Retrieve the list of ignored company names from storage."""
    if not os.path.exists(IGNORED_COMPANIES_PATH):
        save_ignored_companies(DEFAULT_IGNORED_COMPANIES)
        return list(DEFAULT_IGNORED_COMPANIES)
    try:
        with open(IGNORED_COMPANIES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                return data.get("companies", [])
    except Exception as e:
        logger.error(f"Error loading ignored companies: {e}")
    return list(DEFAULT_IGNORED_COMPANIES)


def save_ignored_companies(companies: List[str]) -> bool:
    """Save the list of ignored companies to storage."""
    os.makedirs(os.path.dirname(IGNORED_COMPANIES_PATH), exist_ok=True)
    try:
        with open(IGNORED_COMPANIES_PATH, "w", encoding="utf-8") as f:
            json.dump(companies, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Error saving ignored companies: {e}")
        return False


def add_ignored_company(company_name: str) -> bool:
    """Add a new company to the ignored list if not already present."""
    companies = get_ignored_companies()
    clean_name = company_name.strip()
    if not clean_name:
        return False
    # Check case-insensitive duplicate
    for c in companies:
        if c.lower() == clean_name.lower():
            return True
    companies.append(clean_name)
    return save_ignored_companies(companies)


def remove_ignored_company(company_name: str) -> bool:
    """Remove a company from the ignored list."""
    companies = get_ignored_companies()
    clean_name = company_name.strip().lower()
    updated = [c for c in companies if c.lower() != clean_name]
    return save_ignored_companies(updated)


def is_company_ignored(company_name: str) -> bool:
    """Check whether a given company name matches any ignored company rule."""
    if not company_name:
        return False
    target = company_name.lower().replace(" ", "").strip()
    for ignored in get_ignored_companies():
        normalized_ignored = ignored.lower().replace(" ", "").strip()
        if normalized_ignored and normalized_ignored in target:
            return True
    return False
