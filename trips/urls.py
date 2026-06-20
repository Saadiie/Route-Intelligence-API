"""URL routing for the trips app."""

from django.urls import path

from trips.views import TripPlanView

app_name = "trips"

urlpatterns = [
    path("trips/", TripPlanView.as_view(), name="plan-trip"),
]
