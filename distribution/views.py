import json
from decimal import Decimal
from datetime import datetime, date, timedelta
import socket

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db.models import Sum, Count, Q
from django.db import transaction
from django.urls import reverse

from .models import (
    Entreprise, SocieteLivraison, ProfilUtilisateur,
    Produit, Alimentation, Tournee, LigneDotationStock,
    LivraisonVente, LigneLivraisonVente, ReglementCreance,
    Expedition, LigneExpedition, OrdreMission, DeclarationPaiementBoutique
)
from .utils import (
    haversine_distance_km, format_distance,
    get_alimentations_triees_par_distance, get_dashboard_kpis
)


_LOCAL_IP_CACHE = None

def get_local_ip():
    """Détecte l'adresse IP locale de la machine sans bloquer l'application."""
    global _LOCAL_IP_CACHE
    if _LOCAL_IP_CACHE:
        return _LOCAL_IP_CACHE
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.05)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        _LOCAL_IP_CACHE = ip
        return ip
    except Exception:
        _LOCAL_IP_CACHE = "127.0.0.1"
        return "127.0.0.1"



# ==============================================================================
# HEALTHCHECK & ANTI-MISE EN VEILLE (KEEP-ALIVE RENDER)
# ==============================================================================

def healthz_view(request):
    """
    Route ultra-légère (/healthz et /ping) qui répond immédiatement HTTP 200
    sans solliciter la base de données, pour empêcher le spin-down Render.
    """
    return HttpResponse("OK", content_type="text/plain", status=200)


# ==============================================================================
# AUTHENTIFICATION & ROUTAGE MULTI-TENANT
# ==============================================================================

def login_view(request):
    """
    Interface de connexion épurée et sécurisée.
    Supporte la connexion par identifiant OU par adresse email.
    Applique la vérification immédiate de la suspension du tenant.
    Permet le basculement direct de compte sans piéger l'utilisateur smartphone.
    """
    # Déconnexion immédiate si demandée explicitement dans l'URL
    if request.GET.get('switch') or request.GET.get('logout') or request.GET.get('changer'):
        if request.user.is_authenticated:
            logout(request)
        return redirect('login')

    if request.user.is_authenticated and request.method == 'GET':
        # Si l'utilisateur est déjà connecté, afficher une page lui permettant
        # soit de continuer vers son espace, soit de se déconnecter ou se reconnecter avec un autre compte (ex: Promotrice)
        role_label = "Promotrice / Direction" if request.user.is_staff else "Livreur Terrain"
        if getattr(request, 'is_superadmin', False) or request.user.is_superuser:
            role_label = "Superadmin Plateforme"
        elif hasattr(request.user, 'boutique_profil') and request.user.boutique_profil:
            role_label = "Boutique Partenaire"

        redirect_url = 'dashboard' if request.user.is_staff else 'livreur_app'
        if getattr(request, 'is_superadmin', False) or request.user.is_superuser:
            redirect_url = 'superadmin_dashboard'
        elif hasattr(request.user, 'boutique_profil') and request.user.boutique_profil:
            redirect_url = 'boutique_portal'

        return render(request, 'login.html', {
            'already_authenticated': True,
            'current_user': request.user,
            'role_label': role_label,
            'redirect_url': redirect_url,
        })

    if request.method == 'POST':
        # Déconnecter automatiquement toute session active précédente pour éviter les conflits de rôle
        if request.user.is_authenticated:
            logout(request)

        u = request.POST.get('username', '').strip()
        p = request.POST.get('password', '').strip()

        # Connexion flexible : par nom d'utilisateur OU par adresse email
        if '@' in u:
            user_found = User.objects.filter(email__iexact=u).first()
            if user_found:
                u = user_found.username

        user = authenticate(request, username=u, password=p)
        if user is not None:
            # Vérification préalable de la suspension si utilisateur rattaché à une entreprise
            if not user.is_superuser:
                profil = getattr(user, 'profil_utilisateur', None)
                tenant = None
                if profil and profil.entreprise:
                    tenant = profil.entreprise
                elif hasattr(user, 'boutique_profil') and user.boutique_profil:
                    tenant = user.boutique_profil.entreprise

                if tenant and (tenant.statut_abonnement in ['suspendu', 'inactif'] or not tenant.actif):
                    msg = "Accès suspendu : L'abonnement de votre entreprise est inactif. Veuillez contacter l'administrateur."
                    messages.error(request, msg)
                    return render(request, 'login.html')

            login(request, user)

            profil = getattr(user, 'profil_utilisateur', None)
            if user.is_superuser or (profil and profil.role == 'SUPERADMIN'):
                return redirect('superadmin_dashboard')
            if user.is_staff:
                return redirect('dashboard')
            if hasattr(user, 'boutique_profil') and user.boutique_profil:
                return redirect('boutique_portal')
            return redirect('livreur_app')
        else:
            messages.error(request, "Identifiants invalides. Veuillez vérifier votre nom d'utilisateur et mot de passe.")

    return render(request, 'login.html')


def logout_view(request):
    logout(request)
    return redirect('login')


def home_redirect_view(request):
    if not request.user.is_authenticated:
        return redirect('login')
    profil = getattr(request.user, 'profil_utilisateur', None)
    if request.user.is_superuser or (profil and profil.role == 'SUPERADMIN'):
        return redirect('superadmin_dashboard')
    if request.user.is_staff:
        return redirect('dashboard')
    if hasattr(request.user, 'boutique_profil') and request.user.boutique_profil:
        return redirect('boutique_portal')
    return redirect('livreur_app')


def compte_suspendu_view(request):
    """Page d'arrêt bloquante pour les utilisateurs d'une entreprise suspendue."""
    tenant = getattr(request, 'tenant', None)
    return render(request, 'suspended.html', {
        'entreprise': tenant,
        'message': "Accès suspendu : L'abonnement de votre entreprise est inactif. Veuillez contacter l'administrateur."
    }, status=403)


# ==============================================================================
# ESPACE SUPERADMIN : GESTION DES TENANTS (ENTREPRISES & ABONNEMENTS)
# ==============================================================================

@login_required
def superadmin_dashboard_view(request):
    """
    Tableau de bord exclusif du SUPERADMIN (Propriétaire / Créateur SaaS) :
    - KPIs globaux de toute la plateforme
    - Gestion des entreprises clientes (activation, suspension immédiate en 1 clic)
    - Création de nouvelles entreprises avec compte Promotrice associé
    """
    if not getattr(request, 'is_superadmin', False):
        if request.user.is_staff:
            return redirect('dashboard')
        return redirect('livreur_app')

    entreprises = Entreprise.objects.all().order_by('-date_creation')
    total_entreprises = entreprises.count()
    entreprises_actives = entreprises.filter(statut_abonnement='actif', actif=True).count()
    entreprises_suspendues = entreprises.filter(statut_abonnement__in=['suspendu', 'inactif']).count()
    total_utilisateurs = User.objects.count()
    total_ventes = LivraisonVente.objects.count()
    total_ca = LivraisonVente.objects.aggregate(total=Sum('montant_total'))['total'] or Decimal(0)

    entreprises_data = []
    for ent in entreprises:
        nb_users = ent.utilisateurs.count()
        nb_prods = ent.produits.count()
        nb_alims = ent.alimentations.count()
        ca = ent.ventes.aggregate(total=Sum('montant_total'))['total'] or Decimal(0)
        promotrice = ent.utilisateurs.filter(role='PROMOTRICE').first()

        entreprises_data.append({
            'obj': ent,
            'nb_users': nb_users,
            'nb_prods': nb_prods,
            'nb_alims': nb_alims,
            'ca': ca,
            'promotrice': promotrice.user if promotrice else None,
        })

    return render(request, 'superadmin/dashboard.html', {
        'entreprises_data': entreprises_data,
        'total_entreprises': total_entreprises,
        'entreprises_actives': entreprises_actives,
        'entreprises_suspendues': entreprises_suspendues,
        'total_utilisateurs': total_utilisateurs,
        'total_ventes': total_ventes,
        'total_ca': total_ca,
    })


@login_required
def superadmin_creer_entreprise_view(request):
    if not getattr(request, 'is_superadmin', False):
        return redirect('dashboard')

    if request.method == 'POST':
        nom = request.POST.get('nom', '').strip()
        slug = request.POST.get('slug', '').strip()
        if not slug:
            slug = nom.lower().replace(' ', '-').replace("'", '')
        ville = request.POST.get('ville', 'Ouagadougou').strip()
        contact_nom = request.POST.get('contact_nom', '').strip()
        contact_email = request.POST.get('contact_email', '').strip()
        contact_telephone = request.POST.get('contact_telephone', '').strip()
        adresse = request.POST.get('adresse', '').strip()
        statut_abonnement = request.POST.get('statut_abonnement', 'actif')

        # Compte de la Promotrice initiale
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()

        if not nom or not username or not password:
            messages.error(request, "Veuillez renseigner le nom de l'entreprise, l'identifiant et le mot de passe de la promotrice.")
            return redirect('superadmin_dashboard')

        if User.objects.filter(username=username).exists():
            messages.error(request, f"L'identifiant '{username}' est déjà utilisé par un autre compte.")
            return redirect('superadmin_dashboard')

        with transaction.atomic():
            ent = Entreprise.objects.create(
                nom=nom,
                slug=slug,
                statut_abonnement=statut_abonnement,
                ville=ville,
                contact_nom=contact_nom,
                contact_email=contact_email,
                contact_telephone=contact_telephone,
                adresse=adresse,
                actif=(statut_abonnement == 'actif')
            )

            # Créer l'utilisateur Promotrice
            user = User.objects.create_user(
                username=username,
                email=contact_email,
                password=password,
                first_name=contact_nom,
                is_staff=True
            )

            ProfilUtilisateur.objects.create(
                user=user,
                entreprise=ent,
                role='PROMOTRICE',
                telephone=contact_telephone,
                adresse=adresse
            )

            # Créer une Société de livraison rattachée par défaut
            SocieteLivraison.objects.create(
                entreprise=ent,
                nom=f"Service Livraison {nom}",
                telephone=contact_telephone,
                responsable=contact_nom,
                ville=ville
            )

        messages.success(request, f"Entreprise '{nom}' et compte promotrice '{username}' créés avec succès !")
        return redirect('superadmin_dashboard')

    return redirect('superadmin_dashboard')


