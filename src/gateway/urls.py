from django.urls import path

from . import views

urlpatterns = [
    path("healthz", views.healthz),
    path("v1/messages", views.Mensagens.as_view()),
    path("v1/messages/<uuid:pk>", views.MensagemDetalhe.as_view()),
    path("v1/status", views.Status.as_view()),
]
