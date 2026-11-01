from rest_framework.permissions import BasePermission

from .models import User


class IsUserRole(BasePermission):
    message = "Only users can do this."

    def has_permission(self, request, view):
        return request.user.role == User.Role.USER


class IsProviderRole(BasePermission):
    message = "Only providers can do this."

    def has_permission(self, request, view):
        return request.user.role == User.Role.PROVIDER