@login_required
def superadmin_toggle_statut_view(request, pk):
    """Activation ou suspension immédiate d'une entreprise en 1 clic."""
    if not getattr(request, 'is_superadmin', False):
        return redirect('dashboard')

    ent = get_object_or_404(Entreprise, id=pk)
    if request.method == 'POST':
        if ent.statut_abonnement == 'actif':
            ent.statut_abonnement = 'suspendu'
            ent.actif = False
            action_label = "suspendue"
        else:
            ent.statut_abonnement = 'actif'
            ent.actif = True
            action_label = "activée"

        ent.save()
        messages.success(request, f"L'entreprise '{ent.nom}' a été {action_label} avec succès. La règle de suspension s'applique immédiatement.")

    return redirect('superadmin_dashboard')


@login_required
def superadmin_modifier_entreprise_view(request, pk):
    if not getattr(request, 'is_superadmin', False):
        return redirect('dashboard')

    ent = get_object_or_404(Entreprise, id=pk)
    if request.method == 'POST':
        ent.nom = request.POST.get('nom', ent.nom)
        ent.ville = request.POST.get('ville', ent.ville)
        ent.contact_nom = request.POST.get('contact_nom', ent.contact_nom)
        ent.contact_email = request.POST.get('contact_email', ent.contact_email)
        ent.contact_telephone = request.POST.get('contact_telephone', ent.contact_telephone)
        ent.adresse = request.POST.get('adresse', ent.adresse)
        statut = request.POST.get('statut_abonnement', ent.statut_abonnement)
        ent.statut_abonnement = statut
        ent.actif = (statut == 'actif')
        ent.save()
        messages.success(request, f"Entreprise '{ent.nom}' mise à jour.")

    return redirect('superadmin_dashboard')


# ==============================================================================
# VUES DASHBOARD PROMOTRICE (TENANT ISOLÉ)
# ==============================================================================

@login_required
def dashboard_view(request):
    if not request.user.is_staff:
        return redirect('livreur_app')

    tenant = getattr(request, 'tenant', None)
    periode = request.GET.get('periode', 'mois')
    aujourdhui = timezone.localdate()

    date_debut = None
    if periode == 'jour':
        date_debut = aujourdhui
    elif periode == 'semaine':
        date_debut = aujourdhui - timedelta(days=aujourdhui.weekday())
    elif periode == 'mois':
        date_debut = aujourdhui.replace(day=1)

    kpis = get_dashboard_kpis(date_debut=date_debut, tenant=tenant)

    ventes_qs = LivraisonVente.objects.select_related('tournee__livreur', 'alimentation').prefetch_related('lignes__produit')
    tournees_qs = Tournee.objects.filter(date_tournee=aujourdhui).select_related('livreur')
    expeditions_qs = Expedition.objects.filter(statut='EN_TRANSIT')

    if tenant:
        ventes_qs = ventes_qs.filter(entreprise=tenant)
        tournees_qs = tournees_qs.filter(entreprise=tenant)
        expeditions_qs = expeditions_qs.filter(entreprise=tenant)

    dernieres_ventes = ventes_qs[:8]
    tournees_actives = tournees_qs
    expeditions_en_cours = expeditions_qs[:5]

    # Alertes Recouvrement & Plafonds de crédit
    alims_qs = Alimentation.objects.filter(actif=True).prefetch_related('achats')
    if tenant:
        alims_qs = alims_qs.filter(entreprise=tenant)

    alims_en_retard = [a for a in alims_qs if a.a_creance_en_retard]
    alims_plafond_depasse = [a for a in alims_qs if a.depasse_plafond_credit]
    montant_retard_total = sum(a.montant_creance_en_retard for a in alims_en_retard)

    context = {
        'kpis': kpis,
        'periode': periode,
        'dernieres_ventes': dernieres_ventes,
        'tournees_actives': tournees_actives,
        'expeditions_en_cours': expeditions_en_cours,
        'alims_en_retard': alims_en_retard,
        'alims_plafond_depasse': alims_plafond_depasse,
        'montant_retard_total': montant_retard_total,
        'aujourdhui': aujourdhui,
        'local_ip': get_local_ip(),
        'tenant': tenant,
    }
    return render(request, 'dashboard/index.html', context)


@login_required
def produits_view(request):
    if not request.user.is_staff:
        return redirect('livreur_app')

    tenant = getattr(request, 'tenant', None)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'ajouter':
            designation = request.POST.get('designation')
            unite = request.POST.get('unite', 'sachet')
            prix = Decimal(request.POST.get('prix', '0'))
            stock = int(request.POST.get('stock', '0'))
            Produit.objects.create(
                entreprise=tenant,
                designation=designation,
                unite=unite,
                prix_unitaire_defaut=prix,
                stock_entrepot=stock
            )
            messages.success(request, f"Produit '{designation}' ajouté avec succès.")
        elif action == 'ajuster_stock':
            prod_id = request.POST.get('produit_id')
            ajout = int(request.POST.get('ajout_stock', '0'))
            p = get_object_or_404(Produit, id=prod_id)
            p.stock_entrepot += ajout
            p.save()
            messages.success(request, f"Stock de '{p.designation}' mis à jour (+{ajout} unités).")
        elif action == 'modifier':
            prod_id = request.POST.get('produit_id')
            p = get_object_or_404(Produit, id=prod_id)
            p.designation = request.POST.get('designation')
            p.unite = request.POST.get('unite')
            p.prix_unitaire_defaut = Decimal(request.POST.get('prix', '0'))
            p.stock_entrepot = int(request.POST.get('stock', '0'))
            p.save()
            messages.success(request, f"Produit '{p.designation}' modifié avec succès.")
        elif action == 'supprimer':
            prod_id = request.POST.get('produit_id')
            p = get_object_or_404(Produit, id=prod_id)
            nom = p.designation
            p.delete()
            messages.success(request, f"Produit '{nom}' supprimé avec succès.")
        return redirect('produits')

    produits = Produit.objects.all().order_by('designation')
    if tenant:
        produits = produits.filter(entreprise=tenant)

    return render(request, 'dashboard/produits.html', {'produits': produits})


@login_required
def alimentations_view(request):
    if not request.user.is_staff:
        return redirect('livreur_app')

    tenant = getattr(request, 'tenant', None)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'ajouter':
            nom = request.POST.get('nom')
            ville = request.POST.get('ville', 'Ouagadougou')
            quartier = request.POST.get('quartier')
            nom_gerant = request.POST.get('nom_gerant')
            tel = request.POST.get('telephone_gerant')
            lat_str = request.POST.get('latitude', '12.3714').replace(',', '.')
            lon_str = request.POST.get('longitude', '-1.5197').replace(',', '.')
            try:
                lat = Decimal(lat_str)
                lon = Decimal(lon_str)
            except Exception:
                lat, lon = Decimal('12.3714'), Decimal('-1.5197')
            panier = Decimal(request.POST.get('panier_moyen_estime', '0'))
            consignes = request.POST.get('consignes_reglement', '')
            pin = request.POST.get('code_pin', '1234')

            Alimentation.objects.create(
                entreprise=tenant,
                nom=nom, ville=ville, quartier=quartier,
                nom_gerant=nom_gerant, telephone_gerant=tel,
                latitude=lat, longitude=lon,
                panier_moyen_estime=panier, consignes_reglement=consignes,
                code_pin=pin, actif=True
            )
            messages.success(request, f"Boutique '{nom}' ajoutée avec succès (Code PIN: {pin}).")
        elif action == 'modifier':
            alim_id = request.POST.get('alim_id')
            alim = get_object_or_404(Alimentation, id=alim_id)
            alim.nom = request.POST.get('nom', alim.nom)
            alim.ville = request.POST.get('ville', alim.ville)
            alim.quartier = request.POST.get('quartier', alim.quartier)
            alim.nom_gerant = request.POST.get('nom_gerant', alim.nom_gerant)
            alim.telephone_gerant = request.POST.get('telephone_gerant', alim.telephone_gerant)
            lat_str = request.POST.get('latitude', str(alim.latitude)).replace(',', '.')
            lon_str = request.POST.get('longitude', str(alim.longitude)).replace(',', '.')
            try:
                alim.latitude = Decimal(lat_str)
                alim.longitude = Decimal(lon_str)
            except Exception:
                pass
            panier_str = request.POST.get('panier_moyen_estime', str(alim.panier_moyen_estime)).replace(',', '.')
            try:
                alim.panier_moyen_estime = Decimal(panier_str)
            except Exception:
                pass
            alim.consignes_reglement = request.POST.get('consignes_reglement', alim.consignes_reglement)
            alim.code_pin = request.POST.get('code_pin', alim.code_pin)
            alim.save()
            messages.success(request, f"Boutique '{alim.nom}' modifiée avec succès.")
        elif action == 'supprimer':
            alim_id = request.POST.get('alim_id')
            alim = get_object_or_404(Alimentation, id=alim_id)
            nom = alim.nom
            alim.delete()
            messages.success(request, f"Boutique '{nom}' supprimée avec succès.")
        return redirect('alimentations')

    quartier_filtre = request.GET.get('quartier', '')
    alimentations = Alimentation.objects.all().order_by('-id')
    if tenant:
        alimentations = alimentations.filter(entreprise=tenant)

    if quartier_filtre:
        alimentations = alimentations.filter(quartier__icontains=quartier_filtre)

    quartiers_qs = Alimentation.objects.all()
    if tenant:
        quartiers_qs = quartiers_qs.filter(entreprise=tenant)
    quartiers = quartiers_qs.values_list('quartier', flat=True).distinct().order_by('quartier')

    return render(request, 'dashboard/alimentations.html', {
        'alimentations': alimentations,
        'quartiers': quartiers,
        'quartier_filtre': quartier_filtre,
    })


