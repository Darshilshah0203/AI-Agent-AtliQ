"""Google Docs API reader and brief cache manager."""

import os
import re
from typing import Optional
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.config import Config, load_config
from src.context.stakeholders import Stakeholder


DOCS_SCOPE = ["https://www.googleapis.com/auth/documents.readonly"]


def sanitize_name_for_cache(name: str) -> str:
    """Sanitize stakeholder name for cache filename."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name).lower()


def extract_text_from_doc(doc_data: dict) -> str:
    """Extract plain text from Google Doc JSON structure."""
    text_pieces = []
    body = doc_data.get("body", {})
    for element in body.get("content", []):
        if "paragraph" in element:
            for p_elem in element["paragraph"].get("elements", []):
                if "textRun" in p_elem:
                    text_pieces.append(p_elem["textRun"].get("content", ""))
    return "".join(text_pieces).strip()


def get_cached_brief(stakeholder: Stakeholder, cache_dir: str = "context/cache") -> Optional[str]:
    """Retrieve brief from local cache or seed context files."""
    # 1. Check cached brief file
    cache_file = os.path.join(cache_dir, f"{sanitize_name_for_cache(stakeholder.name)}.txt")
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    return content
        except Exception:
            pass

    # 2. Check seed file for Bruce Haryali
    if "bruce" in stakeholder.name.lower():
        bruce_seed_paths = [
            os.path.join("context", "bruce_context.md"),
            os.path.join("Downloads", "AnalystAgent", "bruce_context.md"),
        ]
        for bp in bruce_seed_paths:
            if os.path.exists(bp):
                try:
                    with open(bp, "r", encoding="utf-8") as f:
                        return f.read().strip()
                except Exception:
                    pass

    return None


def save_brief_to_cache(stakeholder: Stakeholder, content: str, cache_dir: str = "context/cache") -> None:
    """Save successfully fetched brief to local cache directory."""
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = os.path.join(cache_dir, f"{sanitize_name_for_cache(stakeholder.name)}.txt")
    with open(cache_file, "w", encoding="utf-8") as f:
        f.write(content)


def fetch_stakeholder_brief(
    stakeholder: Stakeholder,
    config: Optional[Config] = None,
    cache_dir: str = "context/cache",
) -> Optional[str]:
    """Fetch stakeholder private brief via Google Docs API with cache fallback.
    
    Rules (PRD 7.3 & 9):
    - Fresh read on every run using Google Docs API (documents.readonly).
    - If read fails, use the last saved copy and log that fallback.
    - If no saved copy exists, skip that stakeholder and retry next run.
    - Never send a generic personalized digest.
    """
    if config is None:
        config = load_config()

    doc_id = stakeholder.doc_id
    if not doc_id:
        print(f"  [Context Error] Invalid or missing Google Doc link for {stakeholder.name}: {stakeholder.doc_link}")
        return get_cached_brief(stakeholder, cache_dir)

    # Check for live Google OAuth credentials
    has_live_creds = (
        config.google_client_id
        and not config.google_client_id.startswith("mock_")
        and config.google_refresh_token
        and not config.google_refresh_token.startswith("mock_")
    )

    if has_live_creds:
        try:
            creds = Credentials(
                token=None,
                refresh_token=config.google_refresh_token,
                client_id=config.google_client_id,
                client_secret=config.google_client_secret,
                token_uri="https://oauth2.googleapis.com/token",
                scopes=DOCS_SCOPE,
            )
            service = build("docs", "v1", credentials=creds, cache_discovery=False)
            doc = service.documents().get(documentId=doc_id).execute()
            brief_text = extract_text_from_doc(doc)

            if brief_text:
                save_brief_to_cache(stakeholder, brief_text, cache_dir)
                print(f"  [Context] Fresh brief fetched from Google Docs for {stakeholder.name}.")
                return brief_text

        except Exception as err:
            print(f"  [Context Warning] Google Docs API error for {stakeholder.name}: {err}. Attempting cache fallback...")

    # Fallback to cached brief
    cached = get_cached_brief(stakeholder, cache_dir)
    if cached:
        print(f"  [Context Notice] Using saved brief for {stakeholder.name} (fallback).")
        # Ensure it's in context/cache for persistence
        save_brief_to_cache(stakeholder, cached, cache_dir)
        return cached

    print(f"  [Context Warning] No saved brief found for {stakeholder.name}. Skipping personalized digest.")
    return None

