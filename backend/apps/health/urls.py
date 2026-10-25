from django.urls import path

from apps.health.views import LivenessView

urlpatterns = [
    path("live/", LivenessView.as_view(), name="health-live"),
]