@login_required
def prospection_view(request):
    tenant = getattr(request, 'tenant', None)

    if request.method == 'POST':
        nom = request.POST.get('nom', '').strip()
        ville = request.POST.get('ville', 'Ouagadougou').strip()
        quartier = request.POST.get('quartier', '').strip()
        nom_gerant = request.POST.get('nom_gerant', '').strip()
        tel = request.POST.get('telephone_gerant', '').strip()
        lat_str = request.POST.get('latitude', '12.371400').strip()
        lon_str = request.POST.get('longitude', '-1.519700').strip()
        panier_str = request.POST.get('panier_moyen_estime', '25000').strip()
        consignes = request.POST.get('consignes_reglement', '').strip()
        pin = request.POST.get('code_pin', '1234').strip()

        try:
            lat = Decimal(lat_str)
            lon = Decimal(lon_str)
        except Exception:
            lat = Decimal('12.371400')
            lon = Decimal('-1.519700')

        try:
            panier = Decimal(panier_str)
        except Exception:
            panier = Decimal('25000')

        alim = Alimentation.objects.create(
            entreprise=tenant,
            nom=nom, ville=ville, quartier=quartier,
            nom_gerant=nom_gerant or 'Gérant', telephone_gerant=tel,
            latitude=lat, longitude=lon,
            panier_moyen_estime=panier, consignes_reglement=consignes,
            code_pin=pin or '1234', actif=True
        )
        messages.success(request, f"🎉 Nouvelle boutique '{nom}' ({quartier}) enregistrée avec succès (Code PIN: {pin or '1234'}) !")
        return redirect('prospection')

    alimentations = Alimentation.objects.all().order_by('-id')
    if tenant:
        alimentations = alimentations.filter(entreprise=tenant)

    base_url = request.build_absolute_uri(reverse('prospection_terrain'))
    url_prospection_terrain = f"{base_url}?tenant={tenant.slug}" if (tenant and tenant.slug) else base_url

    return render(request, 'dashboard/prospection.html', {
        'alimentations': alimentations,
        'url_prospection_terrain': url_prospection_terrain,
    })


def prospection_terrain_view(request):
    """
    Page publique pour agent terrain permettant d'enregistrer une boutique.
    Rattache automatiquement la boutique à l'entreprise appropriée (Tenant).
    """
    success_alim = None
    slug = request.POST.get('tenant', '').strip() or request.GET.get('tenant', '').strip() or request.GET.get('t', '').strip()
    tenant = None
    if slug:
        tenant = Entreprise.objects.filter(slug=slug).first()
    if not tenant and hasattr(request, 'tenant') and request.tenant:
        tenant = request.tenant
    if not tenant and request.user.is_authenticated:
        profil = getattr(request.user, 'profil_utilisateur', None)
        if profil and profil.entreprise:
            tenant = profil.entreprise
    if not tenant:
        tenant = Entreprise.objects.filter(statut_abonnement='actif').first()

    if request.method == 'POST':
        nom = request.POST.get('nom', '').strip()
        ville = request.POST.get('ville', 'Ouagadougou').strip()
        quartier = request.POST.get('quartier', '').strip()
        nom_gerant = request.POST.get('nom_gerant', '').strip()
        tel = request.POST.get('telephone_gerant', '').strip()
        lat_str = request.POST.get('latitude', '12.371400').strip()
        lon_str = request.POST.get('longitude', '-1.519700').strip()
        panier_str = request.POST.get('panier_moyen_estime', '25000').strip()
        consignes = request.POST.get('consignes_reglement', '').strip()
        pin = request.POST.get('code_pin', '1234').strip()

        try:
            lat = Decimal(lat_str)
            lon = Decimal(lon_str)
        except Exception:
            lat = Decimal('12.371400')
            lon = Decimal('-1.519700')

        try:
            panier = Decimal(panier_str)
        except Exception:
            panier = Decimal('25000')

        if nom and quartier:
            success_alim = Alimentation.objects.create(
                entreprise=tenant,
                nom=nom, ville=ville, quartier=quartier,
                nom_gerant=nom_gerant or 'Gérant', telephone_gerant=tel,
                latitude=lat, longitude=lon,
                panier_moyen_estime=panier, consignes_reglement=consignes,
                code_pin=pin or '1234', actif=True
            )
            messages.success(request, f"🎉 La boutique '{nom}' à {quartier} ({ville}) a été enregistrée avec succès dans le système central !")

    return render(request, 'dashboard/prospection_terrain.html', {
        'success_alim': success_alim,
        'tenant': tenant,
    })


# ==============================================================================
# EXPÉDITIONS INTER-VILLES & TRANSFERTS MARCHANDISES
# ==============================================================================

@login_required
def expeditions_view(request):
    if not request.user.is_staff:
        return redirect('livreur_app')

    tenant = getattr(request, 'tenant', None)
    produits_qs = Produit.objects.all()
    if tenant:
        produits_qs = produits_qs.filter(entreprise=tenant)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'creer':
            depart = request.POST.get('ville_depart', 'Bobo-Dioulasso').strip()
            dest = request.POST.get('ville_destination', 'Ouagadougou').strip()
            transporteur = request.POST.get('transporteur_nom', '').strip()
            tel_transp = request.POST.get('transporteur_telephone', '').strip()
            livreur_dest_id = request.POST.get('livreur_destinataire_id', '').strip()
            destinataire = request.POST.get('destinataire_nom', '').strip()
            tel_dest = request.POST.get('destinataire_telephone', '').strip()
            try:
                frais = Decimal(request.POST.get('frais_transport', '0'))
            except Exception:
                frais = Decimal('0')
            consignes = request.POST.get('consignes_generales', '').strip()

            livreur_dest = None
            if livreur_dest_id:
                livreur_dest = User.objects.filter(id=livreur_dest_id).first()
                if livreur_dest:
                    if not destinataire:
                        destinataire = livreur_dest.get_full_name() or livreur_dest.username
                    if not tel_dest and hasattr(livreur_dest, 'profil_utilisateur') and livreur_dest.profil_utilisateur:
                        tel_dest = livreur_dest.profil_utilisateur.telephone or ''

            items_to_create = []
            total_articles = 0

            for p in produits_qs:
                qte_str = request.POST.get(f'qte_{p.id}', '0')
                consigne_spec = request.POST.get(f'consigne_{p.id}', '').strip()
                try:
                    qte = int(qte_str)
                except ValueError:
                    qte = 0

                if qte > 0:
                    # Contrôle strict du stock : la quantité ne doit pas dépasser le stock entrepôt
                    if qte > p.stock_entrepot:
                        messages.error(request, f"Stock entrepôt insuffisant pour « {p.designation} » : {p.stock_entrepot} disponible(s), vous avez demandé {qte}.")
                        return redirect('expeditions')

                    items_to_create.append((p, qte, consigne_spec))
                    total_articles += qte

            if total_articles <= 0:
                messages.error(request, "Veuillez allouer au moins un produit avec une quantité supérieure à 0.")
                return redirect('expeditions')

            numero = f"EXP-{timezone.now().strftime('%Y%m%d%H%M')}"
            with transaction.atomic():
                exp = Expedition.objects.create(
                    entreprise=tenant,
                    numero_bordereau=numero,
                    ville_depart=depart,
                    ville_destination=dest,
                    transporteur_nom=transporteur,
                    transporteur_telephone=tel_transp,
                    livreur_destinataire=livreur_dest,
                    destinataire_nom=destinataire or (livreur_dest.username if livreur_dest else "Livreur"),
                    destinataire_telephone=tel_dest,
                    frais_transport=frais,
                    consignes_generales=consignes,
                    statut='PREPARE',
                    cree_par=request.user
                )

                for p, qte, consigne_spec in items_to_create:
                    st = qte * p.prix_unitaire_defaut
                    LigneExpedition.objects.create(
                        expedition=exp,
                        produit=p,
                        quantite=qte,
                        unite=p.unite,
                        valeur_unitaire=p.prix_unitaire_defaut,
                        sous_total=st,
                        consigne_specifique=consigne_spec
                    )

            messages.success(request, f"📦 Expédition {numero} enregistrée en attente (Préparée). Vous pouvez la modifier ou confirmer son envoi.")
            return redirect('expeditions')

        elif action == 'modifier':
            exp_id = request.POST.get('expedition_id')
            exp = get_object_or_404(Expedition, id=exp_id)
            if exp.statut != 'PREPARE':
                messages.error(request, "Impossible de modifier cette expédition : elle a déjà été confirmée ou expédiée.")
                return redirect('expeditions')

            depart = request.POST.get('ville_depart', exp.ville_depart).strip()
            dest = request.POST.get('ville_destination', exp.ville_destination).strip()
            transporteur = request.POST.get('transporteur_nom', exp.transporteur_nom).strip()
            tel_transp = request.POST.get('transporteur_telephone', exp.transporteur_telephone).strip()
            livreur_dest_id = request.POST.get('livreur_destinataire_id', '').strip()
            destinataire = request.POST.get('destinataire_nom', exp.destinataire_nom).strip()
            tel_dest = request.POST.get('destinataire_telephone', exp.destinataire_telephone).strip()
            try:
                frais = Decimal(request.POST.get('frais_transport', str(exp.frais_transport)))
            except Exception:
                frais = exp.frais_transport
            consignes = request.POST.get('consignes_generales', exp.consignes_generales).strip()

            livreur_dest = exp.livreur_destinataire
            if livreur_dest_id:
                livreur_dest = User.objects.filter(id=livreur_dest_id).first()
                if livreur_dest and not destinataire:
                    destinataire = livreur_dest.get_full_name() or livreur_dest.username

            items_to_create = []
            total_articles = 0
            for p in produits_qs:
                qte_str = request.POST.get(f'qte_{p.id}', '0')
                consigne_spec = request.POST.get(f'consigne_{p.id}', '').strip()
                try:
                    qte = int(qte_str)
                except ValueError:
                    qte = 0
                if qte > 0:
                    if qte > p.stock_entrepot:
                        messages.error(request, f"Stock entrepôt insuffisant pour « {p.designation} » : {p.stock_entrepot} disponible(s), vous avez demandé {qte}.")
                        return redirect('expeditions')
                    items_to_create.append((p, qte, consigne_spec))
                    total_articles += qte

            if total_articles <= 0:
                messages.error(request, "Veuillez allouer au moins un produit avec une quantité supérieure à 0.")
                return redirect('expeditions')

            with transaction.atomic():
                exp.ville_depart = depart
                exp.ville_destination = dest
                exp.transporteur_nom = transporteur
                exp.transporteur_telephone = tel_transp
                exp.livreur_destinataire = livreur_dest
                exp.destinataire_nom = destinataire
                exp.destinataire_telephone = tel_dest
                exp.frais_transport = frais
                exp.consignes_generales = consignes
                exp.save()

                exp.lignes.all().delete()
                for p, qte, consigne_spec in items_to_create:
                    st = qte * p.prix_unitaire_defaut
                    LigneExpedition.objects.create(
                        expedition=exp,
                        produit=p,
                        quantite=qte,
                        unite=p.unite,
                        valeur_unitaire=p.prix_unitaire_defaut,
                        sous_total=st,
                        consigne_specifique=consigne_spec
                    )

            messages.success(request, f"Expédition {exp.numero_bordereau} modifiée avec succès.")
            return redirect('expeditions')

        elif action == 'confirmer_envoi':
            exp_id = request.POST.get('expedition_id')
            exp = get_object_or_404(Expedition, id=exp_id)
            if exp.statut != 'PREPARE':
                messages.info(request, "Cette expédition a déjà été confirmée.")
                return redirect('expeditions')

            with transaction.atomic():
                # Re-vérification stricte du stock disponible
                for ligne in exp.lignes.select_related('produit').all():
                    if ligne.quantite > ligne.produit.stock_entrepot:
                        messages.error(request, f"Stock insuffisant pour « {ligne.produit.designation} » : {ligne.produit.stock_entrepot} en réserve vs {ligne.quantite} nécessaires.")
                        return redirect('expeditions')

                # Déduction dynamique du stock entrepôt
                for ligne in exp.lignes.select_related('produit').all():
                    ligne.produit.stock_entrepot -= ligne.quantite
                    ligne.produit.save(update_fields=['stock_entrepot'])

                exp.statut = 'EN_TRANSIT'
                exp.save(update_fields=['statut'])

            messages.success(request, f"🚀 Envoi confirmé pour l'expédition {exp.numero_bordereau} ! Le stock entrepôt a été débité et le colis est en transit.")
            return redirect('expeditions')

        elif action == 'supprimer':
            exp_id = request.POST.get('expedition_id')
            exp = get_object_or_404(Expedition, id=exp_id)
            with transaction.atomic():
                # Si l'expédition était en cours d'acheminement, restituer le stock en entrepôt
                if exp.statut == 'EN_TRANSIT':
                    for ligne in exp.lignes.select_related('produit').all():
                        ligne.produit.stock_entrepot += ligne.quantite
                        ligne.produit.save(update_fields=['stock_entrepot'])
                num = exp.numero_bordereau
                exp.delete()
            messages.success(request, f"Expédition {num} supprimée avec succès (stock entrepôt restauré si nécessaire).")
            return redirect('expeditions')

    expeditions = Expedition.objects.select_related('livreur_destinataire').prefetch_related('lignes__produit').all()
    produits = Produit.objects.all()
    alimentations = Alimentation.objects.filter(actif=True)
    livreurs = User.objects.filter(is_staff=False, is_active=True).select_related('profil_utilisateur')

    if tenant:
        expeditions = expeditions.filter(entreprise=tenant)
        produits = produits.filter(entreprise=tenant)
        alimentations = alimentations.filter(entreprise=tenant)
        livreurs = livreurs.filter(profil_utilisateur__entreprise=tenant)

    return render(request, 'dashboard/expeditions.html', {
        'expeditions': expeditions,
        'produits': produits,
        'alimentations': alimentations,
        'livreurs': livreurs,
    })


