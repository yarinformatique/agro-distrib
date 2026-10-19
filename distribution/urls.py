from django.urls import path
from . import views

urlpatterns = [
    # Anti-mise en veille & Healthcheck ultra-léger (0 requête SQL)
    path('healthz', views.healthz_view, name='healthz_no_slash'),
    path('healthz/', views.healthz_view, name='healthz'),
    path('ping', views.healthz_view, name='ping_no_slash'),
    path('ping/', views.healthz_view, name='ping'),

    # Auth & redirection
    path('', views.home_redirect_view, name='home'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('compte-suspendu/', views.compte_suspendu_view, name='compte_suspendu'),

    # Superadmin SaaS (Plateforme globale)
    path('superadmin/', views.superadmin_dashboard_view, name='superadmin_dashboard'),
    path('superadmin/entreprises/creer/', views.superadmin_creer_entreprise_view, name='superadmin_creer_entreprise'),
    path('superadmin/entreprises/<uuid:pk>/toggle/', views.superadmin_toggle_statut_view, name='superadmin_toggle_statut'),
    path('superadmin/entreprises/<uuid:pk>/modifier/', views.superadmin_modifier_entreprise_view, name='superadmin_modifier_entreprise'),

    # Promotrice Dashboard (Tenant)
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('produits/', views.produits_view, name='produits'),
    path('alimentations/', views.alimentations_view, name='alimentations'),
    path('prospection/', views.prospection_view, name='prospection'),
    path('prospection/terrain/', views.prospection_terrain_view, name='prospection_terrain'),
    path('tournees/', views.tournees_view, name='tournees'),
    path('tournees/<uuid:pk>/', views.tournee_detail_view, name='tournee_detail'),
    path('creances/', views.creances_view, name='creances'),
    path('rapports/', views.rapports_view, name='rapports'),
    path('livreurs/', views.livreurs_view, name='livreurs'),
    path('parametres/', views.parametres_view, name='parametres'),

    # Expéditions Inter-Villes & Sociétés de Livraison (PDG / Promotrice)
    path('expeditions/', views.expeditions_view, name='expeditions'),
    path('expeditions/<uuid:pk>/', views.expedition_detail_view, name='expedition_detail'),
    path('expeditions/<uuid:pk>/bordereau/', views.expedition_bordereau_view, name='expedition_bordereau'),

    # Accès Smartphone & QR Code en 1 Clic
    path('mobile-link/', views.mobile_link_view, name='mobile_link'),

    # Espace Dédié Boutique Partenaire (Validation contradictoire anti-litige)
    path('espace-boutique/connexion/', views.boutique_login_view, name='boutique_login'),
    path('espace-boutique/deconnexion/', views.boutique_logout_view, name='boutique_logout'),
    path('espace-boutique/', views.boutique_portal_view, name='boutique_portal'),

    # Mobile-First Livreur PWA
    path('livreur/', views.livreur_app_view, name='livreur_app'),
    path('livreur/expeditions/<uuid:pk>/confirmer/', views.livreur_confirmer_reception_expedition, name='livreur_confirmer_reception_expedition'),
    path('vente/<uuid:pk>/recu/', views.recu_vente_view, name='recu_vente'),

    # API Endpoints pour Alpine.js / AJAX
    path('api/tri-distance/', views.api_tri_distance, name='api_tri_distance'),
    path('api/ventes/creer/', views.api_enregistrer_vente, name='api_enregistrer_vente'),
    path('api/tournees/cloturer/', views.api_cloturer_tournee, name='api_cloturer_tournee'),
]
