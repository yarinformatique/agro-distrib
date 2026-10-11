from django.contrib import admin
from .models import (
    Entreprise, SocieteLivraison, ProfilUtilisateur,
    Produit, Alimentation, Tournee, LigneDotationStock,
    LivraisonVente, LigneLivraisonVente, ReglementCreance,
    Expedition, LigneExpedition, OrdreMission, DeclarationPaiementBoutique
)


@admin.register(Entreprise)
class EntrepriseAdmin(admin.ModelAdmin):
    list_display = ('nom', 'slug', 'statut_abonnement', 'ville', 'contact_nom', 'contact_telephone', 'date_creation', 'actif')
    list_filter = ('statut_abonnement', 'actif', 'ville')
    search_fields = ('nom', 'contact_nom', 'contact_email', 'contact_telephone')
    prepopulated_fields = {'slug': ('nom',)}


@admin.register(SocieteLivraison)
class SocieteLivraisonAdmin(admin.ModelAdmin):
    list_display = ('nom', 'entreprise', 'responsable', 'telephone', 'ville', 'actif')
    list_filter = ('entreprise', 'actif', 'ville')
    search_fields = ('nom', 'responsable', 'telephone')


@admin.register(ProfilUtilisateur)
class ProfilUtilisateurAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'entreprise', 'societe_livraison', 'telephone')
    list_filter = ('role', 'entreprise')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'telephone')


class LigneDotationInline(admin.TabularInline):
    model = LigneDotationStock
    extra = 1


class LigneLivraisonVenteInline(admin.TabularInline):
    model = LigneLivraisonVente
    extra = 1


class LigneExpeditionInline(admin.TabularInline):
    model = LigneExpedition
    extra = 1


@admin.register(Produit)
class ProduitAdmin(admin.ModelAdmin):
    list_display = ('designation', 'entreprise', 'unite', 'prix_unitaire_defaut', 'stock_entrepot')
    search_fields = ('designation',)
    list_filter = ('entreprise', 'unite',)


@admin.register(Alimentation)
class AlimentationAdmin(admin.ModelAdmin):
    list_display = ('nom', 'entreprise', 'quartier', 'ville', 'nom_gerant', 'telephone_gerant', 'code_pin', 'actif')
    search_fields = ('nom', 'quartier', 'nom_gerant', 'telephone_gerant')
    list_filter = ('entreprise', 'ville', 'actif', 'quartier')


@admin.register(Tournee)
class TourneeAdmin(admin.ModelAdmin):
    list_display = ('id_court', 'entreprise', 'livreur', 'date_tournee', 'statut', 'caisse_theorique', 'caisse_declaree', 'ecart_caisse_display')
    list_filter = ('entreprise', 'statut', 'date_tournee', 'livreur')
    inlines = [LigneDotationInline]

    def id_court(self, obj):
        return str(obj.id)[:8]
    id_court.short_description = "ID"

    def ecart_caisse_display(self, obj):
        return f"{obj.ecart_caisse:,.0f} FCFA"
    ecart_caisse_display.short_description = "Écart Caisse"


@admin.register(LivraisonVente)
class LivraisonVenteAdmin(admin.ModelAdmin):
    list_display = ('id_court', 'entreprise', 'alimentation', 'tournee', 'date_heure', 'montant_total', 'montant_paye', 'statut_paiement', 'mode_reglement', 'confirme_par_boutique')
    list_filter = ('entreprise', 'statut_paiement', 'mode_reglement', 'confirme_par_boutique', 'date_heure')
    search_fields = ('alimentation__nom', 'alimentation__quartier')
    inlines = [LigneLivraisonVenteInline]

    def id_court(self, obj):
        return str(obj.id)[:8]
    id_court.short_description = "N° Vente"


@admin.register(ReglementCreance)
class ReglementCreanceAdmin(admin.ModelAdmin):
    list_display = ('vente', 'entreprise', 'date_reglement', 'montant', 'mode_reglement', 'recu_par')
    list_filter = ('entreprise', 'mode_reglement', 'date_reglement')


@admin.register(Expedition)
class ExpeditionAdmin(admin.ModelAdmin):
    list_display = ('numero_bordereau', 'entreprise', 'ville_depart', 'ville_destination', 'transporteur_nom', 'statut', 'date_expedition')
    list_filter = ('entreprise', 'statut', 'ville_depart', 'ville_destination')
    inlines = [LigneExpeditionInline]


@admin.register(OrdreMission)
class OrdreMissionAdmin(admin.ModelAdmin):
    list_display = ('tournee', 'entreprise', 'alimentation', 'montant_cible', 'statut', 'date_creation')
    list_filter = ('entreprise', 'statut', 'date_creation')


@admin.register(DeclarationPaiementBoutique)
class DeclarationPaiementBoutiqueAdmin(admin.ModelAdmin):
    list_display = ('alimentation', 'entreprise', 'montant', 'mode_reglement', 'reference_transaction', 'date_declaration', 'valide_par_admin')
    list_filter = ('entreprise', 'valide_par_admin', 'mode_reglement', 'date_declaration')
