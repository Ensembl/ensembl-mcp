"""Reusable asynchronous GraphQL transport, validation and request timing."""

import logging
from time import perf_counter
from typing import TypeVar

import httpx
from pydantic import BaseModel, TypeAdapter, ValidationError

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class LookupError(Exception):
    """Only explicitly safe messages cross the MCP boundary."""

    def __init__(self, category: str, message: str):
        self.category = category
        super().__init__(f"{category}: {message}")


class CoreGraphQLClient:
    def __init__(self, http: httpx.AsyncClient, endpoint: str):
        self.http = http
        self.endpoint = endpoint

    async def query_list(
        self,
        operation: str,
        query: str,
        variables: dict,
        field: str,
        model: type[T],
        *,
        single: bool = False,
        not_found_message: str | None = None,
    ) -> list[T]:
        start = perf_counter()
        category = "internal_error"
        status = None
        try:
            response = await self.http.post(
                self.endpoint,
                json={"operationName": operation, "query": query, "variables": variables},
                headers={"Content-Type": "application/json"},
            )
            status = response.status_code
            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError:
                raise LookupError("upstream_response", "The service returned invalid JSON.") from None
            if not isinstance(payload, dict):
                raise LookupError("upstream_response", "The service returned an invalid response.")
            if "errors" in payload:
                if not isinstance(payload["errors"], list):
                    raise LookupError("upstream_response", "The service returned invalid errors.")
                if payload["errors"]:
                    # Fail even if partial data is present; never expose raw upstream messages.
                    raise LookupError("upstream_graphql", "The service could not complete the query.")
            data = payload.get("data")
            if single and not_found_message and isinstance(data, dict) and field in data and data[field] is None:
                raise LookupError("not_found", not_found_message)
            if not isinstance(data, dict) or not isinstance(data.get(field), dict if single else list):
                raise LookupError("upstream_response", "The service returned missing or invalid data.")
            try:
                values = [data[field]] if single else data[field]
                result = TypeAdapter(list[model]).validate_python(values, strict=True)
            except ValidationError:
                raise LookupError("upstream_response", "The service returned invalid result fields.") from None
            category = "success"
            return result
        except httpx.TimeoutException:
            category = "upstream_timeout"
            raise LookupError(category, "The Ensembl service request timed out.") from None
        except httpx.HTTPStatusError:
            category = "upstream_http"
            raise LookupError(category, "The Ensembl service returned an unsuccessful HTTP status.") from None
        except httpx.RequestError:
            category = "upstream_connection"
            raise LookupError(category, "Could not communicate with the Ensembl service.") from None
        except LookupError as exc:
            category = exc.category
            raise
        finally:
            logger.info(
                "graphql operation=%s elapsed_seconds=%.3f outcome=%s http_status=%s",
                operation, perf_counter() - start, category, status,
            )

    async def query_object(self, operation: str, query: str, variables: dict, field: str, model: type[T], *, not_found_message: str | None = None) -> T:
        return (await self.query_list(operation, query, variables, field, model, single=True, not_found_message=not_found_message))[0]
