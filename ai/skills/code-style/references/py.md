# Python style

## Visibility and organization

- Do not prefix ordinary identifiers with `_` to express that they are private.
- Do not create private classes, functions, or files (modules) starting with `_`. This codebase does not use underscore naming to express private APIs.
- Instead of hiding something as "private" with a leading `_`, extract it into its own module and import it from there.
- Separate implementation into appropriately scoped modules when that improves organization.
- Python-defined special names such as `__init__`, `__enter__`, and `__all__` are exempt.

## Backend stack

- Target modern Python `3.14+`.
- Fully type-annotate code.
- Prefer the native generic types over `typing.*` aliases (e.g. `dict[str, int]` over `typing.Dict[AnyStr, int]`).
- Prefer async code where practical.
- Web framework: `FastAPI`.
- Database: typed `sqlalchemy` models for Postgres; `alembic` for migrations.

## Testing

- Write tests for the backend code.
