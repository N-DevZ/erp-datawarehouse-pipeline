"""Peuple erp_source avec un jeu de données ERP synthétique et borné.

Données 100% fictives(Faker). Rejouable : vide les tables avant insertion. 
Les identifiants sont 1..N après TRUNCATE RESTART IDENTITY, ce qui permet de 
tirer les clés étrangères sans relire la base.  
"""

# ===========================================================================
# 1. IMPORTATIONS DES MODULES
# ===========================================================================
import os
import random
from datetime import date, timedelta

import psycopg2
from dotenv import load_dotenv
from faker import Faker
from psycopg2.extras import execute_values

# ===========================================================================
# 2. INITIALISATION ET CONFIGURATION STATISTIQUE
# ===========================================================================

# Charge le fichier nommé .env dans le système pour être utilisé par la suite par os
load_dotenv()

# Initialise le générateur de fausses données (fake) en langue française et avec les formats français
fake = Faker("fr_FR")

# Bloque les générateurs de données afin de rendre le jeu reproductible
Faker.seed(42)
random.seed(42)

# --- Paramètres de volumétrie --- 
N_CLIENTS           = 2_000
N_ARTICLES          = 500
N_COMMANDES         = 30_000
BATCH               = 1_000

# --- Paramètres temporels ---
DATE_DEBUT          = date(2025, 1, 1)
DATE_FIN            = date(2026, 9, 1)

# --- Référentiels et probabilités ---
STATUTS             = ["brouillon", "validee", "expediee", "livree", "annulee"]
POIDS_STATUTS       = [5, 12, 25, 55, 3]
SEGMENTS            = ["PME", "Grand compte", "Artisan", "Collectivite"]
FAMILLES            = ["Quincaillerie", "Outillage", "Consommable", "Electricite", "Plomberie"]
CANAUX              = ["web", "telephone", "commercial", "edi"]
UNITES              = ["U", "KG", "M", "L"]
STATUTS_PAIEMENT    = ["emise", "payee", "en_retard"]

# ===========================================================================
# 3. FONCTIONS UTILITAIRES
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

def date_entre(debut, fin):
    """Calcule d'une date aléatoire située strictement entre une date de début et une date de fin."""
    return debut + timedelta(days=random.randint(0, (fin - debut).days))

def vider(cur):
    """
    Purge totale de la base.
    Remise des compteurs (ID) à 1.
    Force la suppression même s'il y a des clés étrangèrs.
    """
    cur.execute(
       "TRUNCATE factures, lignes_commande, commandes, articles, clients "
       "RESTART IDENTITY CASCADE;"
   )

# ===========================================================================
# 4. FONCTIONS D'INSERTION DES DONNÉES
# ===========================================================================

def inserer_clients(cur):
    """Génère et insère les clients. Retourne le nombre de clients créés."""

    # Création d'une liste de tuples
    lignes = [
        (
           f"CLI{i:06d}",
           fake.company(),
           fake.company_email(),
           fake.phone_number(),
           fake.street_address(),
           fake.postcode(),
           fake.city(),
           "France",
           random.choice(SEGMENTS),
           date_entre(date(2018, 1, 1), DATE_DEBUT),
        )
        for i in range(1, N_CLIENTS + 1)
    ]

    # Injecte toute la liste de tuple en une seule fois et par lots (BATCH)
    execute_values(
        cur,
        """INSERT INTO CLIENTS
            (code_client, raison_sociale, email, telephone, adresse,
             code_postal, ville, pays, segment, date_creation)
            VALUES %s""",
        lignes, page_size=BATCH,
    )
    return len(lignes)



def inserer_articles(cur):
    """Génère les articles et sauvegarde leurs prix. Retourne le catalogue des prix."""

    lignes, prix = [], {}

    # Mémorisation du prix exact pour chaque article 
    for i in range(1, N_ARTICLES + 1):
        p = round(random.uniform(2, 900), 2)    
        prix[i] = p

        # Ajout des données dans la liste
        lignes.append((
            f"ART{i:05d}",
            f"{fake.word().capitalize()} {fake.word()}",
            random.choice(FAMILLES),
            p,
            random.choice(UNITES),
            random.random() > 0.05, # Probabilité de 95% que l'article soit actif.    
        ))

    execute_values(
        cur,
        """INSERT INTO ARTICLES
            (reference, libelle, famille, prix_unitaire_ht, unite, actif)
            VALUES %s""",
        lignes, page_size=BATCH, 
    )
    return prix # Renvoie le dictionnaire de prix entier.