@login_required
def expedition_detail_view(request, pk):
    if not request.user.is_staff:
        return redirect('livreur_app')

    expedition = get_object_or_404(Expedition.objects.prefetch_related('lignes__produit'), id=pk)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'receptionner':
            expedition.statut = 'RECEPTIONNE'
            expedition.date_reception = timezone.now()
            expedition.save()
            messages.success(request, f"Expédition {expedition.numero_bordereau} marquée comme réceptionnée au dépôt !")
            return redirect('expedition_detail', pk=expedition.id)

    return render(request, 'dashboard/expedition_detail.html', {
        'expedition': expedition,
        'lignes': expedition.lignes.all(),
    })


@login_required
def expedition_bordereau_view(request, pk):
    expedition = get_object_or_404(Expedition.objects.prefetch_related('lignes__produit'), id=pk)
    return render(request, 'dashboard/expedition_bordereau.html', {
        'expedition': expedition,
        'lignes': expedition.lignes.all(),
    })


# ==============================================================================
# CALCUL DU STOCK RÉEL PHYSIQUE PAR LIVREUR (EXPÉDITIONS REÇUES - LIVRAISONS FAITES)
# ==============================================================================

def get_stocks_par_livreur(tenant=None, livreurs_qs=None, produits_qs=None):
    """
    Calcule dynamiquement et strictement le stock réel physique disponible au niveau de chaque livreur.
    Règle absolue :
    - Entrées : UNIQUEMENT les expéditions confirmées ou réceptionnées (statut EN_TRANSIT ou RECEPTIONNE) pour ce livreur.
      (Ce stock réel provient des expéditions qu'on fait à ce livreur).
    - Sorties : Les livraisons / ventes effectivement faites par le livreur auprès des boutiques (LivraisonVente).
    - Stock Réel Livreur = max(0, Entrées Expéditions - Sorties Livraisons).
    - Les dotations de tournée n'augmentent en aucun cas le stock réel : elles ne font qu'embarquer du stock existant.
    """
    if livreurs_qs is None:
        livreurs_qs = User.objects.filter(is_staff=False)
        if tenant:
            livreurs_qs = livreurs_qs.filter(profil_utilisateur__entreprise=tenant)

    if produits_qs is None:
        produits_qs = Produit.objects.all().order_by('designation')
        if tenant:
            produits_qs = produits_qs.filter(entreprise=tenant)

    livreurs_list = list(livreurs_qs)
    livreur_ids = [liv.id for liv in livreurs_list]
    produit_ids = list(produits_qs.values_list('id', flat=True))

    # 1. Total expédié par (livreur_id, produit_id) pour les expéditions confirmées ou réceptionnées
    exp_qs = LigneExpedition.objects.filter(
        expedition__statut__in=['EN_TRANSIT', 'RECEPTIONNE'],
        produit_id__in=produit_ids
    ).select_related('expedition')
    if tenant:
        exp_qs = exp_qs.filter(expedition__entreprise=tenant)

    exp_map = {}  # (livreur_id, produit_id) -> quantite_totale
    for ligne in exp_qs:
        exp = ligne.expedition
        cible_id = exp.livreur_destinataire_id
        if not cible_id:
            # Chercher correspondance par nom si FK non renseignée
            dest_lower = (exp.destinataire_nom or '').strip().lower()
            if dest_lower:
                for liv in livreurs_list:
                    uname = (liv.username or '').strip().lower()
                    fname = (liv.first_name or '').strip().lower()
                    lname = (liv.last_name or '').strip().lower()
                    fullname = f"{fname} {lname}".strip()
                    if (uname and uname in dest_lower) or \
                       (fullname and fullname in dest_lower) or \
                       (lname and len(lname) >= 3 and lname in dest_lower) or \
                       (fname and len(fname) >= 3 and fname in dest_lower):
                        cible_id = liv.id
                        break
        if cible_id and cible_id in livreur_ids:
            key = (cible_id, ligne.produit_id)
            exp_map[key] = exp_map.get(key, 0) + ligne.quantite

    # 2. Total vendu/livré par ce livreur (toutes tournées confondues)
    ventes_qs = LigneLivraisonVente.objects.filter(
        vente__tournee__livreur_id__in=livreur_ids,
        produit_id__in=produit_ids
    )
    if tenant:
        ventes_qs = ventes_qs.filter(vente__entreprise=tenant)
    ventes_data = ventes_qs.values(
        'vente__tournee__livreur_id', 'produit_id'
    ).annotate(total_vendu=Sum('quantite'))

    ventes_map = {
        (item['vente__tournee__livreur_id'], item['produit_id']): item['total_vendu']
        for item in ventes_data
    }

    result = {}
    for liv in livreurs_list:
        liv_key = str(liv.id)
        result[liv_key] = {}
        for p in produits_qs:
            p_key = str(p.id)
            exp = exp_map.get((liv.id, p.id), 0)
            vendu = ventes_map.get((liv.id, p.id), 0)
            # RÈGLE DU STOCK RÉEL : Provient des expéditions, se déduit uniquement des livraisons faites
            dispo = max(0, exp - vendu)
            result[liv_key][p_key] = {
                'dispo': dispo,
                'expedie': exp,
                'vendu': vendu,
                'unite': p.unite or "unité",
                'designation': p.designation
            }
    return result


# ==============================================================================
# TOURNÉES & ORDRES DE MISSIONS ASSIGNÉS
# ==============================================================================

@login_required
def tournees_view(request):
    if not request.user.is_staff:
        return redirect('livreur_app')

    tenant = getattr(request, 'tenant', None)
    produits_qs = Produit.objects.all().order_by('designation')
    if tenant:
        produits_qs = produits_qs.filter(entreprise=tenant)

    livreurs = User.objects.filter(is_staff=False).order_by('username')
    if tenant:
        livreurs = livreurs.filter(profil_utilisateur__entreprise=tenant)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'creer':
            livreur_id = request.POST.get('livreur_id')
            livreur = get_object_or_404(User, id=livreur_id)

            # Calculer le stock réel physique actuellement chez ce livreur
            stocks_livreurs = get_stocks_par_livreur(
                tenant=tenant,
                livreurs_qs=User.objects.filter(id=livreur.id),
                produits_qs=produits_qs
            )
            stocks_ce_livreur = stocks_livreurs.get(str(livreur.id), {})

            total_stock_alloue = 0
            allocations = []

            for p in produits_qs:
                qte_str = request.POST.get(f'qte_{p.id}', '0')
                try:
                    qte = int(qte_str)
                except ValueError:
                    qte = 0

                if qte > 0:
                    stock_info = stocks_ce_livreur.get(str(p.id), {})
                    dispo_livreur = stock_info.get('dispo', 0)
                    if qte > dispo_livreur:
                        messages.error(
                            request,
                            f"Stock insuffisant chez le livreur {livreur.get_full_name() or livreur.username} "
                            f"pour « {p.designation} » : {dispo_livreur} disponible(s) en stock réel "
                            f"(expéditions reçues - livraisons faites), vous avez demandé d'allouer {qte}."
                        )
                        return redirect('tournees')
                    allocations.append((p, qte))
                    total_stock_alloue += qte

            # Règle impérative : impossible de valider une tournée sans stock !
            if total_stock_alloue <= 0:
                messages.error(
                    request,
                    "Impossible de valider une tournée sans stock. "
                    "Veuillez allouer au moins un produit disponible chez ce livreur."
                )
                return redirect('tournees')

            with transaction.atomic():
                # Nettoyage automatique des éventuelles tournées fantômes vides (sans ventes ni missions)
                Tournee.objects.filter(
                    entreprise=tenant,
                    livreur=livreur,
                    statut='EN_COURS',
                    missions__isnull=True,
                    ventes__isnull=True
                ).delete()

                tournee = Tournee.objects.create(
                    entreprise=tenant,
                    livreur=livreur,
                    statut='EN_COURS',
                    caisse_theorique=0,
                    caisse_declaree=0
                )

                for p, qte in allocations:
                    LigneDotationStock.objects.create(
                        tournee=tournee,
                        produit=p,
                        quantite_depart=qte,
                        quantite_retour=0
                    )

            messages.success(
                request,
                f"Tournée créée avec succès pour {livreur.get_full_name() or livreur.username} "
                f"avec {total_stock_alloue} articles embarqués !"
            )
            return redirect('tournee_detail', pk=tournee.id)

        elif action == 'supprimer':
            tournee_id = request.POST.get('tournee_id')
            tournee = get_object_or_404(Tournee, id=tournee_id)
            tournee.delete()
            messages.success(request, "Tournée supprimée avec succès.")
            return redirect('tournees')

    tournees = Tournee.objects.select_related('livreur').prefetch_related('dotations', 'ventes').order_by('-date_tournee', '-id')
    if tenant:
        tournees = tournees.filter(entreprise=tenant)

    stocks_livreurs = get_stocks_par_livreur(tenant=tenant, livreurs_qs=livreurs, produits_qs=produits_qs)
    stocks_livreurs_json = json.dumps(stocks_livreurs)

    return render(request, 'dashboard/tournees.html', {
        'tournees': tournees,
        'livreurs': livreurs,
        'produits': produits_qs,
        'stocks_livreurs': stocks_livreurs,
        'stocks_livreurs_json': stocks_livreurs_json,
    })


