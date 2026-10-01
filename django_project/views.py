from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .monitor import telemetry


def dashboard(request):
    return render(request, "dashboard.html")


@require_GET
def metrics(request):
    window = request.GET.get("window", "15m")
    return JsonResponse(telemetry.snapshot(window))