def inserer_commandes(cur):
    """Génère les entêtes de commandes. Retourne un dictionnaire {id_commande: (date, statut)}."""

    lignes, infos = [], {}
    for i in range(1, N_COMMANDES + 1):
        d = date_entre(DATE_DEBUT, DATE_FIN)

        # Tirage d'un statut (selon probabilités) -> extrait la chaîne de l'élément tiré.
        statut = random.choices(STATUTS, weights=POIDS_STATUTS)[0]

        # Affectation d'un tuple pour chaque éléments de ce dictionnaire.
        infos[i] = (d, statut)

        lignes.append((
            f"CMD{i:08d}",
            random.randint(1, N_CLIENTS), # Attribution aléatoire à un client existant.
            d,
            statut,
            random.choice(CANAUX),
        ))

    execute_values(
        cur,
        """INSERT INTO COMMANDES
            (numero_commande, client_id, date_commande, statut, canal)
            VALUES %s""",
        lignes, page_size=BATCH,
    )
    return infos

    

def inserer_lignes(cur, prix_articles):
    """
    Génère le détail des commandes (les articles achetés).
    Utilise un système de "Tampon" (Buffer) pour ne pas saturer la RAM.
    """

    sql = """INSERT INTO lignes_commande
            (commande_id, article_id, numero_ligne,
                quantite, prix_unitaire_ht, remise_pct)
            VALUES %s"""
    
    tampon, totaux, inserees = [], {}, 0

    for commande_id in range(1, N_COMMANDES + 1):
        total = 0.0

        # Une commande contient entre 1 et 5 articles
        for numero_ligne in range(1, random.randint(1, 5) + 1):
            article_id = random.randint(1, N_ARTICLES)
            quantite = random.randint(1, 20)

            # Récupération du vrai prix de l'article via le catalogue généré précédemment
            pu = prix_articles[article_id]
            remise = random.choice([0, 0, 0, 0, 5, 10, 15])
            total += quantite * pu * (1 - remise / 100)
            tampon.append((commande_id, article_id, numero_ligne,
                           quantite, pu, remise))

        # Mémorisation du total de la commande pour la future facture
        totaux[commande_id] = round(total, 2)

        # libération du buffer avec exécution de la requête toutes les 20 000 lignes.
        if len(tampon) >= 20_000: 
            execute_values(cur, sql, tampon, page_size=BATCH)
            inserees += len(tampon)
            tampon = []

    # Exécution des lignes restantes
    if tampon:
        execute_values(cur, sql, tampon, page_size=BATCH)
        inserees += len(tampon)

    return totaux, inserees # Renvoie l'ensemble des totaux et le nombre de lignes inserees



def inserer_factures(cur, infos_commandes, totaux):
    """Génère les factures uniquement pour les commandes expédiées ou livrées."""
    lignes, numero = [], 0

    # Règle métier : On ne facture pas ce qui est annulé ou en brouillon.
    for commande_id, (date_cmd, statut) in infos_commandes.items():
        if statut not in ("expediee", "livree"):
            continue

        numero += 1

        # Fixe une date entre 1 et 30 jours après la date de commande on s'assurant de ne pas dépasser la date de fin globale.
        date_fact = min(date_cmd + timedelta(days=random.randint(1,30)), DATE_FIN)

        lignes.append((
            f"FAC{numero:08d}",
            commande_id,
            date_fact,
            totaux[commande_id], # Récupération du montant exact calculé à l'étape précédente.
            random.choices(STATUTS_PAIEMENT, weights=[20, 70, 10])[0],
        ))

    execute_values(
        cur,
        """INSERT INTO factures
            (numero_facture, commande_id, date_facture, montant_ht, statut_paiement)
            VALUES %s""",
        lignes, page_size=BATCH,
    )
    return len(lignes)

# ===========================================================================
# 5. TRAITEMENT PRINCIPAL
# ===========================================================================

def main():
    """Orchestre l'ordre d'exécution et affiche les statistiques de fin."""
    conn = connexion()
    try:
        
        # Assurance que le curseur soit proprement fermé même en cas d'erreur
        with conn.cursor() as cur:
            vider(cur)
            n_clients = inserer_clients(cur)
            print(f"clients             : {n_clients:>7,}")
            prix = inserer_articles(cur)
            print(f"articles            : {len(prix):>7,}")
            infos = inserer_commandes(cur)
            print(f"commandes           : {len(infos):>7,}")
            totaux, n_lignes = inserer_lignes(cur, prix)
            print(f"lignes_commande     : {n_lignes:>7,}")
            n_factures = inserer_factures(cur, infos, totaux)
            print(f"factures            : {n_factures:>7,}")
            
        # Validation de la transaction SQL
        conn.commit()
        
        # Calcul et affichage du total général
        total = n_clients + len(prix) + len(infos) + n_lignes + n_factures
        print(f"{'-' * 27}\ntotal               : {total:>7,} lignes")
    
    finally:
        # Clôture sécurisée de la connexion à la base
        conn.close()

# Lance la fonction main seulement si le fichier est exécuté directement
if __name__ == "__main__":
    main()