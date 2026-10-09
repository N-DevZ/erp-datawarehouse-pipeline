-- Schéma source : ERP générique aucune structure propriétaire.
-- Aucune donnée réelle. Rejouable : les tables sont recréées à chaque passage.

DROP TABLE IF EXISTS factures CASCADE;
DROP TABLE IF EXISTS lignes_commande CASCADE;
DROP TABLE IF EXISTS commandes CASCADE;
DROP TABLE IF EXISTS articles CASCADE;
DROP TABLE IF EXISTS clients CASCADE;

CREATE TABLE clients (
    id                  BIGSERIAL PRIMARY KEY,
    code_client         TEXT NOT NULL UNIQUE,
    raison_sociale      TEXT NOT NULL,
    email               TEXT,
    telephone           TEXT,
    adresse             TEXT,
    code_postal         TEXT,
    ville               TEXT,
    pays                TEXT NOT NULL DEFAULT 'FRANCE',
    segment             TEXT NOT NULL,
    date_creation       DATE NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE articles (
    id                  BIGSERIAL PRIMARY KEY,
    reference           TEXT NOT NULL UNIQUE,
    libelle             TEXT NOT NULL,
    famille             TEXT NOT NULL,
    prix_unitaire_ht    NUMERIC(10,2) NOT NULL,
    unite               TEXT NOT NULL DEFAULT 'U',
    actif               BOOLEAN NOT NULL DEFAULT true,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE commandes (
    id                  BIGSERIAL PRIMARY KEY,
    numero_commande     TEXT NOT NULL UNIQUE,
    client_id           BIGINT NOT NULL REFERENCES clients(id),
    date_commande       DATE NOT NULL,
    statut              TEXT NOT NULL,
    canal               TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE lignes_commande (
    id                  BIGSERIAL PRIMARY KEY,
    commande_id         BIGINT NOT NULL REFERENCES commandes(id),
    article_id          BIGINT NOT NULL REFERENCES articles(id),
    numero_ligne        INTEGER NOT NULL,
    quantite            INTEGER NOT NULL,
    prix_unitaire_ht    NUMERIC(10,2) NOT NULL,
    remise_pct          NUMERIC(5,2) NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (commande_id, numero_ligne)
); 

CREATE TABLE factures (
    id                  BIGSERIAL PRIMARY KEY,
    numero_facture      TEXT NOT NULL UNIQUE,
    commande_id         BIGINT NOT NULL REFERENCES commandes(id),
    date_facture        DATE NOT NULL,
    montant_ht          NUMERIC(12,2) NOT NULL,
    statut_paiement     TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ================================================================================
-- Index d'extraction -> Optimisation des requêtes de chargement incrémental.
-- Permet de cibler instantanément les données modifiées.
-- ================================================================================

CREATE INDEX idx_clients_updated_at                 ON clients(updated_at);
CREATE INDEX idx_articles_updated_at                ON articles(updated_at);
CREATE INDEX idx_commandes_updated_at               ON commandes(updated_at);
CREATE INDEX idx_lignes_updated_at                  ON lignes_commande(updated_at);
CREATE INDEX idx_factures_updated_at                ON factures(updated_at);

-- ================================================================================
-- Index de jointure placés sur les clés étrangères les plus sollicitées.
-- Accélération du traitement en évitant de parcourir chaque ligne une par une.
-- ================================================================================

CREATE INDEX idx_commandes_client_id                ON commandes(client_id);
CREATE INDEX idx_lignes_commande_id                 ON lignes_commande(commande_id);
CREATE INDEX idx_factures_commande_id               ON factures(commande_id);