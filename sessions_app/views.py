from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsProviderRole, IsUserRole

from . import services
from .serializers import AssignSerializer, SessionSerializer


def _ok(session, status=200):
    return Response(SessionSerializer(session).data, status=status)


class SessionCreateView(APIView):
    permission_classes = [IsUserRole]

    def post(self, request):
        return _ok(services.create_session(request.user), status=201)


class SessionDetailView(APIView):
    def get(self, request, pk):
        return _ok(services.get_session(pk, request.user))


class AssignView(APIView):
    permission_classes = [IsUserRole]

    def post(self, request, pk):
        serializer = AssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return _ok(services.assign(pk, request.user, serializer.validated_data["provider_id"]))


class AcceptView(APIView):
    permission_classes = [IsProviderRole]

    def post(self, request, pk):
        return _ok(services.accept(pk, request.user))


class StartView(APIView):
    permission_classes = [IsUserRole]

    def post(self, request, pk):
        return _ok(services.start(pk, request.user))


class EndView(APIView):
    def post(self, request, pk):
        return _ok(services.end(pk, request.user))


class CancelView(APIView):
    def post(self, request, pk):
        return _ok(services.cancel(pk, request.user))


class BillView(APIView):
    def post(self, request, pk):
        services.get_session(pk, request.user)  # participants only
        return _ok(services.bill_session(pk))
