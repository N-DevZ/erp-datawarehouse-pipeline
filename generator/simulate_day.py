"""Simule une journée d'activité ERP sur erp_source.

Usage : python generator/simulate_day.py --date 2026-09-02

Une journée : des commandes qui avancent, des factures qui naissent et se
règlent, quelques fiches modifiées, puis les nouvelles commandes du jour.
Tout passe dans une seule transaction : soit la journée entière est écrite,
soit rien. Les dates métier suivent --date ; updated_at, lui, est posé par le
trigger avec l'heure réelle de la modification.
"""

# ===========================================================================
# 1. IMPORTATIONS DES MODULES
# ===========================================================================
import argparse
import os
import random
import sys
from datetime import date

import psycopg2
from dotenv import load_dotenv
from faker import Faker
from psycopg2.extras import execute_values

# Charge le fichier nommé .env dans le système pour être utilisé par la suite par os
load_dotenv()


# ===========================================================================
# 2. INITIALISATION ET CONFIGURATION STATISTIQUE
# ===========================================================================

# Volumes d'une journée type : (minimum, maximum)
NOUVELLES_COMMANDES = (40, 80)
LIVRAISONS          = (40, 70)          # expediee  -> livree
EXPEDITIONS         = (40, 70)          # validee   -> expediee, avec sa facture
VALIDATIONS         = (30, 60)          # brouillon -> validee
ANNULATIONS         = (1, 4)            # brouillon -> annulee
REGULARISATIONS     = (2, 6)            # facture en_retard -> payee
RETARDS             = (3, 8)            # facture emise     -> en_retard
PAIEMENTS           = (50, 90)          # facture emise     -> payee
CLIENTS_MODIFIES    = (3, 8)
ARTICLES_MODIFIES   = (0, 3)

# Référentiel des sources d'acquisition d'une commande
CANAUX = ["web", "telephone", "commercial", "edi"]


# ===========================================================================
# 3. FONCTIONS UTILITAIRES ET DE CONTRÔLE
# ===========================================================================

def connexion():
    """Ouvre et retourne la connexion à la base de données PostgreSQL."""
    return psycopg2.connect(
        host="localhost",
        port=5433,
        dbname=os.environ["ERP_SOURCE_DB"],
        user=os.environ["ERP_SOURCE_USER"],
        password=os.environ["ERP_SOURCE_PASSWORD"],
    )

    

def lire_date():
    """Lit et valide l'argument --date passé en ligne de commande (Format ISO requis)."""
    parser = argparse.ArgumentParser(description="Simule une journée d'activité ERP.")
    parser.add_argument(
        "--date", required=True, type=date.fromisoformat,
        help="jour simulé, au format AAAA-MM-JJ",
    )
    return parser.parse_args().date



def verifier_chronologie(cur, jour):
    """
    Refuse de simuler un jour déjà couvert : le temps ne revient pas en arrière.
    Coupe l'exécution du script via sys.exit() si la règle n'est pas respectée.
    """
    cur.execute("SELECT max(date_commande) FROM commandes;")
    derniere = cur.fetchone()[0]
    if derniere is not None and jour <= derniere:
        sys.exit(
            f"Refus : la base contient déjà des commandes au {derniere}. "
            f"Simule un jour postérieur."
        )

        

def tirer(cur, sql, bornes):
    """Tire au hasard entre min et max identifiants parmi ceux que renvoie la requête sql."""
    cur.execute(sql)
    ids = [ligne[0] for ligne in cur.fetchall()]
    return random.sample(ids, min(random.randint(*bornes), len(ids)))



def changer(cur, table, colonne, ids, valeur):
    """Exécute un UPDATE en masse sur une liste d'identifiants ciblés."""
    if ids:
        cur.execute(
            f"UPDATE {table} SET {colonne} = %s WHERE id = ANY(%s);", (valeur, ids)
        )
    return len(ids)


