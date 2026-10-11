"""iot_audit — reconnaissance d'objets connectés pour audit de sécurité IoT.

Le paquet est volontairement plat : un module par responsabilité, aucune
dépendance circulaire. Les contrats (dataclasses gelées) vivent dans
``iot_audit.contracts`` et sont la seule interface entre les couches
(voir ``docs/03-architecture.md`` §2).
"""

__version__ = "0.1.0"
