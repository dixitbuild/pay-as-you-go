from django.urls import path

from . import views

urlpatterns = [
    path("", views.SessionCreateView.as_view()),
    path("<int:pk>/", views.SessionDetailView.as_view()),
    path("<int:pk>/assign/", views.AssignView.as_view()),
    path("<int:pk>/accept/", views.AcceptView.as_view()),
    path("<int:pk>/start/", views.StartView.as_view()),
    path("<int:pk>/end/", views.EndView.as_view()),
    path("<int:pk>/bill/", views.BillView.as_view()),
    path("<int:pk>/cancel/", views.CancelView.as_view()),
]
