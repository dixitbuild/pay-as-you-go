from rest_framework.permissions import BasePermission

from .models import User


class HasRole(BasePermission):
    required_role = None

    def has_permission(self, request, view):
        # Anonymous users must get 401, so let authentication fail first.
        user = request.user
        return bool(user and user.is_authenticated and user.role == self.required_role)


class IsUserRole(HasRole):
    message = "Only users can do this."
    required_role = User.Role.USER


class IsProviderRole(HasRole):
    message = "Only providers can do this."
    required_role = User.Role.PROVIDER
