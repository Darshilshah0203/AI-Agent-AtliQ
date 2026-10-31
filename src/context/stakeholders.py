"""Stakeholder registry loader from stakeholders.csv."""

import csv
import os
import re
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Stakeholder:
    name: str
    role: str
    email: str
    doc_link: str

    @property
    def doc_id(self) -> Optional[str]:
        """Extract Google Doc ID from the doc_link URL."""
        match = re.search(r"/d/([a-zA-Z0-9-_]+)", self.doc_link)
        if match:
            return match.group(1)
        return None


def load_stakeholders(csv_path: Optional[str] = None) -> List[Stakeholder]:
    """Load stakeholders list from CSV.
    
    Checks specified path, then 'stakeholders.csv', then 'Stakeholders Input/stakeholders.csv'.
    """
    candidate_paths = [
        csv_path,
        "stakeholders.csv",
        os.path.join("Stakeholders Input", "stakeholders.csv"),
    ]

    resolved_path = None
    for p in candidate_paths:
        if p and os.path.exists(p):
            resolved_path = p
            break

    if not resolved_path:
        raise FileNotFoundError("Could not locate stakeholders.csv in workspace root or Stakeholders Input/.")

    stakeholders: List[Stakeholder] = []
    with open(resolved_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("name") or "").strip()
            role = (row.get("role") or "").strip()
            email = (row.get("email") or "").strip()
            doc_link = (row.get("doc_link") or row.get("Doc link") or "").strip()
            if name and email:
                stakeholders.append(
                    Stakeholder(
                        name=name,
                        role=role,
                        email=email,
                        doc_link=doc_link,
                    )
                )

    return stakeholders