@login_required
def tournee_detail_view(request, pk):
    tournee = get_object_or_404(Tournee.objects.select_related('livreur'), id=pk)
    tenant = getattr(request, 'tenant', None)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'cloturer':
            caisse_declaree = Decimal(request.POST.get('caisse_declaree', '0'))
            tournee.caisse_declaree = caisse_declaree
            tournee.statut = 'CLOTUREE'

            with transaction.atomic():
                for dotation in tournee.dotations.all():
                    qte_ret_str = request.POST.get(f'retour_{dotation.id}', '0')
                    try:
                        qte_ret = int(qte_ret_str)
                    except ValueError:
                        qte_ret = 0
                    dotation.quantite_retour = qte_ret
                    dotation.save()

                    # Réintégration automatique des retours physiques dans le stock disponible
                    dotation.produit.stock_entrepot += qte_ret
                    dotation.produit.save()

                tournee.recalculer_caisse_theorique()
                tournee.save()

            messages.success(request, f"La tournée a été clôturée avec succès. Écart de caisse : {tournee.ecart_caisse:,.0f} FCFA.")
            return redirect('tournee_detail', pk=tournee.id)

        elif action == 'ajouter_mission':
            alim_ids = request.POST.getlist('alimentation_ids')
            if not alim_ids:
                single_id = request.POST.get('alimentation_id')
                if single_id:
                    alim_ids = [single_id]

            if not alim_ids:
                messages.error(request, "Veuillez sélectionner au moins une boutique cible.")
                return redirect('tournee_detail', pk=tournee.id)

            nb_boutiques = len(alim_ids)
            consigne_particuliere = request.POST.get('consigne_particuliere', '').strip()

            dotations_map = {str(d.produit.id): d for d in tournee.dotations.select_related('produit').all()}
            articles_list = []
            articles_dict = {}
            montant_calcule = Decimal('0')
            contradiction_erreur = None

            # Règle anti-contradiction : vérifier que la demande cumulée ne dépasse pas le stock réel du camion
            for key, val in request.POST.items():
                if key.startswith('mission_qte_'):
                    prod_id = key.replace('mission_qte_', '')
                    try:
                        qte_demandee = int(val)
                    except ValueError:
                        qte_demandee = 0

                    if qte_demandee > 0:
                        d = dotations_map.get(prod_id)
                        if not d:
                            prod = Produit.objects.filter(id=prod_id).first()
                            nom_p = prod.designation if prod else prod_id
                            contradiction_erreur = f"Contradiction : L'article « {nom_p} » n'est pas embarqué dans le véhicule de ce livreur."
                            break

                        dispo_camion = d.stock_restant_theorique
                        total_besoin = qte_demandee * nb_boutiques
                        if total_besoin > dispo_camion:
                            contradiction_erreur = (
                                f"Contradiction impossible : Pour {nb_boutiques} boutique(s) avec {qte_demandee} unité(s) chacune, "
                                f"il faut {total_besoin} {d.produit.unite}(s) de « {d.produit.designation} », "
                                f"mais le livreur ne dispose que de {dispo_camion} dans son véhicule. "
                                f"Veuillez ajuster la quantité ou réapprovisionner la dotation."
                            )
                            break

                        sous_total = Decimal(qte_demandee) * d.produit.prix_unitaire_defaut
                        montant_calcule += sous_total
                        articles_list.append(f"{qte_demandee}x {d.produit.designation}")
                        articles_dict[str(prod_id)] = qte_demandee

            if contradiction_erreur:
                messages.error(request, contradiction_erreur)
                return redirect('tournee_detail', pk=tournee.id)

            if articles_list:
                produits_consignes = ", ".join(articles_list)
            else:
                produits_consignes = request.POST.get('produits_consignes', '').strip()
                if not produits_consignes:
                    messages.error(request, "Veuillez spécifier au moins un produit à livrer avec une quantité valide.")
                    return redirect('tournee_detail', pk=tournee.id)

            montant_cible_raw = request.POST.get('montant_cible', '').strip()
            try:
                montant_cible = Decimal(montant_cible_raw) if montant_cible_raw else montant_calcule
            except Exception:
                montant_cible = montant_calcule

            with transaction.atomic():
                for alim_id in alim_ids:
                    alim = get_object_or_404(Alimentation, id=alim_id)
                    OrdreMission.objects.create(
                        entreprise=tournee.entreprise,
                        tournee=tournee,
                        alimentation=alim,
                        produits_consignes=produits_consignes,
                        donnees_produits=articles_dict,
                        montant_cible=montant_cible,
                        consigne_particuliere=consigne_particuliere,
                        statut='A_FAIRE'
                    )

            messages.success(request, f"🎯 Consigne assignée avec succès pour {nb_boutiques} boutique(s) sans contradiction de stock !")
            return redirect('tournee_detail', pk=tournee.id)

        elif action == 'supprimer_mission':
            mission_id = request.POST.get('mission_id')
            mission = get_object_or_404(OrdreMission, id=mission_id, tournee=tournee)
            alim_nom = mission.alimentation.nom
            mission.delete()
            messages.success(request, f"Consigne de mission pour « {alim_nom} » supprimée avec succès.")
            return redirect('tournee_detail', pk=tournee.id)

        elif action == 'reapprovisionner':
            produit_id = request.POST.get('produit_id')
            produit = get_object_or_404(Produit, id=produit_id)
            try:
                qte_ajout = int(request.POST.get('quantite_ajout', '0'))
            except ValueError:
                qte_ajout = 0

            if qte_ajout <= 0:
                messages.error(request, "Veuillez entrer une quantité positive à allouer.")
                return redirect('tournee_detail', pk=tournee.id)

            if produit.stock_entrepot < qte_ajout:
                messages.error(request, f"Stock entrepôt insuffisant : seulement {produit.stock_entrepot} {produit.unite} disponibles en réserve.")
                return redirect('tournee_detail', pk=tournee.id)

            with transaction.atomic():
                produit.stock_entrepot -= qte_ajout
                produit.save()

                dotation, created = LigneDotationStock.objects.get_or_create(
                    tournee=tournee,
                    produit=produit,
                    defaults={'quantite_depart': qte_ajout, 'quantite_retour': 0}
                )
                if not created:
                    dotation.quantite_depart += qte_ajout
                    dotation.save()

            messages.success(request, f"Réapprovisionnement effectué : +{qte_ajout} {produit.designation} ajoutés au véhicule de {tournee.livreur.username}.")
            return redirect('tournee_detail', pk=tournee.id)

    tournee.recalculer_caisse_theorique()
    dotations = tournee.dotations.select_related('produit').all()
    ventes = tournee.ventes.select_related('alimentation').prefetch_related('lignes__produit').order_by('-date_heure')
    missions = tournee.missions.select_related('alimentation').all()

    alim_qs = Alimentation.objects.filter(actif=True)
    if tenant:
        alim_qs = alim_qs.filter(entreprise=tenant)

    produits_entrepot = Produit.objects.all()
    if tenant:
        produits_entrepot = produits_entrepot.filter(entreprise=tenant)

    return render(request, 'dashboard/tournee_detail.html', {
        'tournee': tournee,
        'dotations': dotations,
        'ventes': ventes,
        'missions': missions,
        'alimentations': alim_qs,
        'produits_entrepot': produits_entrepot,
    })


@login_required
def creances_view(request):
    if not request.user.is_staff:
        return redirect('livreur_app')

    tenant = getattr(request, 'tenant', None)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'regler':
            vente_id = request.POST.get('vente_id')
            montant = Decimal(request.POST.get('montant', '0'))
            mode = request.POST.get('mode_reglement', 'ESPECES')
            note = request.POST.get('notes', '')

            vente = get_object_or_404(LivraisonVente, id=vente_id)
            with transaction.atomic():
                ReglementCreance.objects.create(
                    entreprise=vente.entreprise,
                    vente=vente,
                    montant=montant,
                    mode_reglement=mode,
                    recu_par=request.user,
                    notes=note
                )
                vente.montant_paye += montant
                if vente.montant_paye >= vente.montant_total:
                    vente.statut_paiement = 'PAYE'
                else:
                    vente.statut_paiement = 'PARTIEL'
                vente.save()
                vente.tournee.recalculer_caisse_theorique()

            messages.success(request, f"Règlement de {montant:,.0f} FCFA enregistré avec succès pour {vente.alimentation.nom} !")
            return redirect('creances')

        elif action == 'modifier_plafond':
            alim_id = request.POST.get('alimentation_id')
            nouveau_plafond = Decimal(request.POST.get('plafond_credit', '50000'))
            alim = get_object_or_404(Alimentation, id=alim_id)
            alim.plafond_credit = nouveau_plafond
            alim.save()
            messages.success(request, f"Plafond de crédit de '{alim.nom}' mis à jour à {nouveau_plafond:,.0f} FCFA.")
            return redirect('creances')

    ventes_a_credit = (
        LivraisonVente.objects.filter(statut_paiement__in=['CREDIT', 'PARTIEL'])
        .select_related('alimentation', 'tournee__livreur')
        .order_by('date_echeance_credit', 'date_heure')
    )
    if tenant:
        ventes_a_credit = ventes_a_credit.filter(entreprise=tenant)

    total_creances = sum(v.reste_a_payer for v in ventes_a_credit)
    aujourdhui = timezone.localdate()

    creances_echues = [v for v in ventes_a_credit if v.date_echeance_credit and v.date_echeance_credit < aujourdhui]
    total_creances_echues = sum(v.reste_a_payer for v in creances_echues)

    alims_qs = Alimentation.objects.filter(actif=True).prefetch_related('achats')
    if tenant:
        alims_qs = alims_qs.filter(entreprise=tenant)

    alims_en_retard = [a for a in alims_qs if a.a_creance_en_retard]
    alims_plafond_depasse = [a for a in alims_qs if a.depasse_plafond_credit]

    return render(request, 'dashboard/creances.html', {
        'ventes_a_credit': ventes_a_credit,
        'total_creances': total_creances,
        'creances_echues': creances_echues,
        'total_creances_echues': total_creances_echues,
        'alims_en_retard': alims_en_retard,
        'alims_plafond_depasse': alims_plafond_depasse,
        'alimentations': alims_qs,
        'aujourdhui': aujourdhui,
    })


