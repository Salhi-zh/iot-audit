-- ===========================================================================
--  iot_audit/vuln/schema.sql — spine NVD (docs/04 §2, CDS §7)
-- ===========================================================================
--  Trois tables, un seul ecrivain (WAL), ingestion hors ligne.
--
--  * feed_versions  — tracabilite : quel fichier, quel sha256, quand ingere,
--                     combien de lignes. C'est la piece qui rend un run
--                     reproductible (D13 : le sha256 du snapshot est enregistre
--                     dans chaque run).
--  * cves           — metadonnees CVE (statut, CVSS, dates). Le statut est
--                     conserve pour que les CVE *Rejected* restent visibles :
--                     sans cela, un rapport passe liste une CVE qui a disparu
--                     de la base sans explication (CDS §7.6).
--  * cve_cpe_criteria — criteres CPE denormalises en lignes, `part='h'` seul.
--                     Le motif CPE original est conserve (`criteria`) : c'est
--                     la piece d'audit qui montre *pourquoi* une CVE remonte.
--
--  Idempotent : CREATE ... IF NOT EXISTS. Rejouer une ingestion ne duplique rien
--  (UNIQUE (cve_id, match_criteria_id) + upsert).
-- ===========================================================================

PRAGMA foreign_keys = ON;
PRAGMA journal_mode  = WAL;

CREATE TABLE IF NOT EXISTS feed_versions (
  id            INTEGER PRIMARY KEY,
  feed_name     TEXT NOT NULL,          -- ex. nvdcve-2.0-2024.json.gz
  sha256        TEXT NOT NULL,
  published_at  TEXT,                   -- date de publication du flux (NVD)
  ingested_at   TEXT NOT NULL,          -- date d'ingestion (nous)
  row_count     INTEGER,                -- nb de lignes de criteres inserees
  cve_count     INTEGER,                -- nb de CVE vues dans le flux
  UNIQUE (feed_name, sha256)
);

CREATE TABLE IF NOT EXISTS cves (
  cve_id            TEXT PRIMARY KEY,
  vuln_status       TEXT,               -- Analyzed | Modified | Rejected | Awaiting Analysis
  published         TEXT,
  last_modified     TEXT,
  description       TEXT,               -- premiere description anglaise, tronquee
  cvss_v3_score     REAL,
  cvss_v3_severity  TEXT,               -- LOW | MEDIUM | HIGH | CRITICAL
  cvss_v3_vector    TEXT,
  feed_version_id   INTEGER NOT NULL REFERENCES feed_versions (id)
);

CREATE TABLE IF NOT EXISTS cve_cpe_criteria (
  id                  INTEGER PRIMARY KEY,
  cve_id              TEXT    NOT NULL,
  match_criteria_id   TEXT,
  criteria            TEXT    NOT NULL,  -- cpe:2.3:h:vendor:product:version:... (motif original)
  part                TEXT    NOT NULL,  -- 'h' uniquement (filtre a l'ingestion)
  vendor              TEXT    NOT NULL,
  product             TEXT    NOT NULL,  -- peut valoir '*'
  version             TEXT,              -- peut valoir '*'
  version_start_incl  TEXT,
  version_start_excl  TEXT,
  version_end_incl    TEXT,
  version_end_excl    TEXT,
  vulnerable          INTEGER NOT NULL DEFAULT 1,
  negate              INTEGER NOT NULL DEFAULT 0,
  operator            TEXT,              -- AND / OR du noeud parent
  feed_version_id     INTEGER NOT NULL REFERENCES feed_versions (id),
  UNIQUE (cve_id, match_criteria_id)
);

-- Chemin chaud de `search_cve` : pre-filtre (part, vendor, product).
CREATE INDEX IF NOT EXISTS ix_criteria_lookup ON cve_cpe_criteria (part, vendor, product, vulnerable);
CREATE INDEX IF NOT EXISTS ix_criteria_cve    ON cve_cpe_criteria (cve_id);
CREATE INDEX IF NOT EXISTS ix_cves_status     ON cves (vuln_status);

-- Reprise sur erreur : ou en est l'ingestion d'un flux.
CREATE TABLE IF NOT EXISTS ingest_progress (
  job         TEXT PRIMARY KEY,          -- ex. nvd:2024
  position    INTEGER NOT NULL DEFAULT 0,
  updated_at  TEXT NOT NULL
);
