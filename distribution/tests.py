from decimal import Decimal
from datetime import timedelta
import json

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone

from .models import (
    Entreprise, SocieteLivraison, ProfilUtilisateur,
    Produit, Alimentation, Tournee, LigneDotationStock,
    LivraisonVente, LigneLivraisonVente,
    Expedition, LigneExpedition, OrdreMission, DeclarationPaiementBoutique
)
from .utils import haversine_distance_km, get_alimentations_triees_par_distance, get_dashboard_kpis


class MultiTenantAgroDistribTestCase(TestCase):
    def setUp(self):
        self.client = Client()

        # 1. Superadmin global
        self.superadmin = User.objects.create_superuser(
            username="superadmin", password="admin123", email="superadmin@agrodistrib.com"
        )
        ProfilUtilisateur.objects.create(
            user=self.superadmin,
            role="SUPERADMIN"
        )

        # 2. Tenant A (Actif : Agro-Distrib Faso)
        self.tenant_a = Entreprise.objects.create(
            nom="Agro-Distrib Faso",
            slug="agro-distrib-faso",
            statut_abonnement="actif",
            actif=True,
            ville="Ouagadougou"
        )
        self.promotrice_a = User.objects.create_user(
            username="demo", password="123", email="demo@agrodistrib.bf", is_staff=True
        )
        ProfilUtilisateur.objects.create(
            user=self.promotrice_a,
            entreprise=self.tenant_a,
            role="PROMOTRICE"
        )
        self.livreur_a = User.objects.create_user(
            username="livreur_demo", password="123", email="livreur@agrodistrib.bf"
        )
        ProfilUtilisateur.objects.create(
            user=self.livreur_a,
            entreprise=self.tenant_a,
            role="LIVREUR"
        )

        # 3 Produits pour Tenant A
        self.p_miel = Produit.objects.create(
            entreprise=self.tenant_a,
            designation="Miel pur de savane (500g)",
            unite="pot",
            prix_unitaire_defaut=Decimal("2500"),
            stock_entrepot=50
        )
        self.p_mangue = Produit.objects.create(
            entreprise=self.tenant_a,
            designation="Mangues séchées Bio (100g)",
            unite="sachet",
            prix_unitaire_defaut=Decimal("1000"),
            stock_entrepot=100
        )
        self.p_sesame = Produit.objects.create(
            entreprise=self.tenant_a,
            designation="Huile de Sésame (1L)",
            unite="bouteille",
            prix_unitaire_defaut=Decimal("3000"),
            stock_entrepot=40
        )

        # Alimentations pour Tenant A
        self.alim_koulouba = Alimentation.objects.create(
            entreprise=self.tenant_a,
            nom="Wend-Kuni",
            quartier="Koulouba",
            nom_gerant="Fatouma Guira",
            telephone_gerant="+226 76 98 76 54",
            latitude=Decimal("12.368500"),
            longitude=Decimal("-1.527500"),
            panier_moyen_estime=Decimal("30000"),
            code_pin="1234",
            actif=True
        )
        self.alim_ouaga2000 = Alimentation.objects.create(
            entreprise=self.tenant_a,
            nom="La Grâce",
            quartier="Ouaga 2000",
            nom_gerant="Salif Kaboré",
            telephone_gerant="+226 70 12 34 56",
            latitude=Decimal("12.311500"),
            longitude=Decimal("-1.492500"),
            panier_moyen_estime=Decimal("25000"),
            code_pin="1234",
            actif=True
        )

        # 3. Tenant B (Secondaire Suspendu : Bio Sahel Distribution)
        self.tenant_b = Entreprise.objects.create(
            nom="Bio Sahel Distribution",
            slug="bio-sahel",
            statut_abonnement="suspendu",
            actif=False,
            ville="Bobo-Dioulasso"
        )
        self.promotrice_b = User.objects.create_user(
            username="suspendu_demo", password="123", email="suspendu@biosahel.bf", is_staff=True
        )
        ProfilUtilisateur.objects.create(
            user=self.promotrice_b,
            entreprise=self.tenant_b,
            role="PROMOTRICE"
        )
        self.livreur_b = User.objects.create_user(
            username="livreur_suspendu", password="123", email="livreur_suspendu@biosahel.bf"
        )
        ProfilUtilisateur.objects.create(
            user=self.livreur_b,
            entreprise=self.tenant_b,
            role="LIVREUR"
        )
        self.p_karite = Produit.objects.create(
            entreprise=self.tenant_b,
            designation="Beurre de Karité Bio Brut (250g)",
            unite="pot",
            prix_unitaire_defaut=Decimal("1500"),
            stock_entrepot=80
        )
        self.alim_bobo = Alimentation.objects.create(
            entreprise=self.tenant_b,
            nom="Superette du Houet",
            quartier="Accart-Ville",
            nom_gerant="Seydou Sanou",
            telephone_gerant="+226 71 00 00 00",
            latitude=Decimal("11.178500"),
            longitude=Decimal("-4.296500"),
            panier_moyen_estime=Decimal("35000"),
            code_pin="1234",
            actif=True
        )

    # --------------------------------------------------------------------------
    # TESTS D'ISOLATION STRICTE MULTI-TENANT
    # --------------------------------------------------------------------------
    def test_isolation_donnees_entre_tenants(self):
        """Une promotrice A ne peut en aucun cas voir les produits ni boutiques du tenant B."""
        self.client.login(username="demo", password="123")

        # Catalogue produits
        res_prods = self.client.get("/produits/")
        self.assertEqual(res_prods.status_code, 200)
        self.assertContains(res_prods, "Miel pur de savane")
        self.assertContains(res_prods, "Mangues séchées Bio")
        self.assertNotContains(res_prods, "Beurre de Karité Bio Brut")

        # Alimentations
        res_alims = self.client.get("/alimentations/")
        self.assertEqual(res_alims.status_code, 200)
        self.assertContains(res_alims, "Wend-Kuni")
        self.assertNotContains(res_alims, "Superette du Houet")

    # --------------------------------------------------------------------------
    # TESTS DE LA RÈGLE STRICTE DE SUSPENSION EN CASCADE
    # --------------------------------------------------------------------------
    def test_suspension_en_cascade_bloque_web_et_api(self):
        """
        Si l'entreprise est suspendue :
        - Bloque les requêtes web avec HTTP 403 et message officiel
        - Bloque les requêtes API avec HTTP 403 et JSON {'suspended': True}
        - L'entreprise active continue de fonctionner sans interruption
        """
        # Test 1 : Livreur d'une entreprise suspendue sur l'application web
        self.client.login(username="livreur_suspendu", password="123")
        res_web = self.client.get("/livreur/")
        self.assertEqual(res_web.status_code, 403)
        self.assertContains(res_web, "Accès suspendu : L'abonnement de votre entreprise est inactif. Veuillez contacter l'administrateur.", status_code=403)

        # Test 2 : Requête API depuis une entreprise suspendue
        res_api = self.client.post(
            "/api/ventes/creer/",
            data=json.dumps({"test": "data"}),
            content_type="application/json"
        )
        self.assertEqual(res_api.status_code, 403)
        data = res_api.json()
        self.assertTrue(data.get('suspended'))
        self.assertIn("Accès suspendu : L'abonnement de votre entreprise est inactif", data.get('error'))

        self.client.logout()

        # Test 3 : L'entreprise active fonctionne normalement
        self.client.login(username="livreur_demo", password="123")
        res_active = self.client.get("/livreur/")
        self.assertEqual(res_active.status_code, 200)

    # --------------------------------------------------------------------------
    # TESTS SUPERADMIN GLOBAL (/superadmin/)
    # --------------------------------------------------------------------------
    def test_superadmin_dashboard_et_activation_toggle(self):
        """Le Superadmin a accès exclusif au tableau de bord /superadmin et peut activer/suspendre les tenants."""
        # Utilisateur normal rejeté
        self.client.login(username="demo", password="123")
        res_unauthorized = self.client.get("/superadmin/")
        self.assertNotEqual(res_unauthorized.status_code, 200)
        self.client.logout()

        # Superadmin autorisé
        self.client.login(username="superadmin", password="admin123")
        res_admin = self.client.get("/superadmin/")
        self.assertEqual(res_admin.status_code, 200)
        self.assertContains(res_admin, "Console de Supervision Multi-Tenant")
        self.assertContains(res_admin, "Agro-Distrib Faso")
        self.assertContains(res_admin, "Bio Sahel Distribution")

        # Toggle réactivation de Bio Sahel Distribution
        res_toggle = self.client.post(f"/superadmin/entreprises/{self.tenant_b.id}/toggle/")
        self.assertEqual(res_toggle.status_code, 302)
        self.tenant_b.refresh_from_db()
        self.assertEqual(self.tenant_b.statut_abonnement, 'actif')
        self.assertTrue(self.tenant_b.actif)

        self.client.logout()

        # Maintenant l'utilisateur de Bio Sahel peut accéder à son dashboard
        self.client.login(username="suspendu_demo", password="123")
        res_now_active = self.client.get("/dashboard/")
        self.assertEqual(res_now_active.status_code, 200)

    # --------------------------------------------------------------------------
    # TESTS DU FLUX LIVREUR & SYNCHRONISATION DES STOCKS
    # --------------------------------------------------------------------------
    def test_selection_dynamique_produits_livreur(self):
        """
        Le livreur doit voir TOUS les produits de son entreprise dans ses dotations,
        résolvant le bug où un seul produit apparaissait.
        """
        self.client.login(username="livreur_demo", password="123")
        res = self.client.get("/livreur/")
        self.assertEqual(res.status_code, 200)

        # Vérifier que les 3 produits sont dans dotations_json
        dotations_json = res.context['dotations_json']
        dotations = json.loads(dotations_json)
        self.assertEqual(len(dotations), 3)
        prod_designations = [d['designation'] for d in dotations]
        self.assertIn("Miel pur de savane (500g)", prod_designations)
        self.assertIn("Mangues séchées Bio (100g)", prod_designations)
        self.assertIn("Huile de Sésame (1L)", prod_designations)

    def test_cycle_vente_et_reintegration_retours_a_la_cloture(self):
        """
        Validation stricte de la synchronisation des stocks :
        1. Vente décrémente le stock disponible du livreur.
        2. Clôture de tournée réintègre physiquement les retours invendus dans le stock entrepôt de la promotrice.
        """
        tournee = Tournee.objects.create(
            entreprise=self.tenant_a,
            livreur=self.livreur_a,
            statut='EN_COURS',
            caisse_theorique=Decimal(0),
            caisse_declaree=Decimal(0)
        )
        dotation_miel = LigneDotationStock.objects.create(
            tournee=tournee,
            produit=self.p_miel,
            quantite_depart=15,
            quantite_retour=0
        )

        initial_stock_entrepot = self.p_miel.stock_entrepot

        self.client.login(username="livreur_demo", password="123")
        payload_vente = {
            "tournee_id": str(tournee.id),
            "alimentation_id": str(self.alim_koulouba.id),
            "lignes": [
                {"produit_id": str(self.p_miel.id), "quantite": 5, "prix_unitaire": 2500}
            ],
            "mode_reglement": "ESPECES",
            "statut_paiement": "PAYE",
            "montant_paye": 12500,
            "notes": "Vente test comptant"
        }
        res_vente = self.client.post(
            "/api/ventes/creer/",
            data=json.dumps(payload_vente),
            content_type="application/json"
        )
        self.assertEqual(res_vente.status_code, 200)

        dotation_miel.refresh_from_db()
        self.assertEqual(dotation_miel.quantite_vendue, 5)
        self.assertEqual(dotation_miel.stock_restant_theorique, 10)

        # Clôture avec 10 retours invendus
        payload_cloture = {
            "tournee_id": str(tournee.id),
            "caisse_declaree": 12500,
            "retours": {
                str(dotation_miel.id): 10
            }
        }
        res_cloture = self.client.post(
            "/api/tournees/cloturer/",
            data=json.dumps(payload_cloture),
            content_type="application/json"
        )
        self.assertEqual(res_cloture.status_code, 200)

        # Vérifier réintégration des 10 unités dans le stock entrepôt
        self.p_miel.refresh_from_db()
        self.assertEqual(self.p_miel.stock_entrepot, initial_stock_entrepot + 10)

        tournee.refresh_from_db()
        self.assertEqual(tournee.statut, 'CLOTUREE')
        self.assertEqual(tournee.ecart_caisse, Decimal(0))

    # --------------------------------------------------------------------------
    # TESTS DE L'INTERFACE DE CONNEXION ÉPURÉE
    # --------------------------------------------------------------------------
    def test_login_interface_nettoyee(self):
        """L'interface de connexion ne doit comporter aucun mot de passe en clair ni raccourci démo."""
        res = self.client.get("/login/")
        self.assertEqual(res.status_code, 200)
        # Ne doit contenir aucun credential de test visible
        self.assertNotContains(res, "password123")
        self.assertNotContains(res, "Comptes de Démonstration")
        self.assertNotContains(res, "👑 Promotrice (PDG)")
        self.assertNotContains(res, "🛵 Moussa (Livreur)")
        # Doit contenir les champs sobres
        self.assertContains(res, "Identifiant ou Adresse email")
        self.assertContains(res, "Mot de passe")
        self.assertContains(res, "Se connecter")

    def test_haversine_et_tri_gps(self):
        dist = haversine_distance_km(12.3685, -1.5275, 12.3115, -1.4925)
        self.assertIsNotNone(dist)
        self.assertTrue(6.0 <= dist <= 9.0)

        boutiques_triees = get_alimentations_triees_par_distance(12.3685, -1.5275, tenant=self.tenant_a)
        self.assertEqual(len(boutiques_triees), 2)
        self.assertEqual(boutiques_triees[0]['nom'], "Wend-Kuni")

    def test_expedition_intervilles_tenant(self):
        exp = Expedition.objects.create(
            entreprise=self.tenant_a,
            numero_bordereau="EXP-TEST-TENANT-001",
            ville_depart="Bobo-Dioulasso",
            ville_destination="Ouagadougou",
            transporteur_nom="TSR Transport",
            destinataire_nom="Moussa Sawadogo",
            frais_transport=Decimal("5000"),
            statut="EN_TRANSIT"
        )
        LigneExpedition.objects.create(
            expedition=exp,
            produit=self.p_miel,
            quantite=20,
            unite="pot",
            valeur_unitaire=Decimal("2500"),
            sous_total=Decimal("50000"),
            consigne_specifique="Scellé"
        )
        self.assertEqual(exp.valeur_totale_marchandise, Decimal("50000"))
        self.assertEqual(exp.nombre_articles_total, 20)

    def test_boutique_portal_et_confirmation(self):
        tournee = Tournee.objects.create(
            entreprise=self.tenant_a,
            livreur=self.livreur_a,
            statut='EN_COURS'
        )
        vente = LivraisonVente.objects.create(
            entreprise=self.tenant_a,
            tournee=tournee,
            alimentation=self.alim_koulouba,
            montant_total=Decimal("10000"),
            montant_paye=Decimal("10000"),
            statut_paiement='PAYE',
            confirme_par_boutique=False
        )
        res_login = self.client.post("/espace-boutique/connexion/", {
            "alimentation_id": str(self.alim_koulouba.id),
            "code_pin": "1234"
        })
        self.assertEqual(res_login.status_code, 302)

        res_portal = self.client.get("/espace-boutique/")
        self.assertEqual(res_portal.status_code, 200)

        res_conf = self.client.post("/espace-boutique/", {
            "action": "confirmer_reception",
            "vente_id": str(vente.id),
            "note_boutique": "Bien reçu."
        })
        self.assertEqual(res_conf.status_code, 302)
        vente.refresh_from_db()
        self.assertTrue(vente.confirme_par_boutique)

    def test_blocage_vente_credit_si_plafond_ou_retard_depasse(self):
        """Si la boutique a dépassé son plafond de crédit ou a une créance échue, la vente à crédit est bloquée."""
        self.alim_koulouba.plafond_credit = Decimal("20000")
        self.alim_koulouba.bloquer_si_plafond_depasse = True
        self.alim_koulouba.save()

        tournee = Tournee.objects.create(
            entreprise=self.tenant_a, livreur=self.livreur_a, statut='EN_COURS'
        )
        dotation = LigneDotationStock.objects.create(
            tournee=tournee, produit=self.p_miel, quantite_depart=20
        )

        # 1. Créer une première dette atteignant le plafond
        LivraisonVente.objects.create(
            entreprise=self.tenant_a,
            tournee=tournee,
            alimentation=self.alim_koulouba,
            montant_total=Decimal("20000"),
            montant_paye=Decimal("0"),
            statut_paiement='CREDIT'
        )

        self.client.login(username="livreur_demo", password="123")

        # 2. Tentative de nouvelle vente à crédit -> Bloquée (HTTP 400)
        payload_credit_bloque = {
            "tournee_id": str(tournee.id),
            "alimentation_id": str(self.alim_koulouba.id),
            "lignes": [{"produit_id": str(self.p_miel.id), "quantite": 2, "prix_unitaire": 2500}],
            "mode_reglement": "AUCUN",
            "statut_paiement": "CREDIT",
            "montant_paye": 0
        }
        res_refus = self.client.post("/api/ventes/creer/", data=json.dumps(payload_credit_bloque), content_type="application/json")
        self.assertEqual(res_refus.status_code, 400)
        self.assertIn("plafond de crédit", res_refus.json().get('error', '').lower())

        # 3. La même vente au COMPTANT (ESPECES / PAYE) -> Autorisée (HTTP 200)
        payload_comptant_autorise = {
            "tournee_id": str(tournee.id),
            "alimentation_id": str(self.alim_koulouba.id),
            "lignes": [{"produit_id": str(self.p_miel.id), "quantite": 2, "prix_unitaire": 2500}],
            "mode_reglement": "ESPECES",
            "statut_paiement": "PAYE",
            "montant_paye": 5000
        }
        res_ok = self.client.post("/api/ventes/creer/", data=json.dumps(payload_comptant_autorise), content_type="application/json")
        self.assertEqual(res_ok.status_code, 200)

    def test_creation_livreur_avec_societe_nom_libre(self):
        """La promotrice peut créer un livreur en saisissant librement le nom du transporteur."""
        self.client.login(username="demo", password="123")
        res = self.client.post("/livreurs/", {
            "action": "creer",
            "username": "livreur_nouveau",
            "password": "456",
            "first_name": "Ibrahim",
            "last_name": "Ouedraogo",
            "telephone": "+226 75 00 00 00",
            "societe_nom": "Express Bobo Logistique"
        })
        self.assertEqual(res.status_code, 302)

        user_cree = User.objects.get(username="livreur_nouveau")
        profil = user_cree.profil_utilisateur
        self.assertEqual(profil.entreprise, self.tenant_a)
        self.assertEqual(profil.role, 'LIVREUR')
        self.assertIsNotNone(profil.societe_livraison)
        self.assertEqual(profil.societe_livraison.nom, "Express Bobo Logistique")

    def test_boutique_bloquee_si_entreprise_suspendue(self):
        """Le portail boutique est immédiatement inaccessible si l'entreprise associée est suspendue."""
        res_login_suspendu = self.client.post("/espace-boutique/connexion/", {
            "alimentation_id": str(self.alim_bobo.id),
            "code_pin": "1234"
        })
        self.assertEqual(res_login_suspendu.status_code, 302)
        # Redirigé vers la page de connexion boutique avec message d'erreur
        self.assertNotIn('boutique_id', self.client.session)

    def test_anti_contradiction_mission_consignes(self):
        """La promotrice ne peut pas assigner une consigne demandant plus de stock que ce dont le livreur dispose."""
        self.client.login(username="demo", password="123")
        tournee = Tournee.objects.create(
            entreprise=self.tenant_a,
            livreur=self.livreur_a,
            statut='EN_COURS'
        )
        # Dotation : 10 pots de miel
        LigneDotationStock.objects.create(
            tournee=tournee,
            produit=self.p_miel,
            quantite_depart=10,
            quantite_retour=0
        )

        # 1. Tentative d'assigner une consigne exigeant 20 pots (alors qu'il n'en a que 10) -> Rejeté
        res_refus = self.client.post(f"/tournees/{tournee.id}/", {
            "action": "ajouter_mission",
            "alimentation_id": str(self.alim_koulouba.id),
            f"mission_qte_{self.p_miel.id}": "20",
            "consigne_particuliere": "Paiement cash"
        }, follow=True)
        self.assertEqual(res_refus.status_code, 200)
        self.assertEqual(OrdreMission.objects.filter(tournee=tournee).count(), 0)
        # Vérification message d'erreur
        messages = list(res_refus.context['messages'])
        self.assertTrue(any("Contradiction" in str(m) for m in messages))

        # 2. Consigne exigeant 5 pots (conforme au stock disponible de 10) -> Validé
        res_ok = self.client.post(f"/tournees/{tournee.id}/", {
            "action": "ajouter_mission",
            "alimentation_id": str(self.alim_koulouba.id),
            f"mission_qte_{self.p_miel.id}": "5",
            "consigne_particuliere": "Paiement cash"
        }, follow=True)
        self.assertEqual(res_ok.status_code, 200)
        mission_creee = OrdreMission.objects.filter(tournee=tournee).first()
        self.assertIsNotNone(mission_creee)
        self.assertIn("5x Miel pur", mission_creee.produits_consignes)
        self.assertEqual(mission_creee.montant_cible, Decimal("12500")) # 5 * 2500

    def test_reapprovisionnement_vehicule_en_cours_de_tournee(self):
        """Le promoteur peut réapprovisionner le véhicule d'un livreur depuis l'entrepôt pour augmenter son stock disponible."""
        self.client.login(username="demo", password="123")
        tournee = Tournee.objects.create(
            entreprise=self.tenant_a,
            livreur=self.livreur_a,
            statut='EN_COURS'
        )
        dotation = LigneDotationStock.objects.create(
            tournee=tournee,
            produit=self.p_miel,
            quantite_depart=10,
            quantite_retour=0
        )
        stock_entrepot_initial = self.p_miel.stock_entrepot # 50

        # Transfert de 15 pots supplémentaires vers le camion
        res = self.client.post(f"/tournees/{tournee.id}/", {
            "action": "reapprovisionner",
            "produit_id": str(self.p_miel.id),
            "quantite_ajout": "15"
        }, follow=True)
        self.assertEqual(res.status_code, 200)

        self.p_miel.refresh_from_db()
        dotation.refresh_from_db()

        self.assertEqual(self.p_miel.stock_entrepot, stock_entrepot_initial - 15)
        self.assertEqual(dotation.quantite_depart, 25)
        self.assertEqual(dotation.stock_restant_theorique, 25)

    def test_healthz_and_ping_zero_db_queries(self):
        """Les routes anti-mise en veille /healthz et /ping doivent répondre HTTP 200 immédiatement avec 0 requête SQL."""
        for route in ['/healthz', '/healthz/', '/ping', '/ping/']:
            with self.assertNumQueries(0):
                res = self.client.get(route)
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.content.decode(), "OK")

    def test_recensement_terrain_public_alimente_reseau_promotrice(self):
        """Un recensement fait à distance via le lien public ?tenant=slug doit alimenter immédiatement la table de la promotrice."""
        # 1. Requête anonyme (sans session connectée) sur le lien public
        self.client.logout()
        res_post = self.client.post(f"/prospection/terrain/?tenant={self.tenant_a.slug}", {
            "tenant": self.tenant_a.slug,
            "nom": "Alimentation Wend-Songda",
            "ville": "Ouagadougou",
            "quartier": "Somgandé",
            "nom_gerant": "Pauline Ouedraogo",
            "telephone_gerant": "+226 77 11 22 33",
            "latitude": "12.389000",
            "longitude": "-1.505000",
            "panier_moyen_estime": "30000",
            "consignes_reglement": "Règlement espèces",
            "code_pin": "5678",
        })
        self.assertEqual(res_post.status_code, 200)

        # Vérifier que la boutique a été créée pour tenant_a
        alim_creee = Alimentation.objects.filter(nom="Alimentation Wend-Songda").first()
        self.assertIsNotNone(alim_creee)
        self.assertEqual(alim_creee.entreprise, self.tenant_a)
        self.assertEqual(alim_creee.code_pin, "5678")

        # 2. La promotrice se connecte et doit voir cette boutique dans son réseau
        self.client.login(username="demo", password="123")
        res_alims = self.client.get("/alimentations/")
        self.assertEqual(res_alims.status_code, 200)
        self.assertContains(res_alims, "Alimentation Wend-Songda")

        res_prospection = self.client.get("/prospection/")
        self.assertEqual(res_prospection.status_code, 200)
        self.assertContains(res_prospection, "Alimentation Wend-Songda")

    def test_expedition_assignee_livreur_et_confirmation_reception_stock(self):
        """Une expédition est d'abord préparée, confirmée pour expédition, puis réceptionnée par le livreur."""
        # 1. La promotrice crée une expédition assignée au livreur (statut initial PREPARE)
        self.client.login(username="demo", password="123")
        stock_entrepot_init = self.p_mangue.stock_entrepot # 100

        res_exp = self.client.post("/expeditions/", {
            "action": "creer",
            "ville_depart": "Bobo-Dioulasso",
            "ville_destination": "Ouagadougou",
            "transporteur_nom": "TSR Express",
            "transporteur_telephone": "+226 70 99 88 77",
            "livreur_destinataire_id": str(self.livreur_a.id),
            "destinataire_nom": "Moussa Livreur",
            "destinataire_telephone": "+226 76 99 88 77",
            "frais_transport": "5000",
            "consignes_generales": "Livrer rapidement",
            f"qte_{self.p_mangue.id}": "25",
        })
        self.assertEqual(res_exp.status_code, 302)

        exp = Expedition.objects.filter(transporteur_nom="TSR Express").first()
        self.assertIsNotNone(exp)
        self.assertEqual(exp.livreur_destinataire, self.livreur_a)
        self.assertEqual(exp.statut, 'PREPARE')

        # À la préparation, le stock entrepôt n'a pas encore été débité
        self.p_mangue.refresh_from_db()
        self.assertEqual(self.p_mangue.stock_entrepot, stock_entrepot_init)

        # 2. La promotrice confirme l'envoi de l'expédition
        res_confirm = self.client.post("/expeditions/", {
            "action": "confirmer_envoi",
            "expedition_id": str(exp.id),
        })
        self.assertEqual(res_confirm.status_code, 302)
        exp.refresh_from_db()
        self.assertEqual(exp.statut, 'EN_TRANSIT')

        # Maintenant le stock entrepôt est débité
        self.p_mangue.refresh_from_db()
        self.assertEqual(self.p_mangue.stock_entrepot, stock_entrepot_init - 25)

        # 3. Le livreur se connecte et consulte son application
        self.client.login(username="livreur_demo", password="123")
        res_livreur = self.client.get("/livreur/")
        self.assertEqual(res_livreur.status_code, 200)
        self.assertContains(res_livreur, exp.numero_bordereau)
        self.assertContains(res_livreur, "TSR Express")

        # 4. Le livreur confirme la réception du colis
        res_reception = self.client.post(f"/livreur/expeditions/{exp.id}/confirmer/")
        self.assertEqual(res_reception.status_code, 302)

        exp.refresh_from_db()
        self.assertEqual(exp.statut, 'RECEPTIONNE')
        self.assertIsNotNone(exp.date_reception)

        # Vérifier que le stock embarqué du livreur a bien été augmenté de 25 unités
        tournee = Tournee.objects.filter(livreur=self.livreur_a, statut='EN_COURS').first()
        self.assertIsNotNone(tournee)
        dotation_mangue = tournee.dotations.filter(produit=self.p_mangue).first()
        self.assertIsNotNone(dotation_mangue)
        self.assertGreaterEqual(dotation_mangue.quantite_depart, 25)

    def test_modifier_et_supprimer_produits_et_boutiques(self):
        """Test des actions modifier et supprimer pour produits et boutiques."""
        self.client.login(username="demo", password="123")

        # 1. Modification d'un produit
        res_mod_p = self.client.post("/produits/", {
            "action": "modifier",
            "produit_id": str(self.p_miel.id),
            "designation": "Miel Sauvage de l'Est (500g)",
            "unite": "pot",
            "prix": "2800",
            "stock": "60",
        })
        self.assertEqual(res_mod_p.status_code, 302)
        self.p_miel.refresh_from_db()
        self.assertEqual(self.p_miel.designation, "Miel Sauvage de l'Est (500g)")
        self.assertEqual(self.p_miel.prix_unitaire_defaut, Decimal("2800"))
        self.assertEqual(self.p_miel.stock_entrepot, 60)

        # 2. Suppression d'un produit
        prod_temp = Produit.objects.create(
            entreprise=self.tenant_a,
            designation="Produit Test Suppr",
            unite="sachet",
            prix_unitaire_defaut=Decimal("500"),
            stock_entrepot=10
        )
        res_del_p = self.client.post("/produits/", {
            "action": "supprimer",
            "produit_id": str(prod_temp.id),
        })
        self.assertEqual(res_del_p.status_code, 302)
        self.assertFalse(Produit.objects.filter(id=prod_temp.id).exists())

        # 3. Modification d'une alimentation
        res_mod_a = self.client.post("/alimentations/", {
            "action": "modifier",
            "alim_id": str(self.alim_koulouba.id),
            "nom": "Wend-Kuni Plus",
            "ville": "Ouagadougou",
            "quartier": "Koulouba Centre",
            "nom_gerant": "Mme Guira",
            "telephone_gerant": "+226 76 99 99 99",
            "latitude": "12.369000",
            "longitude": "-1.528000",
            "panier_moyen_estime": "35000",
            "consignes_reglement": "Orange Money",
            "code_pin": "9999",
        })
        self.assertEqual(res_mod_a.status_code, 302)
        self.alim_koulouba.refresh_from_db()
        self.assertEqual(self.alim_koulouba.nom, "Wend-Kuni Plus")
        self.assertEqual(self.alim_koulouba.code_pin, "9999")

        # 4. Suppression d'une alimentation
        alim_temp = Alimentation.objects.create(
            entreprise=self.tenant_a,
            nom="Boutique Suppr",
            ville="Ouagadougou",
            quartier="Dassasgho",
            nom_gerant="Test",
            telephone_gerant="123",
            latitude=Decimal("12.35"),
            longitude=Decimal("-1.50")
        )
        res_del_a = self.client.post("/alimentations/", {
            "action": "supprimer",
            "alim_id": str(alim_temp.id),
        })
        self.assertEqual(res_del_a.status_code, 302)
        self.assertFalse(Alimentation.objects.filter(id=alim_temp.id).exists())

    def test_expedition_securite_stock_et_suppression_avec_restitution(self):
        """Vérifie le blocage si stock insuffisant, le verrouillage après envoi, et la restitution lors de suppression."""
        self.client.login(username="demo", password="123")
        stock_init = self.p_sesame.stock_entrepot # 40

        # Tentative d'expédition avec quantité supérieure au stock
        res_depassement = self.client.post("/expeditions/", {
            "action": "creer",
            "ville_depart": "Bobo",
            "ville_destination": "Ouaga",
            "transporteur_nom": "TSR",
            "destinataire_nom": "Relais",
            f"qte_{self.p_sesame.id}": "100", # > 40
        })
        self.assertEqual(res_depassement.status_code, 302)
        self.assertFalse(Expedition.objects.filter(transporteur_nom="TSR").exists())

        # Création conforme
        res_creer = self.client.post("/expeditions/", {
            "action": "creer",
            "ville_depart": "Bobo",
            "ville_destination": "Ouaga",
            "transporteur_nom": "TSR Valide",
            "destinataire_nom": "Relais",
            f"qte_{self.p_sesame.id}": "15",
        })
        self.assertEqual(res_creer.status_code, 302)
        exp = Expedition.objects.filter(transporteur_nom="TSR Valide").first()
        self.assertEqual(exp.statut, 'PREPARE')

        # Modification autorisée tant que PREPARE
        res_mod = self.client.post("/expeditions/", {
            "action": "modifier",
            "expedition_id": str(exp.id),
            "ville_depart": "Bobo-Dioulasso",
            "ville_destination": "Koudougou",
            "transporteur_nom": "Rakieta",
            "destinataire_nom": "Relais Koudougou",
            f"qte_{self.p_sesame.id}": "20",
        })
        self.assertEqual(res_mod.status_code, 302)
        exp.refresh_from_db()
        self.assertEqual(exp.ville_destination, "Koudougou")
        self.assertEqual(exp.lignes.first().quantite, 20)

        # Confirmer l'envoi -> déduit le stock
        res_conf = self.client.post("/expeditions/", {
            "action": "confirmer_envoi",
            "expedition_id": str(exp.id),
        })
        self.assertEqual(res_conf.status_code, 302)
        exp.refresh_from_db()
        self.assertEqual(exp.statut, 'EN_TRANSIT')
        self.p_sesame.refresh_from_db()
        self.assertEqual(self.p_sesame.stock_entrepot, stock_init - 20)

        # Modification désormais impossible
        res_mod_bloque = self.client.post("/expeditions/", {
            "action": "modifier",
            "expedition_id": str(exp.id),
            "transporteur_nom": "Autre",
        })
        self.assertEqual(res_mod_bloque.status_code, 302)

        # Suppression pendant transit -> RESTITUE le stock entrepôt
        res_suppr = self.client.post("/expeditions/", {
            "action": "supprimer",
            "expedition_id": str(exp.id),
        })
        self.assertEqual(res_suppr.status_code, 302)
        self.assertFalse(Expedition.objects.filter(id=exp.id).exists())
        self.p_sesame.refresh_from_db()
        self.assertEqual(self.p_sesame.stock_entrepot, stock_init)

    def test_tournee_interdiction_sans_stock_et_missions_multi_boutiques(self):
        """
        Vérifie la gestion dynamique du stock par livreur :
        1. Impossibilité d'allouer du stock à un livreur qui n'a reçu aucune expédition.
        2. Impossibilité de créer une tournée avec 0 stock.
        3. Alimentation dynamique du stock réel du livreur via expédition confirmée.
        4. Interdiction stricte d'allouer une quantité supérieure au stock réel du livreur.
        5. Création réussie d'une tournée dans la limite du stock réel disponible.
        6. Règles anti-contradiction multi-boutiques basées sur le stock embarqué.
        """
        self.client.login(username="demo", password="123")

        # Création d'un second livreur sans stock pour tester la dynamique par livreur
        livreur_b = User.objects.create_user(username="livreur_b_test", password="123", email="livreurb@agrodistrib.bf")
        ProfilUtilisateur.objects.create(user=livreur_b, entreprise=self.tenant_a, role="LIVREUR")

        # 1. Tentative création tournée avec 0 stock
        res_zero_stock = self.client.post("/tournees/", {
            "action": "creer",
            "livreur_id": str(self.livreur_a.id),
            f"qte_{self.p_mangue.id}": "0",
            f"qte_{self.p_miel.id}": "0",
        })
        self.assertEqual(res_zero_stock.status_code, 302)
        self.assertFalse(Tournee.objects.filter(livreur=self.livreur_a, dotations__isnull=False).exists())

        # 2. Tentative d'allouer du stock à un livreur sans expédition reçue (stock réel = 0)
        res_sans_expedition = self.client.post("/tournees/", {
            "action": "creer",
            "livreur_id": str(self.livreur_a.id),
            f"qte_{self.p_miel.id}": "10",
        })
        self.assertEqual(res_sans_expedition.status_code, 302)
        self.assertFalse(Tournee.objects.filter(livreur=self.livreur_a).exists())

        # 3. La promotrice prépare et confirme une expédition de 20 miels pour le livreur A
        stock_miel_init = self.p_miel.stock_entrepot  # 50
        exp = Expedition.objects.create(
            entreprise=self.tenant_a,
            numero_bordereau="EXP-TEST-STOCK-DYN-01",
            ville_depart="Bobo-Dioulasso",
            ville_destination="Ouagadougou",
            transporteur_nom="TSR Express Dyn",
            livreur_destinataire=self.livreur_a,
            destinataire_nom="Livreur Demo",
            statut='PREPARE',
            cree_par=self.promotrice_a
        )
        LigneExpedition.objects.create(
            expedition=exp,
            produit=self.p_miel,
            quantite=20,
            unite=self.p_miel.unite,
            valeur_unitaire=self.p_miel.prix_unitaire_defaut,
            sous_total=20 * self.p_miel.prix_unitaire_defaut
        )
        # Confirmation de l'envoi -> déduit le stock entrepôt (50 - 20 = 30)
        res_conf = self.client.post("/expeditions/", {
            "action": "confirmer_envoi",
            "expedition_id": str(exp.id),
        })
        self.assertEqual(res_conf.status_code, 302)
        self.p_miel.refresh_from_db()
        self.assertEqual(self.p_miel.stock_entrepot, stock_miel_init - 20)

        # 4. Le livreur B n'a toujours rien reçu -> allocation bloquée
        res_bloque_b = self.client.post("/tournees/", {
            "action": "creer",
            "livreur_id": str(livreur_b.id),
            f"qte_{self.p_miel.id}": "5",
        })
        self.assertEqual(res_bloque_b.status_code, 302)
        self.assertFalse(Tournee.objects.filter(livreur=livreur_b).exists())

        # 5. Le livreur A a 20 miels : tentative d'allouer 25 (> 20) -> bloqué par la sécurité
        res_depassement = self.client.post("/tournees/", {
            "action": "creer",
            "livreur_id": str(self.livreur_a.id),
            f"qte_{self.p_miel.id}": "25",
        })
        self.assertEqual(res_depassement.status_code, 302)
        self.assertFalse(Tournee.objects.filter(livreur=self.livreur_a).exists())

        # 6. Allocation valide pour livreur A : 10 miels (<= 20 disponible)
        res_tournee = self.client.post("/tournees/", {
            "action": "creer",
            "livreur_id": str(self.livreur_a.id),
            f"qte_{self.p_miel.id}": "10",
        })
        self.assertEqual(res_tournee.status_code, 302)
        tournee = Tournee.objects.filter(livreur=self.livreur_a, statut='EN_COURS').first()
        self.assertIsNotNone(tournee)
        dotation = tournee.dotations.filter(produit=self.p_miel).first()
        self.assertEqual(dotation.quantite_depart, 10)
        # Le stock entrepôt reste intact car déjà débité lors de l'expédition
        self.p_miel.refresh_from_db()
        self.assertEqual(self.p_miel.stock_entrepot, stock_miel_init - 20)

        # 7. Assignation multi-boutiques avec anti-contradiction
        # Le van a 10 miels. Si on assigne 6 miels à 2 boutiques = 12 > 10 -> Contradiction bloquée !
        res_contradiction = self.client.post(f"/tournees/{tournee.id}/", {
            "action": "ajouter_mission",
            "alimentation_ids": [str(self.alim_koulouba.id), str(self.alim_ouaga2000.id)],
            f"mission_qte_{self.p_miel.id}": "6",
        })
        self.assertEqual(res_contradiction.status_code, 302)
        self.assertEqual(tournee.missions.count(), 0)

        # Assignation multi-boutiques valide : 4 miels x 2 boutiques = 8 <= 10
        res_mission_ok = self.client.post(f"/tournees/{tournee.id}/", {
            "action": "ajouter_mission",
            "alimentation_ids": [str(self.alim_koulouba.id), str(self.alim_ouaga2000.id)],
            f"mission_qte_{self.p_miel.id}": "4",
            "consigne_particuliere": "Consigne multi-test",
        })
        self.assertEqual(res_mission_ok.status_code, 302)
        self.assertEqual(tournee.missions.count(), 2)

        # Suppression d'une consigne de mission
        m1 = tournee.missions.first()
        res_del_m = self.client.post(f"/tournees/{tournee.id}/", {
            "action": "supprimer_mission",
            "mission_id": str(m1.id),
        })
        self.assertEqual(res_del_m.status_code, 302)
        self.assertEqual(tournee.missions.count(), 1)