# ===========================================================================
# 4. LOGIQUE MÉTIER DE LA JOURNÉE
# ===========================================================================


def avancer_commandes(cur):
    """
    Fait avancer les statuts en partant de la fin de la chaîne.
    Livrer avant d'expédier, expédier avant de valider : ainsi aucune commande
    ne saute deux étapes dans la même journée.
    """
    livrees = tirer(cur, "SELECT id FROM commandes WHERE statut = 'expediee' ORDER BY id;", LIVRAISONS)
    changer(cur, "commandes", "statut", livrees, "livree")

    expediees = tirer(cur, "SELECT id FROM commandes WHERE statut = 'validee' ORDER BY id;", EXPEDITIONS)
    changer(cur, "commandes", "statut", expediees, "expediee")

    validees = tirer(cur, "SELECT id FROM commandes WHERE statut = 'brouillon' ORDER BY id;", VALIDATIONS)
    changer(cur, "commandes", "statut", validees, "validee")

    annulees = tirer(cur, "SELECT id FROM commandes WHERE statut = 'brouillon' ORDER BY id;", ANNULATIONS)
    changer(cur, "commandes", "statut", annulees, "annulee")

    return len(livrees), expediees, len(validees), len(annulees)


def regler_factures(cur):
    """
    Gère les flux financiers.
    Même principe : la régularisation d'abord, pour qu'un retard du jour ne soit pas payé le jour même.
    """
    regularisees = tirer(cur, "SELECT id FROM factures WHERE statut_paiement = 'en_retard' ORDER BY id;", REGULARISATIONS)
    changer(cur, "factures", "statut_paiement", regularisees, "payee")

    retards = tirer(cur, "SELECT id FROM factures WHERE statut_paiement = 'emise' ORDER BY id;", RETARDS)
    changer(cur, "factures", "statut_paiement", retards, "en_retard")

    payees = tirer(cur, "SELECT id FROM factures WHERE statut_paiement = 'emise' ORDER BY id;", PAIEMENTS)
    changer(cur, "factures", "statut_paiement", payees, "payee")

    return len(regularisees), len(retards), len(payees)


def facturer(cur, jour, commande_ids):
    """Génère une facture par commande expédiée aujourd'hui, au montant exact de ses lignes."""
    if not commande_ids:
        return 0
        
    cur.execute("SELECT coalesce(max(id), 0) FROM factures;")
    base = cur.fetchone()[0]
    
    # Calcul du montant total de la commande incluant la remise
    cur.execute(
        """SELECT commande_id,
                  round(sum(quantite * prix_unitaire_ht * (1 - remise_pct / 100)), 2)
           FROM lignes_commande
           WHERE commande_id = ANY(%s)
           GROUP BY commande_id
           ORDER BY commande_id;""",
        (commande_ids,),    
    )
    
    # Préparation et insertion en masse
    lignes = [
        (f"FAC{base + i:08d}", commande_id, jour, montant, "emise")
        for i, (commande_id, montant) in enumerate(cur.fetchall(), start=1)
    ]
    execute_values(
        cur,
        """INSERT INTO factures
           (numero_facture, commande_id, date_facture, montant_ht, statut_paiement)
           VALUES %s""",
        lignes,
    )
    return len(lignes)


def modifier_fiches(cur, fake):
    """Quelques clients changent de coordonnées, quelques articles subissent l'inflation."""
    
    # Modification d'informations de contact client
    clients = tirer(cur, "SELECT id FROM clients ORDER BY id;", CLIENTS_MODIFIES)
    for client_id in clients:
        cur.execute(
            "UPDATE clients SET telephone = %s, email = %s WHERE id = %s;",
            (fake.phone_number(), fake.company_email(), client_id),
        )

    # Hausse de prix pour certains articles (2%, 3% ou 5%)
    articles = tirer(cur, "SELECT id FROM articles WHERE actif ORDER BY id;", ARTICLES_MODIFIES)
    for article_id in articles:
        cur.execute(
            "UPDATE articles SET prix_unitaire_ht = round(prix_unitaire_ht * (1 + %s / 100.0), 2) "
            "WHERE id = %s;",
            (random.choice([2, 3, 5]), article_id),
        )
    return len(clients), len(articles)