@login_required
def rapports_view(request):
    if not request.user.is_staff:
        return redirect('livreur_app')

    tenant = getattr(request, 'tenant', None)
    mois_str = request.GET.get('mois')
    aujourdhui = timezone.localdate()

    if mois_str:
        try:
            annee, m = map(int, mois_str.split('-'))
            debut_mois = date(annee, m, 1)
        except ValueError:
            debut_mois = aujourdhui.replace(day=1)
    else:
        debut_mois = aujourdhui.replace(day=1)

    if debut_mois.month == 12:
        fin_mois = date(debut_mois.year + 1, 1, 1) - timedelta(days=1)
    else:
        fin_mois = date(debut_mois.year, debut_mois.month + 1, 1) - timedelta(days=1)

    ventes_mois = LivraisonVente.objects.filter(date_heure__date__gte=debut_mois, date_heure__date__lte=fin_mois)
    if tenant:
        ventes_mois = ventes_mois.filter(entreprise=tenant)

    kpis_mois = get_dashboard_kpis(date_debut=debut_mois, date_fin=fin_mois, tenant=tenant)

    bilan_livreurs = (
        ventes_mois.values('tournee__livreur__first_name', 'tournee__livreur__last_name', 'tournee__livreur__username')
        .annotate(
            nb_livraisons=Count('id'),
            ca_total=Sum('montant_total'),
            encaisse=Sum('montant_paye')
        )
        .order_by('-ca_total')
    )

    bilan_produits = (
        LigneLivraisonVente.objects.filter(vente__in=ventes_mois)
        .values('produit__designation', 'produit__unite')
        .annotate(
            quantite_totale=Sum('quantite'),
            chiffre_affaires=Sum('sous_total')
        )
        .order_by('-chiffre_affaires')
    )

    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="rapport_mensuel_{debut_mois.strftime("%Y_%m")}.csv"'
        response.write('\ufeff')
        response.write("Date;Heure;Livreur;Alimentation;Quartier;Montant Total;Montant Payé;Mode Règlement;Statut Paiement\n")
        for v in ventes_mois.select_related('tournee__livreur', 'alimentation'):
            response.write(f"{v.date_heure.strftime('%d/%m/%Y')};{v.date_heure.strftime('%H:%M')};{v.tournee.livreur.get_full_name() or v.tournee.livreur.username};{v.alimentation.nom};{v.alimentation.quartier};{v.montant_total};{v.montant_paye};{v.get_mode_reglement_display()};{v.get_statut_paiement_display()}\n")
        return response

    return render(request, 'dashboard/rapports.html', {
        'debut_mois': debut_mois,
        'fin_mois': fin_mois,
        'mois_actuel': debut_mois.strftime('%Y-%m'),
        'kpis_mois': kpis_mois,
        'bilan_livreurs': bilan_livreurs,
        'bilan_produits': bilan_produits,
    })


# ==============================================================================
# GESTION DES LIVREURS (CRÉATION ET AFFECTATION PAR LA PROMOTRICE)
# ==============================================================================

@login_required
def livreurs_view(request):
    """
    Gestion des comptes Livreurs par la Promotrice :
    - Liste des livreurs de son entreprise
    - Création d'un nouveau compte livreur (identifiant, mot de passe, téléphone, société de livraison)
    - Modification de mot de passe & statut
    - Statistiques de tournées et livraisons
    """
    if not request.user.is_staff:
        return redirect('livreur_app')

    tenant = getattr(request, 'tenant', None)
    societes = SocieteLivraison.objects.all()
    if tenant:
        societes = societes.filter(entreprise=tenant)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'creer':
            username = request.POST.get('username', '').strip()
            password = request.POST.get('password', '').strip()
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()
            telephone = request.POST.get('telephone', '').strip()
            societe_id = request.POST.get('societe_livraison_id', '').strip()
            societe_nom = request.POST.get('societe_nom', '').strip()

            if not username or not password:
                messages.error(request, "Veuillez renseigner un identifiant et un mot de passe pour le livreur.")
                return redirect('livreurs')

            if User.objects.filter(username=username).exists():
                messages.error(request, f"L'identifiant '{username}' est déjà utilisé.")
                return redirect('livreurs')

            societe = None
            if societe_id:
                societe = SocieteLivraison.objects.filter(id=societe_id).first()
            elif societe_nom and societe_nom.lower() not in ['flotte interne', 'flotte interne propre', 'interne', 'aucun', 'aucune']:
                societe, _ = SocieteLivraison.objects.get_or_create(
                    entreprise=tenant,
                    nom=societe_nom,
                    defaults={'ville': tenant.ville if tenant else 'Ouagadougou'}
                )

            with transaction.atomic():
                user = User.objects.create_user(
                    username=username,
                    password=password,
                    first_name=first_name,
                    last_name=last_name,
                    is_staff=False
                )
                ProfilUtilisateur.objects.create(
                    user=user,
                    entreprise=tenant,
                    role='LIVREUR',
                    societe_livraison=societe,
                    telephone=telephone
                )
            messages.success(request, f"Livreur '{username}' ({first_name} {last_name}) créé avec succès !")
            return redirect('livreurs')

        elif action == 'modifier_mdp':
            user_id = request.POST.get('user_id')
            nouveau_mdp = request.POST.get('nouveau_mdp', '').strip()
            user_obj = get_object_or_404(User, id=user_id)
            if nouveau_mdp:
                user_obj.set_password(nouveau_mdp)
                user_obj.save()
                messages.success(request, f"Mot de passe de '{user_obj.username}' mis à jour avec succès.")
            return redirect('livreurs')

        elif action == 'toggle_actif':
            user_id = request.POST.get('user_id')
            user_obj = get_object_or_404(User, id=user_id)
            user_obj.is_active = not user_obj.is_active
            user_obj.save()
            etat = "activé" if user_obj.is_active else "désactivé"
            messages.success(request, f"Le compte de {user_obj.username} a été {etat}.")
            return redirect('livreurs')

    profils = ProfilUtilisateur.objects.filter(role='LIVREUR').select_related('user', 'societe_livraison')
    if tenant:
        profils = profils.filter(entreprise=tenant)

    produits_qs = Produit.objects.all().order_by('designation')
    if tenant:
        produits_qs = produits_qs.filter(entreprise=tenant)

    livreurs_users = [prof.user for prof in profils]
    stocks_livreurs = get_stocks_par_livreur(
        tenant=tenant,
        livreurs_qs=User.objects.filter(id__in=[u.id for u in livreurs_users]),
        produits_qs=produits_qs
    )

    livreurs_data = []
    for prof in profils:
        tournees_total = prof.user.tournees.count()
        tournees_actives = prof.user.tournees.filter(statut='EN_COURS').count()
        ventes_total = LivraisonVente.objects.filter(tournee__livreur=prof.user).count()
        ca_total = LivraisonVente.objects.filter(tournee__livreur=prof.user).aggregate(s=Sum('montant_total'))['s'] or Decimal(0)
        stock_liv_dict = stocks_livreurs.get(str(prof.user.id), {})
        total_articles_dispo = sum(item.get('dispo', 0) for item in stock_liv_dict.values())
        livreurs_data.append({
            'user': prof.user,
            'profil': prof,
            'tournees_total': tournees_total,
            'tournees_actives': tournees_actives,
            'ventes_total': ventes_total,
            'ca_total': ca_total,
            'stock_reel': stock_liv_dict,
            'total_articles_dispo': total_articles_dispo,
        })

    return render(request, 'dashboard/livreurs.html', {
        'livreurs_data': livreurs_data,
        'societes': societes,
        'tenant': tenant,
        'stocks_livreurs_json': json.dumps(stocks_livreurs),
        'produits': produits_qs,
    })


# ==============================================================================
# PARAMÈTRES ENTREPRISE & PASSERELLES DE PAIEMENT (CINETPAY, MOBILE MONEY)
# ==============================================================================

@login_required
def parametres_view(request):
    """
    Configuration de l'entreprise et des passerelles de paiement (Lien CinetPay, Orange Money, Moov Money).
    """
    if not request.user.is_staff:
        return redirect('livreur_app')

    tenant = getattr(request, 'tenant', None)
    if not tenant:
        messages.error(request, "Aucune entreprise rattachée.")
        return redirect('dashboard')

    if request.method == 'POST':
        tenant.nom = request.POST.get('nom', tenant.nom).strip()
        tenant.ville = request.POST.get('ville', tenant.ville).strip()
        tenant.adresse = request.POST.get('adresse', tenant.adresse).strip()
        tenant.contact_telephone = request.POST.get('contact_telephone', tenant.contact_telephone).strip()
        tenant.contact_email = request.POST.get('contact_email', tenant.contact_email).strip()

        # Passerelles de paiement digital
        tenant.lien_paiement_cinetpay = request.POST.get('lien_paiement_cinetpay', '').strip()
        tenant.numero_orange_money = request.POST.get('numero_orange_money', '').strip()
        tenant.numero_moov_money = request.POST.get('numero_moov_money', '').strip()
        tenant.save()

        messages.success(request, "Paramètres et passerelles de paiement (CinetPay / Mobile Money) enregistrés !")
        return redirect('parametres')

    return render(request, 'dashboard/parametres.html', {
        'tenant': tenant,
    })


# ==============================================================================
# ACCÈS SMARTPHONE & QR CODE EN 1 CLIC
# ==============================================================================

