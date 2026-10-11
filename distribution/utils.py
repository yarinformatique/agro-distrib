import math
from decimal import Decimal
from django.utils import timezone
from django.db.models import Sum, Count, Q
from .models import Produit, Alimentation, Tournee, LivraisonVente, LigneDotationStock, LigneLivraisonVente


def haversine_distance_km(lat1, lon1, lat2, lon2):
    """
    Calcule la distance en kilomètres entre deux coordonnées géographiques
    selon la formule de Haversine.
    """
    try:
        lat1, lon1 = float(lat1), float(lon1)
        lat2, lon2 = float(lat2), float(lon2)
    except (TypeError, ValueError):
        return None

    R = 6371.0  # Rayon moyen de la Terre en km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def format_distance(distance_km):
    if distance_km is None:
        return "Distance inconnue"
    if distance_km < 1.0:
        return f"{int(distance_km * 1000)} m"
    return f"{distance_km:.1f} km"


def get_alimentations_triees_par_distance(lat, lon, actif_only=True, tenant=None):
    """
    Retourne la liste des alimentations enrichie de la distance calculée
    et triée de la plus proche à la plus éloignée, filtrée par tenant si spécifié.
    """
    qs = Alimentation.objects.all()
    if actif_only:
        qs = qs.filter(actif=True)
    if tenant:
        qs = qs.filter(entreprise=tenant)

    boutiques_avec_distance = []

    for boutique in qs:
        dist_km = haversine_distance_km(lat, lon, boutique.latitude, boutique.longitude)
        boutiques_avec_distance.append({
            'obj': boutique,
            'id': str(boutique.id),
            'nom': boutique.nom,
            'ville': boutique.ville,
            'quartier': boutique.quartier,
            'nom_gerant': boutique.nom_gerant,
            'telephone_gerant': boutique.telephone_gerant,
            'latitude': float(boutique.latitude),
            'longitude': float(boutique.longitude),
            'panier_moyen_estime': float(boutique.panier_moyen_estime),
            'consignes_reglement': boutique.consignes_reglement,
            'distance_km': dist_km if dist_km is not None else 999999.0,
            'distance_formatee': format_distance(dist_km),
            'google_maps_url': boutique.google_maps_url,
            'creance_actuelle': float(boutique.total_creance_en_cours),
        })

    # Tri par distance ascendante
    boutiques_avec_distance.sort(key=lambda x: x['distance_km'])
    return boutiques_avec_distance


def get_dashboard_kpis(date_debut=None, date_fin=None, tenant=None):
    """
    Calcule l'ensemble des indicateurs de performance commerciale et financière,
    avec filtrage strict par tenant (Entreprise).
    """
    ventes_qs = LivraisonVente.objects.all()
    if tenant:
        ventes_qs = ventes_qs.filter(entreprise=tenant)
    if date_debut:
        ventes_qs = ventes_qs.filter(date_heure__date__gte=date_debut)
    if date_fin:
        ventes_qs = ventes_qs.filter(date_heure__date__lte=date_fin)

    agg = ventes_qs.aggregate(
        total_ca=Sum('montant_total'),
        total_encaisse=Sum('montant_paye'),
        nb_ventes=Count('id')
    )

    total_ca = agg['total_ca'] or Decimal(0)
    total_encaisse = agg['total_encaisse'] or Decimal(0)
    total_creances = total_ca - total_encaisse

    # Répartition par mode de règlement
    repartition_paiement = {}
    for code, label in LivraisonVente.MODE_REGLEMENT:
        montant = ventes_qs.filter(mode_reglement=code).aggregate(s=Sum('montant_paye'))['s'] or Decimal(0)
        repartition_paiement[label] = float(montant)

    # Répartition par statut
    repartition_statuts = {}
    for code, label in LivraisonVente.PAIEMENT_STATUS:
        nb = ventes_qs.filter(statut_paiement=code).count()
        repartition_statuts[label] = nb

    # Top produits vendus
    top_produits = (
        LigneLivraisonVente.objects.filter(vente__in=ventes_qs)
        .values('produit__designation', 'produit__unite')
        .annotate(total_qte=Sum('quantite'), total_ca=Sum('sous_total'))
        .order_by('-total_ca')[:5]
    )

    # Alertes stocks entrepôt
    stocks_qs = Produit.objects.all()
    if tenant:
        stocks_qs = stocks_qs.filter(entreprise=tenant)
    stocks_faibles = stocks_qs.filter(stock_entrepot__lte=20).order_by('stock_entrepot')

    # Tournées du jour
    aujourdhui = timezone.localdate()
    tournees_jour = Tournee.objects.filter(date_tournee=aujourdhui)
    if tenant:
        tournees_jour = tournees_jour.filter(entreprise=tenant)
    tournees_en_cours = tournees_jour.filter(statut='EN_COURS').count()

    return {
        'total_ca': total_ca,
        'total_encaisse': total_encaisse,
        'total_creances': total_creances,
        'nb_ventes': agg['nb_ventes'] or 0,
        'repartition_paiement': repartition_paiement,
        'repartition_statuts': repartition_statuts,
        'top_produits': list(top_produits),
        'stocks_faibles': stocks_faibles,
        'tournees_en_cours': tournees_en_cours,
        'nb_tournees_jour': tournees_jour.count(),
    }
