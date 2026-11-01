from django.core.management.base import BaseCommand

from sessions_app import services
from sessions_app.models import Session


class Command(BaseCommand):
    help = "Bill every in-progress session. Run it periodically (for example every minute from cron)."

    def handle(self, *args, **options):
        ids = list(Session.objects.filter(status=Session.Status.IN_PROGRESS).values_list("pk", flat=True))
        for session_id in ids:
            session = services.bill_session(session_id)
            self.stdout.write(f"session {session.pk}: {session.status}, billed {session.billed_minutes} min")
        self.stdout.write(self.style.SUCCESS(f"Checked {len(ids)} session(s)."))
