from django.urls import path

from apps.accounts.views import EmailTokenObtainPairView, EmailTokenRefreshView

urlpatterns = [
    path("token/", EmailTokenObtainPairView.as_view(), name="token-obtain"),
    path("token/refresh/", EmailTokenRefreshView.as_view(), name="token-refresh"),
]
