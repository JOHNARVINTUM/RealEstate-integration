import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from django.conf import settings
from django.utils import timezone


def _validated_order_summary(payload):
    """Return the deliberately limited purchase summary, or None if malformed."""
    total_minor = payload.get("order_total_minor")
    currency = payload.get("currency")
    items = payload.get("items")
    if (
        isinstance(total_minor, bool)
        or not isinstance(total_minor, int)
        or total_minor < 0
        or not isinstance(currency, str)
        or len(currency) != 3
        or not isinstance(items, list)
    ):
        return None

    cleaned_items = []
    for item in items:
        if not isinstance(item, dict):
            return None
        name = item.get("name")
        quantity = item.get("quantity")
        unit_of_measure = item.get("unit_of_measure")
        unit_price_minor = item.get("unit_price_minor")
        line_total_minor = item.get("line_total_minor")
        if (
            not isinstance(name, str)
            or not name.strip()
            or len(name) > 255
            or isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or quantity <= 0
            or not isinstance(unit_of_measure, str)
            or len(unit_of_measure) > 32
            or isinstance(unit_price_minor, bool)
            or not isinstance(unit_price_minor, int)
            or unit_price_minor < 0
            or isinstance(line_total_minor, bool)
            or not isinstance(line_total_minor, int)
            or line_total_minor < 0
        ):
            return None
        cleaned_items.append(
            {
                "name": name.strip(),
                "quantity": quantity,
                "unit_of_measure": unit_of_measure.strip(),
                "unit_price_minor": unit_price_minor,
                "line_total_minor": line_total_minor,
            }
        )
    return {"order_total_minor": total_minor, "currency": currency.upper(), "items_snapshot": cleaned_items}


def refresh_delivery_status(supply_order):
    """Refresh a limited, read-only delivery and purchase summary for an external order."""
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
        summary = _validated_order_summary(payload)
        valid_statuses = {value for value, _ in supply_order.DELIVERY_STATUS_CHOICES}
        if status not in valid_statuses:
            supply_order.last_sync_error = "BUILTASUPPLY returned an invalid delivery status."
        elif summary is None:
            supply_order.last_sync_error = "BUILTASUPPLY returned an invalid order summary."
        else:
            supply_order.delivery_status = status
            supply_order.order_total_minor = summary["order_total_minor"]
            supply_order.currency = summary["currency"]
            supply_order.items_snapshot = summary["items_snapshot"]
            supply_order.last_synced_at = timezone.now()
            supply_order.last_sync_error = ""
            supply_order.save(
                update_fields=[
                    "delivery_status",
                    "order_total_minor",
                    "currency",
                    "items_snapshot",
                    "last_synced_at",
                    "last_sync_error",
                    "updated_at",
                ]
            )
            return True

    supply_order.save(update_fields=["last_sync_error", "updated_at"])
    return False
