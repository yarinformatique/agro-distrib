from django.shortcuts import render
from django.http import JsonResponse
from django.urls import reverse
from .models import ProfilUtilisateur, Entreprise


class TenantSecurityMiddleware:
    """
    Middleware d'architecture Multi-Tenant SaaS :
    1. Détermine le Tenant (Entreprise) et le rôle de l'utilisateur connecté.
    2. Règle stricte de suspension en cascade :
       Si l'entreprise a un statut_abonnement = 'suspendu' ou 'inactif' (ou actif=False),
       bloque immédiatement l'accès et les appels API pour TOUS les utilisateurs
       rattachés à cette entreprise (Promotrice, Livreurs, Boutiques).
       Message bloquant : "Accès suspendu : L'abonnement de votre entreprise est inactif. Veuillez contacter l'administrateur."
    3. Permet aux autres entreprises actives de fonctionner sans aucune interruption.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Court-circuit immédiat (0 requête DB) pour les sondes anti-veille
        if request.path in ('/healthz', '/healthz/', '/ping', '/ping/'):
            return self.get_response(request)

        request.tenant = None
        request.is_superadmin = False
        request.user_role = None

        if request.user.is_authenticated:
            profil = getattr(request.user, 'profil_utilisateur', None)

            # Rôle Superadmin (Créateur / Propriétaire de la plateforme)
            if request.user.is_superuser or (profil and profil.role == 'SUPERADMIN'):
                request.is_superadmin = True
                request.user_role = 'SUPERADMIN'
                request.tenant = None
            else:
                tenant = None
                role = None

                if profil:
                    tenant = profil.entreprise
                    role = profil.role
                elif hasattr(request.user, 'boutique_profil') and request.user.boutique_profil:
                    tenant = request.user.boutique_profil.entreprise
                    role = 'BOUTIQUE'

                request.tenant = tenant
                request.user_role = role

                # Règle de suspension en cascade (utilisateurs connectés)
                if tenant and (tenant.statut_abonnement in ['suspendu', 'inactif'] or not tenant.actif):
                    current_path = request.path
                    allowed_prefixes = [
                        reverse('logout'),
                        reverse('login'),
                        '/login/',
                        '/compte-suspendu/',
                        '/static/',
                        '/favicon.ico',
                    ]

                    if not any(current_path.startswith(p) for p in allowed_prefixes):
                        message_suspension = "Accès suspendu : L'abonnement de votre entreprise est inactif. Veuillez contacter l'administrateur."

                        is_api_request = (
                            current_path.startswith('/api/') or
                            request.headers.get('x-requested-with') == 'XMLHttpRequest' or
                            'application/json' in request.headers.get('accept', '') or
                            request.content_type == 'application/json'
                        )

                        if is_api_request:
                            return JsonResponse({
                                'error': message_suspension,
                                'suspended': True
                            }, status=403)

                        return render(request, 'suspended.html', {
                            'entreprise': tenant,
                            'message': message_suspension
                        }, status=403)

        # Règle de suspension en cascade pour les sessions Boutiques ouvertes par code PIN
        elif 'boutique_id' in request.session:
            from .models import Alimentation
            alim = Alimentation.objects.filter(id=request.session['boutique_id']).select_related('entreprise').first()
            if alim and alim.entreprise:
                request.tenant = alim.entreprise
                request.user_role = 'BOUTIQUE'
                if alim.entreprise.statut_abonnement in ['suspendu', 'inactif'] or not alim.entreprise.actif:
                    current_path = request.path
                    allowed_prefixes = [
                        reverse('boutique_logout'),
                        '/compte-suspendu/',
                        '/static/',
                        '/favicon.ico',
                    ]
                    if not any(current_path.startswith(p) for p in allowed_prefixes):
                        message_suspension = "Accès suspendu : L'abonnement de votre entreprise partenaire est inactif. Veuillez contacter l'administrateur."
                        return render(request, 'suspended.html', {
                            'entreprise': alim.entreprise,
                            'message': message_suspension
                        }, status=403)

        response = self.get_response(request)
        return response
