import re
from collections.abc import Callable

from flask import Blueprint, jsonify, request

from app.api.serializers import to_jsonable
from app.config import get_settings
from app.data.client_repository import ClientManagementError, ClientNotFoundError, ClientRepository
from app.data.repositories import SeedRepository
from app.pages.usage import _usage_rows
from app.utils.dates import current_month_key

api_bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")

MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class ApiError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@api_bp.before_request
def require_auth() -> None:
    token = get_settings().revenue_api_token
    if not token:
        return
    header = request.headers.get("Authorization", "")
    provided = header.removeprefix("Bearer ").strip()
    if provided != token:
        raise ApiError("Missing or invalid bearer token.", status_code=401)


@api_bp.errorhandler(ApiError)
def handle_api_error(error: ApiError):
    return jsonify({"error": error.message}), error.status_code


@api_bp.errorhandler(ClientNotFoundError)
def handle_client_not_found(error: ClientNotFoundError):
    return jsonify({"error": str(error)}), 404


@api_bp.errorhandler(ClientManagementError)
def handle_client_management_error(error: ClientManagementError):
    return jsonify({"error": str(error)}), 400


@api_bp.errorhandler(ValueError)
def handle_value_error(error: ValueError):
    return jsonify({"error": str(error)}), 400


def _month_param() -> str:
    month = request.args.get("month", current_month_key())
    if not MONTH_PATTERN.match(month):
        raise ApiError(f"Invalid 'month' parameter '{month}'. Expected format YYYY-MM.", status_code=400)
    return month


def _optional_month_param() -> str | None:
    month = request.args.get("month")
    if month is not None and not MONTH_PATTERN.match(month):
        raise ApiError(f"Invalid 'month' parameter '{month}'. Expected format YYYY-MM.", status_code=400)
    return month


def _client_id_param(raw_client_id: str) -> int:
    try:
        return int(raw_client_id)
    except ValueError as exc:
        raise ApiError(f"Invalid client id '{raw_client_id}'.", status_code=400) from exc


def _endpoint(handler: Callable[[], object]):
    return jsonify(to_jsonable(handler()))


@api_bp.get("/health")
def health():
    return jsonify({"status": "ok"})


@api_bp.get("/months")
def months():
    repository = SeedRepository()
    return _endpoint(lambda: {"months": repository.available_months()})


@api_bp.get("/summary")
def summary():
    month = _month_param()
    repository = SeedRepository()
    return _endpoint(lambda: {"month": month, **repository.monthly_summary(month)})


@api_bp.get("/revenue/split")
def revenue_split():
    month = _month_param()
    repository = SeedRepository()
    return _endpoint(lambda: {"month": month, **repository.monthly_revenue_split(month)})


@api_bp.get("/revenue/by-service")
def revenue_by_service():
    month = _month_param()
    repository = SeedRepository()
    return _endpoint(lambda: {"month": month, "by_service": repository.revenue_by_service(month)})


@api_bp.get("/costs/history")
def cost_history():
    repository = SeedRepository()
    return _endpoint(lambda: {"history": repository.cost_history()})


@api_bp.get("/costs/by-service")
def costs_by_service():
    month = _month_param()
    repository = SeedRepository()
    return _endpoint(lambda: {"month": month, "by_service": repository.cost_by_service(month)})


@api_bp.get("/costs/by-provider")
def costs_by_provider():
    month = _month_param()
    repository = SeedRepository()
    return _endpoint(lambda: {"month": month, "by_provider": repository.cost_by_provider(month)})


@api_bp.get("/costs/by-category")
def costs_by_category():
    month = _month_param()
    repository = SeedRepository()
    return _endpoint(lambda: {"month": month, "by_category": repository.cost_by_category(month)})


@api_bp.get("/usage")
def usage():
    month = _optional_month_param()
    raw_client_id = request.args.get("client_id")
    client_id = _client_id_param(raw_client_id) if raw_client_id is not None else None
    repository = SeedRepository()

    def build():
        rows = _usage_rows(repository)
        if month is not None:
            rows = [row for row in rows if row["timestamp"].startswith(month)]
        if client_id is not None:
            rows = [row for row in rows if row["client_id"] == client_id]
        return {"usage": rows}

    return _endpoint(build)


@api_bp.get("/clients/<raw_client_id>/usage")
def client_usage(raw_client_id: str):
    client_id = _client_id_param(raw_client_id)
    month = _month_param()
    repository = SeedRepository()
    ClientRepository().get_client(client_id)  # 404s if the client does not exist

    def build():
        rows = [row for row in _usage_rows(repository) if row["client_id"] == client_id]
        rows = [row for row in rows if row["timestamp"].startswith(month)]
        return {"month": month, "usage": rows}

    return _endpoint(build)


@api_bp.get("/clients")
def clients():
    status = request.args.get("status", "all")
    repository = ClientRepository()
    return _endpoint(lambda: {"clients": repository.list_clients(status=status)})


@api_bp.get("/clients/<raw_client_id>")
def client_detail(raw_client_id: str):
    client_id = _client_id_param(raw_client_id)
    repository = ClientRepository()
    return _endpoint(lambda: repository.get_client(client_id))


@api_bp.get("/clients/<raw_client_id>/profitability")
def client_profitability(raw_client_id: str):
    client_id = _client_id_param(raw_client_id)
    month = _month_param()
    repository = SeedRepository()
    ClientRepository().get_client(client_id)  # 404s if the client does not exist
    return _endpoint(lambda: {"month": month, **repository.client_profitability(client_id, month).model_dump()})


@api_bp.get("/clients/<raw_client_id>/revenue-split")
def client_revenue_split(raw_client_id: str):
    client_id = _client_id_param(raw_client_id)
    month = _month_param()
    repository = SeedRepository()
    ClientRepository().get_client(client_id)  # 404s if the client does not exist
    return _endpoint(lambda: {"month": month, **repository.client_revenue_split(client_id, month)})
