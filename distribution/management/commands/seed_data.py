from datetime import timedelta
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from distribution.models import (
    Entreprise, SocieteLivraison, ProfilUtilisateur,
    Produit, Alimentation, Tournee, LigneDotationStock,
    LivraisonVente, LigneLivraisonVente, Expedition, LigneExpedition, OrdreMission
)


class Command(BaseCommand):
    help = "Peuple la base de données avec architecture Multi-Tenant : Superadmin, Promotrice Démo, Livreur Démo, Entreprise Suspendue"

    def handle(self, *args, **options):
        self.stdout.write("Initialisation de l'architecture Multi-Tenant SaaS Agro-Distrib...")

        # ======================================================================
        # 1. SUPERADMIN GLOBAL DE LA PLATEFORME (superadmin / admin123)
        # ======================================================================
        superadmin_user, _ = User.objects.get_or_create(
            username="superadmin",
            defaults={
                "email": "superadmin@agrodistrib.com",
                "first_name": "Propriétaire",
                "last_name": "Plateforme",
                "is_staff": True,
                "is_superuser": True
            }
        )
        superadmin_user.set_password("admin123")
        superadmin_user.is_staff = True
        superadmin_user.is_superuser = True
        superadmin_user.save()

        ProfilUtilisateur.objects.update_or_create(
            user=superadmin_user,
            defaults={
                "role": "SUPERADMIN",
                "telephone": "+226 70 00 00 01",
                "adresse": "Siège SaaS Central"
            }
        )
        self.stdout.write(self.style.SUCCESS("[OK] Superadmin créé : superadmin / admin123"))

        # ======================================================================
        # 2. TENANT ACTIF : AGRO-DISTRIB FASO
        # ======================================================================
        tenant_actif, _ = Entreprise.objects.get_or_create(
            slug="agro-distrib-faso",
            defaults={
                "nom": "Agro-Distrib Faso",
                "statut_abonnement": "actif",
                "expire_le": timezone.localdate() + timedelta(days=365),
                "contact_nom": "Aïcha Ouédraogo",
                "contact_email": "demo@agrodistrib.bf",
                "contact_telephone": "+226 70 12 34 56",
                "ville": "Ouagadougou",
                "adresse": "Zone Industrielle de Gounghin",
                "actif": True
            }
        )
        tenant_actif.statut_abonnement = 'actif'
        tenant_actif.actif = True
        tenant_actif.save()

        # Société de livraison liée
        societe_livraison, _ = SocieteLivraison.objects.get_or_create(
            entreprise=tenant_actif,
            nom="Express Faso Livraisons",
            defaults={
                "telephone": "+226 78 11 22 33",
                "responsable": "Moussa Sawadogo",
                "ville": "Ouagadougou",
                "actif": True
            }
        )

        # Compte Promotrice Démo (demo / 123)
        promotrice_user, _ = User.objects.get_or_create(
            username="demo",
            defaults={
                "email": "demo@agrodistrib.bf",
                "first_name": "Aïcha",
                "last_name": "Ouédraogo",
                "is_staff": True,
                "is_superuser": False
            }
        )
        promotrice_user.set_password("123")
        promotrice_user.is_staff = True
        promotrice_user.save()

        ProfilUtilisateur.objects.update_or_create(
            user=promotrice_user,
            defaults={
                "entreprise": tenant_actif,
                "role": "PROMOTRICE",
                "telephone": "+226 70 12 34 56"
            }
        )
        self.stdout.write(self.style.SUCCESS("[OK] Promotrice Démo créée : demo / 123 (Entreprise: Agro-Distrib Faso)"))

        # Compte Livreur Démo (livreur_demo / 123)
        livreur_user, _ = User.objects.get_or_create(
            username="livreur_demo",
            defaults={
                "email": "livreur@agrodistrib.bf",
                "first_name": "Moussa",
                "last_name": "Sawadogo",
                "is_staff": False
            }
        )
        livreur_user.set_password("123")
        livreur_user.save()

        ProfilUtilisateur.objects.update_or_create(
            user=livreur_user,
            defaults={
                "entreprise": tenant_actif,
                "role": "LIVREUR",
                "societe_livraison": societe_livraison,
                "telephone": "+226 76 99 88 77"
            }
        )
        self.stdout.write(self.style.SUCCESS("[OK] Livreur Démo créé : livreur_demo / 123 (Entreprise: Agro-Distrib Faso)"))

        # Boutique Wend-Kuni avec compte utilisateur
        boutique_user, _ = User.objects.get_or_create(
            username="boutique_wendkuni",
            defaults={
                "email": "wendkuni@boutique.bf",
                "first_name": "Fatouma",
                "last_name": "Guira",
                "is_staff": False
            }
        )
        boutique_user.set_password("123")
        boutique_user.save()

        ProfilUtilisateur.objects.update_or_create(
            user=boutique_user,
            defaults={
                "entreprise": tenant_actif,
                "role": "BOUTIQUE",
                "telephone": "+226 76 98 76 54"
            }
        )

        # Produits bien approvisionnés pour Agro-Distrib Faso (au moins 3 bien distincts)
        produits_data = [
            ("Mangues séchées Bio du Burkina (100g)", "sachet", 1000, 200),
            ("Miel pur de savane du Gourma (500g)", "pot", 2500, 120),
            ("Huile pure de Sésame pressée à froid (1L)", "bouteille", 3000, 80),
            ("Anacarde grillé salé Premium (150g)", "sachet", 1500, 150),
            ("Soumbala moulu pur luxe (200g)", "pot", 1200, 100),
        ]

        produits_obj = {}
        for des, uni, px, stk in produits_data:
            p, _ = Produit.objects.update_or_create(
                entreprise=tenant_actif,
                designation=des,
                defaults={
                    "unite": uni,
                    "prix_unitaire_defaut": Decimal(px),
                    "stock_entrepot": stk
                }
            )
            produits_obj[des] = p

        self.stdout.write(self.style.SUCCESS(f"[OK] {len(produits_obj)} Produits créés pour Agro-Distrib Faso."))

        # Alimentations partenaires pour Agro-Distrib Faso
        alimentations_data = [
            ("Superette Wend-Kuni", "Koulouba (Centre)", "Fatouma Guira", "+226 76 98 76 54", 12.368500, -1.527500, 45000, "Paye cash à la livraison. Demande toujours reçu.", "1234", boutique_user),
            ("Alimentation La Grâce", "Ouaga 2000", "Salif Kaboré", "+226 70 12 34 56", 12.311500, -1.492500, 25000, "Préfère Orange Money. Réassort régulier.", "1234", None),
            ("Alimentation Barka", "Gounghin", "Ousmane Diallo", "+226 78 55 44 33", 12.355000, -1.554000, 30000, "Paye sous 7 jours par Moov Money.", "1234", None),
            ("Boutique Étoile du Sahel", "Dassasgho", "Mariam Zongo", "+226 65 22 11 00", 12.378000, -1.482000, 20000, "Règlement en espèces ou Orange Money.", "1234", None),
            ("Alimentation Moderne du Nord", "Tampouy", "Boukary Sanfo", "+226 71 33 22 11", 12.405000, -1.552000, 35000, "Accepte acompte 50%.", "1234", None),
        ]

        boutiques_obj = []
        for nom, quartier, gerant, tel, lat, lon, panier, consignes, pin, u_acc in alimentations_data:
            b, _ = Alimentation.objects.update_or_create(
                entreprise=tenant_actif,
                nom=nom,
                defaults={
                    "quartier": quartier,
                    "nom_gerant": gerant,
                    "telephone_gerant": tel,
                    "latitude": Decimal(str(lat)),
                    "longitude": Decimal(str(lon)),
                    "panier_moyen_estime": Decimal(panier),
                    "consignes_reglement": consignes,
                    "code_pin": pin,
                    "user": u_acc,
                    "actif": True
                }
            )
            boutiques_obj.append(b)

        self.stdout.write(self.style.SUCCESS(f"[OK] {len(boutiques_obj)} Alimentations créées pour Agro-Distrib Faso."))

        # Tournée active du jour avec dotation pour TOUS les produits
        aujourdhui = timezone.localdate()
        tournee, _ = Tournee.objects.get_or_create(
            entreprise=tenant_actif,
            livreur=livreur_user,
            date_tournee=aujourdhui,
            defaults={
                "statut": "EN_COURS",
                "caisse_theorique": Decimal(0),
                "caisse_declaree": Decimal(0)
            }
        )

        for p_nom, p_obj in produits_obj.items():
            LigneDotationStock.objects.update_or_create(
                tournee=tournee,
                produit=p_obj,
                defaults={
                    "quantite_depart": 20,
                    "quantite_retour": 0
                }
            )

        # Ordre de mission pour la tournée
        OrdreMission.objects.get_or_create(
            entreprise=tenant_actif,
            tournee=tournee,
            alimentation=boutiques_obj[0],
            defaults={
                "produits_consignes": "10 sachets mangue 100g, 5 pots miel savane",
                "montant_cible": Decimal("22500"),
                "consigne_particuliere": "Remettre le reçu avec signature du gérant",
                "statut": "A_FAIRE"
            }
        )

        # Expédition Inter-Villes (Bobo -> Ouaga)
        expedition, _ = Expedition.objects.get_or_create(
            entreprise=tenant_actif,
            numero_bordereau="EXP-BOBO-OUAGA-001",
            defaults={
                "ville_depart": "Bobo-Dioulasso",
                "ville_destination": "Ouagadougou",
                "transporteur_nom": "TSR Express Cargo",
                "transporteur_telephone": "+226 70 88 99 00",
                "destinataire_nom": "Moussa Sawadogo",
                "destinataire_telephone": "+226 76 99 88 77",
                "statut": "EN_TRANSIT",
                "frais_transport": Decimal("15000"),
                "consignes_generales": "Marchandise fraîche à ventiler dès réception au dépôt de Gounghin",
                "cree_par": promotrice_user
            }
        )

        for p_obj in list(produits_obj.values())[:3]:
            LigneExpedition.objects.get_or_create(
                expedition=expedition,
                produit=p_obj,
                defaults={
                    "quantite": 50,
                    "unite": p_obj.unite,
                    "valeur_unitaire": p_obj.prix_unitaire_defaut,
                    "sous_total": Decimal(50) * p_obj.prix_unitaire_defaut,
                    "consigne_specifique": "Lot vérifié et scellé"
                }
            )

        # ======================================================================
        # 3. TENANT SUSPENDU : BIO SAHEL DISTRIBUTION (POUR TESTER L'ISOLATION ET LA SUSPENSION)
        # ======================================================================
        tenant_suspendu, _ = Entreprise.objects.get_or_create(
            slug="bio-sahel",
            defaults={
                "nom": "Bio Sahel Distribution",
                "statut_abonnement": "suspendu",
                "expire_le": timezone.localdate() - timedelta(days=10),
                "contact_nom": "Salif Traoré",
                "contact_email": "suspendu@biosahel.bf",
                "contact_telephone": "+226 71 22 33 44",
                "ville": "Bobo-Dioulasso",
                "adresse": "Secteur 22, Bobo",
                "actif": False
            }
        )
        tenant_suspendu.statut_abonnement = 'suspendu'
        tenant_suspendu.actif = False
        tenant_suspendu.save()

        # Promotrice de l'entreprise suspendue (suspendu_demo / 123)
        promotrice_suspendue, _ = User.objects.get_or_create(
            username="suspendu_demo",
            defaults={
                "email": "suspendu@biosahel.bf",
                "first_name": "Salif",
                "last_name": "Traoré",
                "is_staff": True
            }
        )
        promotrice_suspendue.set_password("123")
        promotrice_suspendue.save()

        ProfilUtilisateur.objects.update_or_create(
            user=promotrice_suspendue,
            defaults={
                "entreprise": tenant_suspendu,
                "role": "PROMOTRICE",
                "telephone": "+226 71 22 33 44"
            }
        )

        # Livreur de l'entreprise suspendue (livreur_suspendu / 123)
        livreur_suspendu, _ = User.objects.get_or_create(
            username="livreur_suspendu",
            defaults={
                "email": "livreur_suspendu@biosahel.bf",
                "first_name": "Alassane",
                "last_name": "Sanou",
                "is_staff": False
            }
        )
        livreur_suspendu.set_password("123")
        livreur_suspendu.save()

        ProfilUtilisateur.objects.update_or_create(
            user=livreur_suspendu,
            defaults={
                "entreprise": tenant_suspendu,
                "role": "LIVREUR",
                "telephone": "+226 72 33 44 55"
            }
        )

        # Produit isolé pour Bio Sahel
        Produit.objects.update_or_create(
            entreprise=tenant_suspendu,
            designation="Beurre de Karité Bio Brut (250g)",
            defaults={
                "unite": "pot",
                "prix_unitaire_defaut": Decimal("1500"),
                "stock_entrepot": 100
            }
        )

        self.stdout.write(self.style.SUCCESS("[OK] Entreprise Suspendue créée : Bio Sahel Distribution (suspendu_demo / 123)"))

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("RÉSUMÉ DES COMPTES SEEDER PRÊTS :"))
        self.stdout.write("1. SUPERADMIN GLOBAL :")
        self.stdout.write("   - Accès : /superadmin/")
        self.stdout.write("   - Identifiant : superadmin | Mot de passe : admin123")
        self.stdout.write("2. PROMOTRICE ACTIVE (Agro-Distrib Faso) :")
        self.stdout.write("   - Accès : /dashboard/")
        self.stdout.write("   - Identifiant : demo | Mot de passe : 123")
        self.stdout.write("3. LIVREUR ACTIF (Agro-Distrib Faso) :")
        self.stdout.write("   - Accès : /livreur/")
        self.stdout.write("   - Identifiant : livreur_demo | Mot de passe : 123")
        self.stdout.write("4. ENTREPRISE SUSPENDUE (Bio Sahel Distribution) :")
        self.stdout.write("   - Identifiant : suspendu_demo | Mot de passe : 123")
        self.stdout.write("   - Comportement : Bloqué immédiatement avec 'Accès suspendu'")
        self.stdout.write("=" * 60)
