from pipeline.evaluate import evaluate_transcription

# 1. Fake transcription (IMPORTANT)
transcription = """Agent: Bonjour madame, je vous appelle concernant votre assurance.
Client: Oui bonjour.
Agent: Est-ce que vous êtes disponible ?
Client: Oui.
Agent: Merci beaucoup, je vais vérifier votre dossier.
Client: D'accord.
"""

# 2. Fake criteria (comme DB)
criteria = [
    {"key": "greeting", "label": "Accueil", "max_pts": 20, "description": "Salutation correcte", "is_active": True},
    {"key": "politeness", "label": "Politesse", "max_pts": 20, "description": "Ton respectueux", "is_active": True},
    {"key": "resolution", "label": "Résolution", "max_pts": 60, "description": "Problème traité", "is_active": True},
]

# 3. Call function
result = evaluate_transcription(transcription, criteria)

print("\n===== RESULT =====")
print(result)