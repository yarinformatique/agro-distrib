import uuid
from decimal import Decimal
from django.db import models
from django.contrib.auth.models import User
from django.db.models import Sum


# ==============================================================================
# ARCHITECTURE MULTI-TENANT SAAS : ENTREPRISE & PROFILS UTILISATEURS
# ==============================================================================

class Entreprise(models.Model):
    """
    Tenant SaaS représentant une Entreprise / Marque agroalimentaire (ex: Agro-Distrib Faso).
    Isolation stricte des données et gestion du cycle de vie de l'abonnement.
    """
    STATUT_ABONNEMENT_CHOICES = [
        ('actif', 'Actif'),
        ('suspendu', 'Suspendu'),
        ('inactif', 'Inactif'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nom = models.CharField(max_length=200, help_text="Nom commercial de l'entreprise")
    slug = models.SlugField(max_length=200, unique=True, help_text="Identifiant unique d'URL")
    statut_abonnement = models.CharField(max_length=20, choices=STATUT_ABONNEMENT_CHOICES, default='actif')
    expire_le = models.DateField(null=True, blank=True, help_text="Date d'expiration de l'abonnement")
    date_creation = models.DateTimeField(auto_now_add=True)

    # Coordonnées & Responsable
    contact_nom = models.CharField(max_length=150, blank=True, help_text="Nom de la Promotrice / PDG")
    contact_email = models.EmailField(blank=True)
    contact_telephone = models.CharField(max_length=50, blank=True)
    ville = models.CharField(max_length=100, default="Ouagadougou")
    adresse = models.CharField(max_length=255, blank=True)
    devise = models.CharField(max_length=20, default="FCFA")
    actif = models.BooleanField(default=True)

    # Configuration Paiements Digitaux & CinetPay / Mobile Money
    lien_paiement_cinetpay = models.URLField(max_length=500, blank=True, help_text="Lien de paiement CinetPay / Guichet Mobile Money")
    numero_orange_money = models.CharField(max_length=50, blank=True, help_text="Numéro Marchand Orange Money")
    numero_moov_money = models.CharField(max_length=50, blank=True, help_text="Numéro Marchand Moov Money")

    class Meta:
        ordering = ['nom']
        verbose_name = "Entreprise (Tenant)"
        verbose_name_plural = "Entreprises (Tenants)"

    def __str__(self):
        return f"{self.nom} [{self.get_statut_abonnement_display()}]"

    @property
    def est_actif(self):
        return self.statut_abonnement == 'actif' and self.actif

    @property
    def total_produits(self):
        return self.produits.count()

    @property
    def total_alimentations(self):
        return self.alimentations.count()

    @property
    def total_ventes_ca(self):
        return self.ventes.aggregate(total=Sum('montant_total'))['total'] or Decimal(0)


class SocieteLivraison(models.Model):
    """
    Société partenaire de livraison rattachée au tenant (ex: Express Faso Livraisons, TSR Relay).
    Permet de regrouper et allouer le stock aux équipes de livreurs.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entreprise = models.ForeignKey(Entreprise, on_delete=models.CASCADE, related_name="societes_livraison")
    nom = models.CharField(max_length=150)
    telephone = models.CharField(max_length=50, blank=True)
    responsable = models.CharField(max_length=150, blank=True)
    ville = models.CharField(max_length=100, default="Ouagadougou")
    actif = models.BooleanField(default=True)
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nom']
        verbose_name = "Société de Livraison"
        verbose_name_plural = "Sociétés de Livraison"

    def __str__(self):
        return f"{self.nom} ({self.entreprise.nom})"


class ProfilUtilisateur(models.Model):
    """
    Profil étendu rattaché à l'utilisateur Django pour gérer les rôles multi-tenant :
    - SUPERADMIN : Propriétaire de la plateforme globale SaaS
    - PROMOTRICE : PDG / Gérante de son entreprise
    - LIVREUR : Chauffeur van sales / relais logistique
    - BOUTIQUE : Gérant de boutique partenaire
    """
    ROLE_CHOICES = [
        ('SUPERADMIN', 'Super-Administrateur (Plateforme SaaS)'),
        ('PROMOTRICE', 'Promotrice / PDG (Tenant)'),
        ('LIVREUR', 'Livreur / Chauffeur Van Sales'),
        ('BOUTIQUE', 'Gérant Boutique / Alimentation Partenaire'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profil_utilisateur")
    entreprise = models.ForeignKey(Entreprise, on_delete=models.CASCADE, null=True, blank=True, related_name="utilisateurs")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='PROMOTRICE')
    societe_livraison = models.ForeignKey(SocieteLivraison, on_delete=models.SET_NULL, null=True, blank=True, related_name="livreurs")
    telephone = models.CharField(max_length=50, blank=True)
    adresse = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "Profil Utilisateur"
        verbose_name_plural = "Profils Utilisateurs"

    def __str__(self):
        ent = self.entreprise.nom if self.entreprise else "Sans Entreprise"
        return f"{self.user.username} ({self.role} - {ent})"

    @property
    def is_superadmin(self):
        return self.role == 'SUPERADMIN' or self.user.is_superuser

    @property
    def is_promotrice(self):
        return self.role == 'PROMOTRICE'

    @property
    def is_livreur(self):
        return self.role == 'LIVREUR'


# ==============================================================================
# MODÈLES MÉTIER ISOLÉS PAR TENANT (ENTREPRISE)
# ==============================================================================

class Produit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entreprise = models.ForeignKey(Entreprise, on_delete=models.CASCADE, null=True, blank=True, related_name="produits")
    designation = models.CharField(max_length=150)
    unite = models.CharField(max_length=50, default="sachet")  # sachet, pot, carton, kg
    prix_unitaire_defaut = models.DecimalField(max_digits=10, decimal_places=2)
    stock_entrepot = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['designation']
        verbose_name = "Produit"
        verbose_name_plural = "Produits"

    def __str__(self):
        return f"{self.designation} ({self.prix_unitaire_defaut:,.0f} FCFA / {self.unite})"


class Alimentation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entreprise = models.ForeignKey(Entreprise, on_delete=models.CASCADE, null=True, blank=True, related_name="alimentations")
    nom = models.CharField(max_length=150)
    ville = models.CharField(max_length=100, default="Ouagadougou")
    quartier = models.CharField(max_length=100)
    nom_gerant = models.CharField(max_length=150)
    telephone_gerant = models.CharField(max_length=30)
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    panier_moyen_estime = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    consignes_reglement = models.TextField(blank=True, help_text="Ex: Paye le vendredi, préfère Orange Money")
    actif = models.BooleanField(default=True)

    # Gestion des risques & Plafond d'encours de crédit
    plafond_credit = models.DecimalField(max_digits=12, decimal_places=2, default=50000, help_text="Plafond maximum de crédit autorisé pour cette boutique (FCFA)")
    bloquer_si_plafond_depasse = models.BooleanField(default=True, help_text="Bloquer les nouvelles livraisons à crédit si plafond dépassé ou échéance impayée")

    # Espace Portail Boutique (Authentification & Sécurité anti-litige)
    code_pin = models.CharField(max_length=10, default="1234", help_text="Code PIN d'accès espace boutique")
    user = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="boutique_profil")

    class Meta:
        ordering = ['quartier', 'nom']
        verbose_name = "Alimentation"
        verbose_name_plural = "Alimentations"

    def __str__(self):
        return f"{self.nom} ({self.quartier})"

    @property
    def google_maps_url(self):
        return f"https://www.google.com/maps/dir/?api=1&destination={self.latitude},{self.longitude}"

    @property
    def total_creance_en_cours(self):
        credits = self.achats.filter(statut_paiement__in=['PARTIEL', 'CREDIT'])
        total_du = sum((c.montant_total - c.montant_paye) for c in credits)
        return total_du

    @property
    def a_creance_en_retard(self):
        """Vérifie si la boutique a une facture dont la date d'échéance est échue."""
        from django.utils import timezone
        aujourdhui = timezone.localdate()
        return self.achats.filter(
            statut_paiement__in=['PARTIEL', 'CREDIT'],
            date_echeance_credit__lt=aujourdhui
        ).exists()

    @property
    def montant_creance_en_retard(self):
        """Calcule le montant total des créances en retard de paiement."""
        from django.utils import timezone
        aujourdhui = timezone.localdate()
        credits = self.achats.filter(
            statut_paiement__in=['PARTIEL', 'CREDIT'],
            date_echeance_credit__lt=aujourdhui
        )
        return sum((c.montant_total - c.montant_paye) for c in credits)

    @property
    def depasse_plafond_credit(self):
        """Vérifie si la créance en cours atteint ou dépasse le plafond accordé."""
        return self.total_creance_en_cours >= self.plafond_credit

    @property
    def credit_disponible(self):
        """Crédit restant disponible avant d'atteindre le plafond."""
        return max(Decimal(0), self.plafond_credit - self.total_creance_en_cours)


class Tournee(models.Model):
    STATUT_CHOICES = [
        ('BROUILLON', 'Brouillon'),
        ('EN_COURS', 'En cours'),
        ('CLOTUREE', 'Clôturée'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entreprise = models.ForeignKey(Entreprise, on_delete=models.CASCADE, null=True, blank=True, related_name="tournees")
    livreur = models.ForeignKey(User, on_delete=models.CASCADE, related_name="tournees")
    date_tournee = models.DateField(auto_now_add=True)
    date_creation = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='EN_COURS')
    caisse_theorique = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    caisse_declaree = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ['-date_tournee', '-date_creation']
        verbose_name = "Tournée"
        verbose_name_plural = "Tournées"

    def __str__(self):
        return f"Tournée du {self.date_tournee.strftime('%d/%m/%Y')} - {self.livreur.get_full_name() or self.livreur.username}"

    def recalculer_caisse_theorique(self):
        ventes_especes = self.ventes.filter(mode_reglement='ESPECES')
        total_especes = ventes_especes.aggregate(total=Sum('montant_paye'))['total'] or Decimal(0)
        self.caisse_theorique = total_especes
        self.save(update_fields=['caisse_theorique'])
        return total_especes

    @property
    def ecart_caisse(self):
        return self.caisse_declaree - self.caisse_theorique

    @property
    def chiffre_affaires_total(self):
        return self.ventes.aggregate(total=Sum('montant_total'))['total'] or Decimal(0)

    @property
    def total_encaisse(self):
        return self.ventes.aggregate(total=Sum('montant_paye'))['total'] or Decimal(0)

    @property
    def total_credit_accorde(self):
        return self.chiffre_affaires_total - self.total_encaisse


class LigneDotationStock(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tournee = models.ForeignKey(Tournee, on_delete=models.CASCADE, related_name="dotations")
    produit = models.ForeignKey(Produit, on_delete=models.CASCADE)
    quantite_depart = models.PositiveIntegerField()
    quantite_retour = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Dotation de Stock"
        verbose_name_plural = "Dotations de Stock"

    def __str__(self):
        return f"{self.produit.designation}: {self.quantite_depart} au départ"

    @property
    def quantite_vendue(self):
        lignes = LigneLivraisonVente.objects.filter(vente__tournee=self.tournee, produit=self.produit)
        return lignes.aggregate(total=Sum('quantite'))['total'] or 0

    @property
    def stock_restant_theorique(self):
        return max(0, self.quantite_depart - self.quantite_vendue)

    @property
    def ecart_stock(self):
        return self.quantite_retour - self.stock_restant_theorique


class LivraisonVente(models.Model):
    PAIEMENT_STATUS = [
        ('PAYE', 'Payé comptant'),
        ('PARTIEL', 'Acompte versé'),
        ('CREDIT', 'À crédit'),
    ]
    MODE_REGLEMENT = [
        ('ESPECES', 'Espèces'),
        ('ORANGE_MONEY', 'Orange Money'),
        ('MOOV_MONEY', 'Moov Money'),
        ('AUCUN', 'Aucun (Crédit total)'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entreprise = models.ForeignKey(Entreprise, on_delete=models.CASCADE, null=True, blank=True, related_name="ventes")
    tournee = models.ForeignKey(Tournee, on_delete=models.CASCADE, related_name="ventes")
    alimentation = models.ForeignKey(Alimentation, on_delete=models.CASCADE, related_name="achats")
    date_heure = models.DateTimeField(auto_now_add=True)
    montant_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    montant_paye = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    statut_paiement = models.CharField(max_length=20, choices=PAIEMENT_STATUS, default='PAYE')
    mode_reglement = models.CharField(max_length=20, choices=MODE_REGLEMENT, default='ESPECES')
    date_echeance_credit = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    # Double validation contradictoire (Boutique & Livreur)
    confirme_par_boutique = models.BooleanField(default=False)
    date_confirmation_boutique = models.DateTimeField(null=True, blank=True)
    note_boutique = models.TextField(blank=True)

    class Meta:
        ordering = ['-date_heure']
        verbose_name = "Vente / Livraison"
        verbose_name_plural = "Ventes & Livraisons"

    def __str__(self):
        return f"Vente #{str(self.id)[:8]} - {self.alimentation.nom} ({self.montant_total:,.0f} FCFA)"

    @property
    def reste_a_payer(self):
        return max(Decimal(0), self.montant_total - self.montant_paye)

    @property
    def est_solde(self):
        return self.montant_paye >= self.montant_total


class LigneLivraisonVente(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vente = models.ForeignKey(LivraisonVente, on_delete=models.CASCADE, related_name="lignes")
    produit = models.ForeignKey(Produit, on_delete=models.CASCADE)
    quantite = models.PositiveIntegerField()
    prix_unitaire = models.DecimalField(max_digits=10, decimal_places=2)
    sous_total = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = "Ligne de Vente"
        verbose_name_plural = "Lignes de Vente"

    def __str__(self):
        return f"{self.produit.designation} x {self.quantite} = {self.sous_total:,.0f} FCFA"


class ReglementCreance(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entreprise = models.ForeignKey(Entreprise, on_delete=models.CASCADE, null=True, blank=True, related_name="reglements_creance")
    vente = models.ForeignKey(LivraisonVente, on_delete=models.CASCADE, related_name="reglements_recouvrement")
    date_reglement = models.DateTimeField(auto_now_add=True)
    montant = models.DecimalField(max_digits=12, decimal_places=2)
    mode_reglement = models.CharField(max_length=20, choices=[
        ('ESPECES', 'Espèces'),
        ('ORANGE_MONEY', 'Orange Money'),
        ('MOOV_MONEY', 'Moov Money'),
    ], default='ESPECES')
    recu_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-date_reglement']
        verbose_name = "Règlement de Créance"
        verbose_name_plural = "Règlements de Créances"

    def __str__(self):
        return f"Règlement {self.montant:,.0f} FCFA pour {self.vente.alimentation.nom}"


# ==============================================================================
# EXPÉDITIONS INTER-VILLES & CONSIGNES LIVREURS
# ==============================================================================

class Expedition(models.Model):
    """
    Expéditions et transferts de marchandise inter-villes (Ex: Bobo-Dioulasso -> Ouagadougou)
    effectuées par la Promotrice / PDG vers une société ou un livreur tiers avec valeur exacte et consignes.
    """
    STATUT_CHOICES = [
        ('PREPARE', 'Préparé / En attente départ'),
        ('EN_TRANSIT', 'En cours d\'acheminement'),
        ('RECEPTIONNE', 'Réceptionné au dépôt / par le livreur'),
        ('ANNULE', 'Annulé'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entreprise = models.ForeignKey(Entreprise, on_delete=models.CASCADE, null=True, blank=True, related_name="expeditions")
    numero_bordereau = models.CharField(max_length=50, unique=True)
    date_expedition = models.DateTimeField(auto_now_add=True)
    ville_depart = models.CharField(max_length=100, default="Bobo-Dioulasso")
    ville_destination = models.CharField(max_length=100, default="Ouagadougou")

    # Société de transport / Livreur relais
    transporteur_nom = models.CharField(max_length=150, help_text="Ex: TSR Transport, Rakieta, Transporteur Express")
    transporteur_telephone = models.CharField(max_length=50, blank=True)
    livreur_destinataire = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="expeditions_recues",
        help_text="Livreur assigné devant réceptionner le colis et l'intégrer à son stock"
    )
    destinataire_nom = models.CharField(max_length=150, help_text="Ex: Moussa Sawadogo (Livreur Ouaga)")
    destinataire_telephone = models.CharField(max_length=50, blank=True)

    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='EN_TRANSIT')
    frais_transport = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    consignes_generales = models.TextField(blank=True, help_text="Consignes d'expédition et répartition aux boutiques")
    date_reception = models.DateTimeField(null=True, blank=True)
    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['-date_expedition']
        verbose_name = "Expédition Inter-Villes"
        verbose_name_plural = "Expéditions Inter-Villes"

    def __str__(self):
        return f"{self.numero_bordereau} ({self.ville_depart} -> {self.ville_destination})"

    @property
    def valeur_totale_marchandise(self):
        return self.lignes.aggregate(total=Sum('sous_total'))['total'] or Decimal(0)

    @property
    def nombre_articles_total(self):
        return self.lignes.aggregate(total=Sum('quantite'))['total'] or 0


class LigneExpedition(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    expedition = models.ForeignKey(Expedition, on_delete=models.CASCADE, related_name="lignes")
    produit = models.ForeignKey(Produit, on_delete=models.CASCADE)
    quantite = models.PositiveIntegerField()
    unite = models.CharField(max_length=50, default="sachet")  # sachet, pot, kg, carton
    valeur_unitaire = models.DecimalField(max_digits=10, decimal_places=2)
    sous_total = models.DecimalField(max_digits=12, decimal_places=2)
    consigne_specifique = models.CharField(max_length=255, blank=True, help_text="Ex: 20 sachets réservés pour Boutique Barka")

    class Meta:
        verbose_name = "Ligne d'Expédition"
        verbose_name_plural = "Lignes d'Expédition"

    def __str__(self):
        return f"{self.produit.designation} x {self.quantite} {self.unite}(s) ({self.sous_total:,.0f} FCFA)"


class OrdreMission(models.Model):
    """
    Consignes directes assignées par la Promotrice à un livreur :
    Boutique ciblée, produits à déposer, montant à encaisser, consignes de règlement.
    """
    STATUT_CHOICES = [
        ('A_FAIRE', 'À effectuer'),
        ('LIVRE', 'Livré & Conforme'),
        ('REPORTE', 'Reporté'),
        ('ANNULE', 'Annulé'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entreprise = models.ForeignKey(Entreprise, on_delete=models.CASCADE, null=True, blank=True, related_name="missions")
    tournee = models.ForeignKey(Tournee, on_delete=models.CASCADE, related_name="missions")
    alimentation = models.ForeignKey(Alimentation, on_delete=models.CASCADE, related_name="missions_assignees")
    date_creation = models.DateTimeField(auto_now_add=True)
    produits_consignes = models.TextField(help_text="Ex: 10 sachets mangue 100g, 5 pots miel")
    donnees_produits = models.JSONField(default=dict, blank=True)
    montant_cible = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Montant exact à réclamer")
    consigne_particuliere = models.TextField(blank=True, help_text="Ex: Exiger espèces ou Orange Money, déposer facture")
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='A_FAIRE')
    livraison_vente = models.ForeignKey(LivraisonVente, on_delete=models.SET_NULL, null=True, blank=True, related_name="mission_associee")

    class Meta:
        ordering = ['statut', '-date_creation']
        verbose_name = "Ordre de Mission & Consigne"
        verbose_name_plural = "Ordres de Mission & Consignes"

    def __str__(self):
        return f"Mission {self.alimentation.nom} ({self.montant_cible:,.0f} FCFA)"

    def get_lignes_dict(self):
        """Retourne le dictionnaire {str(produit_id): quantite} des produits consignés."""
        if self.donnees_produits and isinstance(self.donnees_produits, dict):
            # Convertir les valeurs en entiers
            res = {}
            for k, v in self.donnees_produits.items():
                try:
                    res[str(k)] = int(v)
                except (ValueError, TypeError):
                    pass
            if res:
                return res

        # Fallback pour anciennes missions sans donnees_produits : extraction depuis le texte
        res = {}
        if self.produits_consignes:
            import re
            # Récupérer les produits embarqués dans la tournée
            dotations = list(self.tournee.dotations.select_related('produit').all())
            for d in dotations:
                p = d.produit
                # Recherche d'un motif comme "10x Produit" ou "10 Produit"
                pattern = rf'(\d+)\s*(?:x|\*|sachets?|pots?|unit[ée]s?)?\s*{re.escape(p.designation)}'
                match = re.search(pattern, self.produits_consignes, re.IGNORECASE)
                if match:
                    try:
                        res[str(p.id)] = int(match.group(1))
                    except ValueError:
                        pass
        return res

    def get_lignes_json(self):
        import json
        return json.dumps(self.get_lignes_dict())


class DeclarationPaiementBoutique(models.Model):
    """
    Espace Alimentation : Déclaration de paiement directe effectuée par la boutique
    (Orange Money, Moov Money, Espèces) pour apurement de créance sans litige.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entreprise = models.ForeignKey(Entreprise, on_delete=models.CASCADE, null=True, blank=True, related_name="declarations_paiement")
    alimentation = models.ForeignKey(Alimentation, on_delete=models.CASCADE, related_name="declarations_paiement")
    date_declaration = models.DateTimeField(auto_now_add=True)
    montant = models.DecimalField(max_digits=12, decimal_places=2)
    mode_reglement = models.CharField(max_length=20, choices=[
        ('ORANGE_MONEY', 'Orange Money'),
        ('MOOV_MONEY', 'Moov Money'),
        ('ESPECES', 'Espèces (Remis au livreur)'),
    ], default='ORANGE_MONEY')
    reference_transaction = models.CharField(max_length=100, blank=True, help_text="ID transaction OM/Moov")
    valide_par_admin = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-date_declaration']
        verbose_name = "Déclaration de Paiement Boutique"
        verbose_name_plural = "Déclarations de Paiements Boutiques"

    def __str__(self):
        return f"{self.alimentation.nom} - {self.montant:,.0f} FCFA ({self.mode_reglement})"