def creer_commandes(cur, jour):
    """Génère les nouvelles commandes du jour, au prix catalogue du jour — donc après les hausses."""
    
    # Récupération des référentiels actuels
    cur.execute("SELECT id FROM clients ORDER BY id;")
    clients = [ligne[0] for ligne in cur.fetchall()]
    cur.execute("SELECT id, prix_unitaire_ht FROM articles WHERE actif ORDER BY id;")
    prix = dict(cur.fetchall())
    articles = list(prix)

    # Préparation des en-têtes de commandes
    cur.execute("SELECT coalesce(max(id), 0) FROM commandes;")
    base = cur.fetchone()[0]
    entetes = [
        (
            f"CMD{base + i:08d}",
            random.choice(clients),
            jour,
            random.choices(["brouillon", "validee"], weights=[40, 60])[0],
            random.choice(CANAUX),
        )
        for i in range(1, random.randint(*NOUVELLES_COMMANDES) + 1)
    ]
    
    # Insertion et récupération immédiate (RETURNING) des IDs générés par la base
    ids = execute_values(
        cur,
        """INSERT INTO commandes
           (numero_commande, client_id, date_commande, statut, canal)
           VALUES %s
           RETURNING id""",
        entetes,
        fetch=True,
    )

    # Préparation des lignes rattachées aux commandes créées
    lignes = []
    for (commande_id,) in ids:
        for numero_ligne in range(1, random.randint(1, 5) + 1):
            article_id = random.choice(articles)
            lignes.append((
                commande_id, article_id, numero_ligne,
                random.randint(1, 20), prix[article_id],
                random.choice([0, 0, 0, 0, 5, 10, 15]),
            ))
            
    execute_values(
        cur,
        """INSERT INTO lignes_commande
           (commande_id, article_id, numero_ligne, quantite,
            prix_unitaire_ht, remise_pct)
           VALUES %s""",
        lignes,
    )
    return len(ids), len(lignes)


# ===========================================================================
# 5. TRAITEMENT PRINCIPAL
# ===========================================================================

def main():
    jour = lire_date()
    
    # Fixation des graines aléatoires sur la base de la date pour rendre la journée reproductible
    random.seed(jour.toordinal())
    Faker.seed(jour.toordinal())
    fake = Faker("fr_FR")

    conn = connexion()
    try:
        # L'utilisation du with garantit la fermeture propre du curseur
        with conn.cursor() as cur:
            verifier_chronologie(cur, jour)
            livrees, expediees, validees, annulees = avancer_commandes(cur)
            regularisees, retards, payees = regler_factures(cur)
            n_factures = facturer(cur, jour, expediees)
            n_clients, n_articles = modifier_fiches(cur, fake)
            n_commandes, n_lignes = creer_commandes(cur, jour)
            
        # Validation d'une transaction unique : soit tout passe, soit rien n'est écrit.
        conn.commit()
    finally:
        # Clôture sécurisée de la connexion à la base
        conn.close()

    # Affichage du résumé de la journée
    print(f"Journée du {jour}")
    print(f"  commandes : +{n_commandes} créées | livrées {livrees}, "
          f"expédiées {len(expediees)}, validées {validees}, annulées {annulees}")
    print(f"  lignes    : +{n_lignes}")
    print(f"  factures  : +{n_factures} émises | payées {payees}, "
          f"en retard {retards}, régularisées {regularisees}")
    print(f"  fiches    : clients {n_clients}, articles {n_articles}")

# Lance la fonction main seulement si le script est appelé directement dans le terminal
if __name__ == "__main__":
    main()
