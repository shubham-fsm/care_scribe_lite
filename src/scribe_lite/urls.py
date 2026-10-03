from django.urls import path

from scribe_lite.views import ScribeFillView

urlpatterns = [
    path("fill/", ScribeFillView.as_view(), name="scribe-lite-fill"),
]
