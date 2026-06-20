from django.contrib import admin
from routing.models import Route


@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    list_display = ("start_location", "destination_location", "distance_miles", "duration_minutes", "created_at")
    readonly_fields = ("created_at",)
