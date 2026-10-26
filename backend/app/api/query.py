from fastapi import Request
from fastapi.dependencies.models import Dependant

from app.errors import AppError


def reject_unknown_query_parameters(request: Request) -> None:
    """Reject query parameters the matched route does not declare, instead of ignoring them."""
    route = request.scope.get("route")
    if route is None:
        return
    declared = _declared_query_parameters(route.dependant)
    unknown = [name for name in dict.fromkeys(request.query_params) if name not in declared]
    if unknown:
        raise AppError(
            422,
            "invalid_request",
            "The request is invalid.",
            {
                "errors": [
                    {"location": ["query", name], "problem": "unknown_parameter"}
                    for name in unknown
                ]
            },
        )


def _declared_query_parameters(dependant: Dependant) -> set[str]:
    names = {param.alias for param in dependant.query_params}
    for dependency in dependant.dependencies:
        names |= _declared_query_parameters(dependency)
    return names