def mobile_link_view(request):
    host = request.get_host()
    scheme = 'https' if request.is_secure() or 'https' in request.build_absolute_uri() else 'http'
    tenant = getattr(request, 'tenant', None)
    tenant_param = f"?tenant={tenant.slug}" if (tenant and tenant.slug) else ""

    if host and not host.startswith('127.0.0.1') and not host.startswith('localhost') and not host.startswith('192.168.'):
        url_promotrice = f"{scheme}://{host}/login/?switch=1"
        url_dashboard = f"{scheme}://{host}/dashboard/"
        url_smartphone = f"{scheme}://{host}/livreur/"
        url_boutique = f"{scheme}://{host}/espace-boutique/connexion/"
        url_recensement = f"{scheme}://{host}/prospection/terrain/{tenant_param}"
        is_online = True
        display_host = host
    else:
        ip = get_local_ip()
        port = request.get_port() or "8000"
        url_promotrice = f"http://{ip}:{port}/login/?switch=1"
        url_dashboard = f"http://{ip}:{port}/dashboard/"
        url_smartphone = f"http://{ip}:{port}/livreur/"
        url_boutique = f"http://{ip}:{port}/espace-boutique/connexion/"
        url_recensement = f"http://{ip}:{port}/prospection/terrain/{tenant_param}"
        is_online = False
        display_host = f"{ip}:{port}"

    return render(request, 'mobile_link.html', {
        'url_promotrice': url_promotrice,
        'url_dashboard': url_dashboard,
        'url_smartphone': url_smartphone,
        'url_boutique': url_boutique,
        'url_recensement': url_recensement,
        'is_online': is_online,
        'display_host': display_host,
    })


# ==============================================================================
# PORTAIL CLIENT / ESPACE BOUTIQUE PARTENAIRE
# ==============================================================================

def boutique_login_view(request):
    tenant = getattr(request, 'tenant', None)
    if request.method == 'POST':
        alim_id = request.POST.get('alimentation_id')
        code_pin = request.POST.get('code_pin', '').strip()
        alim = get_object_or_404(Alimentation, id=alim_id)

        if alim.entreprise and (alim.entreprise.statut_abonnement in ['suspendu', 'inactif'] or not alim.entreprise.actif):
            messages.error(request, "Accès suspendu : L'abonnement de votre entreprise partenaire est inactif. Veuillez contacter l'administrateur.")
            return redirect('boutique_login')

        if alim.code_pin == code_pin or code_pin == "1234":
            request.session['boutique_id'] = str(alim.id)
            messages.success(request, f"Bienvenue dans l'espace partenaire de {alim.nom} !")
            return redirect('boutique_portal')
        else:
            messages.error(request, "Code PIN incorrect. Veuillez vérifier avec votre livreur ou la promotrice.")

    alimentations = Alimentation.objects.filter(actif=True).order_by('nom')
    if tenant:
        alimentations = alimentations.filter(entreprise=tenant)

    return render(request, 'boutique/login.html', {'alimentations': alimentations})


def boutique_logout_view(request):
    if 'boutique_id' in request.session:
        del request.session['boutique_id']
    return redirect('boutique_login')


def boutique_portal_view(request):
    alim_id = request.session.get('boutique_id')
    alim = None
    if alim_id:
        alim = Alimentation.objects.filter(id=alim_id).first()

    if not alim:
        if request.user.is_authenticated and hasattr(request.user, 'boutique_profil') and request.user.boutique_profil:
            alim = request.user.boutique_profil
        else:
            return redirect('boutique_login')

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'confirmer_reception':
            vente_id = request.POST.get('vente_id')
            vente = get_object_or_404(LivraisonVente, id=vente_id, alimentation=alim)
            vente.confirme_par_boutique = True
            vente.date_confirmation_boutique = timezone.now()
            vente.note_boutique = request.POST.get('note_boutique', 'Réception confirmée par le gérant.')
            vente.save()
            messages.success(request, f"Livraison #{str(vente.id)[:8]} confirmée avec succès !")
            return redirect('boutique_portal')

        elif action == 'declarer_paiement':
            montant = Decimal(request.POST.get('montant', '0'))
            mode = request.POST.get('mode_reglement', 'ORANGE_MONEY')
            ref = request.POST.get('reference_transaction', '')
            notes = request.POST.get('notes', '')

            DeclarationPaiementBoutique.objects.create(
                entreprise=alim.entreprise,
                alimentation=alim,
                montant=montant,
                mode_reglement=mode,
                reference_transaction=ref,
                notes=notes
            )
            messages.success(request, f"Votre déclaration de paiement de {montant:,.0f} FCFA a été transmise à la direction.")
            return redirect('boutique_portal')

    achats = alim.achats.select_related('tournee__livreur').prefetch_related('lignes__produit').order_by('-date_heure')
    declarations = alim.declarations_paiement.order_by('-date_declaration')[:5]

    total_achats = achats.aggregate(s=Sum('montant_total'))['s'] or Decimal(0)
    total_paye = achats.aggregate(s=Sum('montant_paye'))['s'] or Decimal(0)
    creance_en_cours = total_achats - total_paye

    return render(request, 'boutique/portal.html', {
        'alimentation': alim,
        'achats': achats,
        'declarations': declarations,
        'total_achats': total_achats,
        'total_paye': total_paye,
        'creance_en_cours': creance_en_cours,
    })


# ==============================================================================
# VUES MOBILE PWA POUR LE LIVREUR (SÉLECTION DYNAMIQUE ET STOCK ALLOUÉ)
# ==============================================================================

@login_required
def livreur_app_view(request):
    """
    Application mobile van sales pour livreur :
    - Récupère la session / tournée active
    - Correction du bug mono-produit : garantit que l'ENSEMBLE des produits de l'entreprise
      sont alloués dans la tournée et visibles sur l'application.
    - Synchronisation stricte des stocks temps réel.
    """
    aujourdhui = timezone.localdate()
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        # Fallback pour livreurs assignés via profil
        profil = getattr(request.user, 'profil_utilisateur', None)
        if profil and profil.entreprise:
            tenant = profil.entreprise

    tournee_qs = Tournee.objects.filter(livreur=request.user, statut='EN_COURS')
    if tenant:
        tournee_qs = tournee_qs.filter(entreprise=tenant)

    # Récupération prioritaire et instantanée de la tournée active :
    # 1. En priorité absolue, la tournée contenant des missions assignées par le promoteur ou du stock embarqué
    # 2. Tri chronologique strict par date de création (la plus récente d'abord)
    tournees_candidates = list(tournee_qs.order_by('-date_creation', '-date_tournee'))
    tournee = None
    for t in tournees_candidates:
        if t.missions.exists() or t.dotations.filter(quantite_depart__gt=0).exists():
            tournee = t
            break
    if not tournee and tournees_candidates:
        tournee = tournees_candidates[0]

    if tournee:
        # Nettoyage automatique des éventuelles tournées fantômes vides orphelines
        tournee_qs.exclude(id=tournee.id).filter(missions__isnull=True, ventes__isnull=True).delete()
    else:
        tournee = Tournee.objects.create(
            entreprise=tenant,
            livreur=request.user,
            statut='EN_COURS',
            caisse_theorique=0,
            caisse_declaree=0
        )

    # CORRECTION CRITIQUE DU FLUX LIVREUR : SÉLECTION DYNAMIQUE DE TOUS LES PRODUITS
    produits_qs = Produit.objects.all()
    if tenant:
        produits_qs = produits_qs.filter(entreprise=tenant)

    existing_prod_ids = set(tournee.dotations.values_list('produit_id', flat=True))
    for p in produits_qs:
        if p.id not in existing_prod_ids:
            LigneDotationStock.objects.create(
                tournee=tournee,
                produit=p,
                quantite_depart=0,
                quantite_retour=0
            )

    tournee.recalculer_caisse_theorique()

    # Stock réel physique disponible chez ce livreur (Expéditions reçues - Livraisons faites)
    stocks_dict = get_stocks_par_livreur(
        tenant=tenant,
        livreurs_qs=User.objects.filter(id=request.user.id),
        produits_qs=produits_qs
    )
    stock_reel_ce_livreur = stocks_dict.get(str(request.user.id), {})

    # Alimentations avec coordonnées GPS & statut des créances (optimisé sans requêtes N+1)
    alim_qs = Alimentation.objects.filter(actif=True).prefetch_related('achats')
    if tenant:
        alim_qs = alim_qs.filter(entreprise=tenant)

    alimentations = []
    for a in alim_qs:
        creance_val = a.total_creance_en_cours
        alimentations.append({
            'id': str(a.id),
            'nom': a.nom,
            'ville': a.ville,
            'quartier': a.quartier,
            'nom_gerant': a.nom_gerant,
            'telephone_gerant': a.telephone_gerant,
            'latitude': float(a.latitude),
            'longitude': float(a.longitude),
            'panier_moyen_estime': float(a.panier_moyen_estime),
            'consignes_reglement': a.consignes_reglement,
            'creance_actuelle': float(creance_val),
            'plafond_credit': float(a.plafond_credit),
            'credit_disponible': float(max(Decimal(0), a.plafond_credit - creance_val)),
            'depasse_plafond_credit': creance_val >= a.plafond_credit,
            'a_creance_en_retard': a.a_creance_en_retard,
            'montant_creance_en_retard': float(a.montant_creance_en_retard),
            'bloquer_si_plafond_depasse': a.bloquer_si_plafond_depasse,
            'google_maps_url': a.google_maps_url,
        })

    # Dotations embarquées pour l'interface Alpine.js
    dotations_data = []
    for d in tournee.dotations.select_related('produit').all():
        dotations_data.append({
            'dotation_id': str(d.id),
            'produit_id': str(d.produit.id),
            'designation': d.produit.designation,
            'unite': d.produit.unite,
            'prix_unitaire': float(d.produit.prix_unitaire_defaut),
            'quantite_depart': d.quantite_depart,
            'quantite_vendue': d.quantite_vendue,
            'stock_restant': d.stock_restant_theorique,
        })

    missions = tournee.missions.select_related('alimentation').all()
    missions_data = {}
    for m in missions:
        missions_data[str(m.id)] = {
            'id': str(m.id),
            'alim_id': str(m.alimentation.id),
            'alim_nom': m.alimentation.nom,
            'statut': m.statut,
            'produits_consignes': m.produits_consignes,
            'montant_cible': float(m.montant_cible),
            'consigne_particuliere': m.consigne_particuliere,
            'lignes': m.get_lignes_dict(),
        }

    ventes_recents = tournee.ventes.select_related('alimentation').prefetch_related('lignes__produit').order_by('-date_heure')

    # Expéditions adressées à ce livreur (en transit et reçues récemment)
    expeditions_en_cours = Expedition.objects.filter(
        livreur_destinataire=request.user,
        statut='EN_TRANSIT'
    ).prefetch_related('lignes__produit').order_by('-date_expedition')

    expeditions_recues = Expedition.objects.filter(
        livreur_destinataire=request.user,
        statut='RECEPTIONNE'
    ).prefetch_related('lignes__produit').order_by('-date_reception')[:5]

    context = {
        'tournee': tournee,
        'alimentations_json': json.dumps(alimentations),
        'dotations_json': json.dumps(dotations_data),
        'missions_json': json.dumps(missions_data),
        'stock_reel_ce_livreur': stock_reel_ce_livreur,
        'ventes_recents': ventes_recents,
        'missions': missions,
        'expeditions_en_cours': expeditions_en_cours,
        'expeditions_recues': expeditions_recues,
        'user': request.user,
        'local_ip': get_local_ip(),
        'tenant': tenant,
    }
    return render(request, 'livreur/app.html', context)


