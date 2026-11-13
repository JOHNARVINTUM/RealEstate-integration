import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from django.conf import settings
from django.utils import timezone


def refresh_delivery_status(supply_order):
    """Refresh only the delivery state for a staff-linked external order."""
    token = settings.BUILTASUPPLY_STATUS_API_TOKEN
    if not token:
        supply_order.last_sync_error = "Delivery tracking is not configured."
        supply_order.save(update_fields=["last_sync_error", "updated_at"])
        return False

    url = settings.BUILTASUPPLY_STATUS_API_URL.format(order_number=quote(supply_order.order_number, safe=""))
    request = Request(url, headers={"X-RealEstate-Status-Token": token, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        supply_order.last_sync_error = "Order was not found or tracking is unavailable." if error.code == 404 else "Delivery tracking is temporarily unavailable."
    except (URLError, TimeoutError, ValueError):
        supply_order.last_sync_error = "Delivery tracking is temporarily unavailable."
    else:
        status = payload.get("delivery_status")
        valid_statuses = {value for value, _ in supply_order.DELIVERY_STATUS_CHOICES}
        if status not in valid_statuses:
            supply_order.last_sync_error = "BUILTASUPPLY returned an invalid delivery status."
        else:
            supply_order.delivery_status = status
            supply_order.last_synced_at = timezone.now()
            supply_order.last_sync_error = ""
            supply_order.save(update_fields=["delivery_status", "last_synced_at", "last_sync_error", "updated_at"])
            return True

    supply_order.save(update_fields=["last_sync_error", "updated_at"])
    return False
