"""Interface locale (navigateur) du projet — voir ``iot_audit/ui/server.py``.

Ce paquet ne contient aucune logique métier : il lance les mêmes commandes que
l'opérateur taperait, et il rend lisibles les objets que la chaîne produit déjà
(``RunOutcome``, ``Identification``, journal HMAC). Rien n'est recalculé ici —
une seconde formule de confiance dans l'UI serait exactement le défaut que C2
interdit (docs/03 §3).
"""
