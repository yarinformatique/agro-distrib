def tenant_context(request):
    """
    Expose le tenant courant (entreprise), les permissions superadmin
    et le rôle de l'utilisateur directement aux templates Django.
    """
    return {
        'current_tenant': getattr(request, 'tenant', None),
        'is_superadmin': getattr(request, 'is_superadmin', False),
        'user_role': getattr(request, 'user_role', None),
    }
