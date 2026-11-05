# The people PayGuard can send money to. For the hackathon these are the
# PayPal sandbox test accounts; later they can come from the phone's contacts.
CONTACTS = [
    {"name": "Sam Kumar", "email": "sb-8pugp53567304@personal.example.com"},
    {"name": "Sam Sun", "email": "sb-x9t43k53569337@personal.example.com"},
    {"name": "Priya Raj", "email": "sb-oaavd53471227@business.example.com"},
]


def find_contacts(name: str) -> list[dict]:
    """Return every contact whose name matches what the user said, word by word.

    'sam' -> Sam Kumar + Sam Sun, 'sam sun' -> Sam Sun. Each word must match the
    START of a name word, so 'am' or an empty name never match anybody.
    """
    said = name.strip().lower().split()
    if not said:
        return []
    matches = []
    for contact in CONTACTS:
        parts = contact["name"].lower().split()
        if all(any(part.startswith(word) for part in parts) for word in said):
            matches.append(contact)
    return matches


def find_by_email(email: str) -> dict | None:
    email = email.strip().lower()
    return next((c for c in CONTACTS if c["email"] == email), None)
