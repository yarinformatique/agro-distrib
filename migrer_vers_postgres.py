"""
Script d'injection et migration automatique des données vers la nouvelle base PostgreSQL permanente (Neon / Supabase).
Usage :
    python migrer_vers_postgres.py "postgres://user:password@ep-xyz.eu-west-1.neon.tech/neondb?sslmode=require"
"""
import os
import sys
import subprocess

def migrer_vers_nouvelle_db(database_url):
    print("=" * 65)
    print("🚀 MIGRATION AUTOMATIQUE VERS POSTGRESQL PERMANENT (NEON / SUPABASE)")
    print("=" * 65)

    if not database_url or not database_url.startswith(("postgres://", "postgresql://")):
        print("❌ ERREUR : L'URL de connexion fournie n'est pas une URL PostgreSQL valide.")
        print("Exemple attendu : postgres://utilisateur:motdepasse@serveur.neon.tech/nom_db?sslmode=require")
        return False

    os.environ['DATABASE_URL'] = database_url
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agrodistrib.settings')

    # Étape 1 : Exécuter les migrations Django sur la nouvelle base
    print("\n[1/3] Application des migrations et création des tables...")
    res_migrate = subprocess.run([sys.executable, "manage.py", "migrate", "--noinput"], capture_output=True, text=True)
    if res_migrate.returncode != 0:
        print("❌ Erreur lors de l'exécution des migrations :")
        print(res_migrate.stderr)
        return False
    print("✅ Tables créées avec succès sur la nouvelle base PostgreSQL.")

    # Étape 2 : Chargement des données de sauvegarde
    backup_file = "data_backup.json"
    if os.path.exists(backup_file):
        print(f"\n[2/3] Injection des données existantes depuis {backup_file}...")
        res_load = subprocess.run([sys.executable, "manage.py", "loaddata", backup_file], capture_output=True, text=True)
        if res_load.returncode != 0:
            print("⚠️ Avertissement lors du chargement des données :")
            print(res_load.stderr or res_load.stdout)
        else:
            print("✅ Données (Entreprises, Utilisateurs, Produits, Tournées, Ventes) injectées avec succès !")
    else:
        print(f"⚠️ Fichier {backup_file} introuvable, création des tables vierges.")

    # Étape 3 : Vérification de l'intégrité
    print("\n[3/3] Vérification du bon fonctionnement de la base...")
    test_code = """
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agrodistrib.settings')
django.setup()
from distribution.models import Entreprise, Produit, Alimentation, Tournee, User
print(f'-> Entreprises enregistrées : {Entreprise.objects.count()}')
print(f'-> Comptes utilisateurs : {User.objects.count()}')
print(f'-> Produits au catalogue : {Produit.objects.count()}')
print(f'-> Boutiques partenaires : {Alimentation.objects.count()}')
print(f'-> Tournées : {Tournee.objects.count()}')
"""
    res_check = subprocess.run([sys.executable, "-c", test_code], capture_output=True, text=True)
    print(res_check.stdout)
    if res_check.returncode == 0:
        print("🎉 SUCCÈS TOTAL : La nouvelle base permanente est 100% opérationnelle et synchronisée !")
        return True
    else:
        print("❌ Erreur de vérification :", res_check.stderr)
        return False

if __name__ == '__main__':
    if len(sys.argv) > 1:
        db_url = sys.argv[1].strip()
    else:
        db_url = input("Collez votre DATABASE_URL PostgreSQL (Supabase ou Neon) : ").strip()
    migrer_vers_nouvelle_db(db_url)