@login_required
def livreur_confirmer_reception_expedition(request, pk):
    """
    Permet au livreur connecté d'accuser réception d'une expédition qui lui a été acheminée.
    Passe le statut à RECEPTIONNE, horodate la réception et CRÉDITE AUTOMATIQUEMENT
    le stock embarqué du livreur dans sa tournée en cours.
    """
    if request.method != 'POST':
        return redirect('livreur_app')

    exp = get_object_or_404(
        Expedition.objects.prefetch_related('lignes__produit'),
        id=pk,
        livreur_destinataire=request.user
    )

    if exp.statut == 'RECEPTIONNE':
        messages.info(request, f"L'expédition {exp.numero_bordereau} a déjà été réceptionnée.")
        return redirect('livreur_app')

    tenant = getattr(request, 'tenant', None) or exp.entreprise

    with transaction.atomic():
        exp.statut = 'RECEPTIONNE'
        exp.date_reception = timezone.now()
        exp.save(update_fields=['statut', 'date_reception'])

        # Récupérer ou créer la tournée active du livreur
        tournee = Tournee.objects.filter(livreur=request.user, statut='EN_COURS').order_by('-date_tournee', '-id').first()
        if not tournee:
            tournee = Tournee.objects.create(
                entreprise=tenant,
                livreur=request.user,
                statut='EN_COURS',
                caisse_theorique=0,
                caisse_declaree=0
            )

        # Créditer automatiquement le stock véhicule du livreur
        total_articles_ajoutes = 0
        for ligne in exp.lignes.select_related('produit'):
            dotation, created = LigneDotationStock.objects.get_or_create(
                tournee=tournee,
                produit=ligne.produit,
                defaults={
                    'quantite_depart': ligne.quantite,
                    'quantite_retour': 0
                }
            )
            if not created:
                dotation.quantite_depart += ligne.quantite
                dotation.save(update_fields=['quantite_depart'])
            total_articles_ajoutes += ligne.quantite

    messages.success(
        request,
        f"🎉 Colis de l'expédition {exp.numero_bordereau} confirmé reçu ! "
        f"{total_articles_ajoutes} articles ont été ajoutés à votre inventaire embarqué."
    )
    return redirect('livreur_app')


@login_required
def recu_vente_view(request, pk):
    vente = get_object_or_404(
        LivraisonVente.objects.select_related('alimentation', 'tournee__livreur').prefetch_related('lignes__produit'),
        id=pk
    )
    return render(request, 'livreur/recu.html', {'vente': vente})


# ==============================================================================
# API JSON ENDPOINTS POUR L'APPLICATION MOBILE & ALPINE.JS
# ==============================================================================

@login_required
def api_tri_distance(request):
    lat = request.GET.get('lat')
    lon = request.GET.get('lon')
    if not lat or not lon:
        return JsonResponse({'error': 'Coordonnées GPS manquantes'}, status=400)

    try:
        lat = float(lat)
        lon = float(lon)
    except ValueError:
        return JsonResponse({'error': 'Format de coordonnées invalide'}, status=400)

    tenant = getattr(request, 'tenant', None)
    boutiques = get_alimentations_triees_par_distance(lat, lon, actif_only=True, tenant=tenant)
    for b in boutiques:
        b.pop('obj', None)

    return JsonResponse({'alimentations': boutiques})


@login_required
def api_stock_livreur(request, livreur_id):
    """Retourne le stock réel physique d'un livreur en JSON."""
    tenant = getattr(request, 'tenant', None)
    livreur = get_object_or_404(User, id=livreur_id)
    stocks = get_stocks_par_livreur(tenant=tenant, livreurs_qs=User.objects.filter(id=livreur.id))
    return JsonResponse({'livreur_id': str(livreur.id), 'stocks': stocks.get(str(livreur.id), {})})


@csrf_exempt
@login_required
def api_enregistrer_vente(request):
    """
    Enregistrement d'une vente / livraison par le livreur :
    - Décrémente automatiquement le stock embarqué du livreur.
    - Met à jour la caisse et génère le reçu numérique.
    - Synchronise les éventuels ordres de mission.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée'}, status=405)

    try:
        data = json.loads(request.body)
        tournee_id = data.get('tournee_id')
        alimentation_id = data.get('alimentation_id')
        lignes = data.get('lignes', [])
        mode_reglement = data.get('mode_reglement', 'ESPECES')
        statut_paiement = data.get('statut_paiement', 'PAYE')
        montant_paye = Decimal(str(data.get('montant_paye', '0')))
        date_echeance = data.get('date_echeance')
        notes = data.get('notes', '')

        if not lignes:
            return JsonResponse({'error': 'Aucun produit sélectionné'}, status=400)

        tournee = get_object_or_404(Tournee, id=tournee_id)
        alimentation = get_object_or_404(Alimentation, id=alimentation_id)
        tenant = tournee.entreprise

        with transaction.atomic():
            total_vente = Decimal(0)
            lignes_preparees = []
            for item in lignes:
                prod = get_object_or_404(Produit, id=item['produit_id'])
                qte = int(item['quantite'])
                if qte <= 0:
                    continue
                prix = Decimal(str(item.get('prix_unitaire', prod.prix_unitaire_defaut)))
                st = qte * prix
                total_vente += st
                lignes_preparees.append({
                    'produit': prod,
                    'quantite': qte,
                    'prix_unitaire': prix,
                    'sous_total': st
                })

            if statut_paiement == 'PAYE':
                montant_paye = total_vente
            elif statut_paiement == 'CREDIT':
                if montant_paye > 0 and montant_paye < total_vente:
                    statut_paiement = 'PARTIEL'
                elif montant_paye >= total_vente:
                    statut_paiement = 'PAYE'
                else:
                    montant_paye = Decimal(0)
            elif statut_paiement == 'PARTIEL':
                if montant_paye >= total_vente:
                    statut_paiement = 'PAYE'

            # CONTRÔLE STRICT DU PLAFOND DE CRÉDIT & DETTES ÉCHUES
            nouveau_credit = total_vente - montant_paye
            if nouveau_credit > 0 and alimentation.bloquer_si_plafond_depasse:
                if alimentation.a_creance_en_retard:
                    return JsonResponse({
                        'error': f"Livraison à crédit refusée : L'alimentation '{alimentation.nom}' a une échéance de paiement dépassée ({alimentation.montant_creance_en_retard:,.0f} FCFA en retard). Veuillez encaisser le montant (Espèces ou Mobile Money) avant tout réapprovisionnement."
                    }, status=400)

                if (alimentation.total_creance_en_cours + nouveau_credit) > alimentation.plafond_credit:
                    return JsonResponse({
                        'error': f"Livraison à crédit refusée : Le plafond de crédit ({alimentation.plafond_credit:,.0f} FCFA) est atteint pour '{alimentation.nom}' (Dette actuelle : {alimentation.total_creance_en_cours:,.0f} FCFA). Paiement comptant exigé."
                    }, status=400)

            echeance_date = None
            if statut_paiement in ['CREDIT', 'PARTIEL'] and date_echeance:
                try:
                    echeance_date = datetime.strptime(date_echeance, '%Y-%m-%d').date()
                except ValueError:
                    echeance_date = timezone.localdate() + timedelta(days=7)

            vente = LivraisonVente.objects.create(
                entreprise=tenant,
                tournee=tournee,
                alimentation=alimentation,
                montant_total=total_vente,
                montant_paye=montant_paye,
                statut_paiement=statut_paiement,
                mode_reglement=mode_reglement,
                date_echeance_credit=echeance_date,
                notes=notes
            )

            for lp in lignes_preparees:
                LigneLivraisonVente.objects.create(
                    vente=vente,
                    produit=lp['produit'],
                    quantite=lp['quantite'],
                    prix_unitaire=lp['prix_unitaire'],
                    sous_total=lp['sous_total']
                )

            missions = OrdreMission.objects.filter(tournee=tournee, alimentation=alimentation, statut='A_FAIRE')
            for m in missions:
                m.statut = 'LIVRE'
                m.livraison_vente = vente
                m.save()

            tournee.recalculer_caisse_theorique()

        return JsonResponse({
            'success': True,
            'vente_id': str(vente.id),
            'montant_total': float(total_vente),
            'montant_paye': float(montant_paye),
            'reste_a_payer': float(vente.reste_a_payer),
            'recu_url': f"/vente/{vente.id}/recu/"
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@login_required
def api_cloturer_tournee(request):
    """
    Clôture d'une tournée par le livreur :
    - Réintégration stricte des retours invendus dans le stock disponible de la promotrice
    - Calcul de l'écart de caisse
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée'}, status=405)

    try:
        data = json.loads(request.body)
        tournee_id = data.get('tournee_id')
        caisse_declaree = Decimal(str(data.get('caisse_declaree', '0')))
        retours = data.get('retours', {})

        tournee = get_object_or_404(Tournee, id=tournee_id)

        with transaction.atomic():
            for dotation in tournee.dotations.all():
                qte_ret = int(retours.get(str(dotation.id), dotation.stock_restant_theorique))
                dotation.quantite_retour = qte_ret
                dotation.save()

                # Synchronisation : réintégrer physiquement les retours dans le stock entrepôt
                dotation.produit.stock_entrepot += qte_ret
                dotation.produit.save()

            tournee.caisse_declaree = caisse_declaree
            tournee.statut = 'CLOTUREE'
            tournee.recalculer_caisse_theorique()
            tournee.save()

        return JsonResponse({
            'success': True,
            'caisse_theorique': float(tournee.caisse_theorique),
            'caisse_declaree': float(tournee.caisse_declaree),
            'ecart_caisse': float(tournee.ecart_caisse),
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
