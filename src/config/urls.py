from django.urls import include, path

handler404 = "gateway.errors.nao_encontrada"
handler500 = "gateway.errors.erro_interno"

urlpatterns = [
    path("", include("gateway.urls")),
]
