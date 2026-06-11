"""
tools/property_tools.py
-----------------------
Hermes tool handlers for property search and detail retrieval.

Registered tools:
  - search_properties   (toolset: real_estate)
  - get_property_details (toolset: real_estate)

    Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 8.1, 8.2
    """


def search_properties(
    city: str | None = None,
    asset_type: str | None = None,
    asset_category: str | None = None,
    institution: str | None = None,
    min_price: str | None = None,
    max_price: str | None = None,
    limit: str | None = None,
    offset: str | None = None,
    **kwargs,
) -> str:
    # Coerce types: Groq sometimes passes strings for numeric params
    if isinstance(limit, str):
        limit = int(limit)
    if isinstance(offset, str):
        offset = int(offset)
    if isinstance(min_price, str):
        min_price = float(min_price)
    if isinstance(max_price, str):
        max_price = float(max_price)
    # Clamp limit to [1, 10] — Requirements 2.2, 2.3
    limit = max(1, min(limit, 10))

    try:
        # Late import to avoid circular dependencies at module load time
        from services.database import _get_shared_db  # noqa: PLC0415

        db = _get_shared_db()

        # Build filters dict — omit None values so search_auctions ignores them
        filters = {
            k: v
            for k, v in {
                "city": city,
                "asset_type": asset_type,
                "asset_category": asset_category,
                "institution": institution,
                "min_reserve_price": min_price,
                "max_reserve_price": max_price,
            }.items()
            if v is not None
        }

        rows, total = db.search_auctions(filters=filters, limit=limit, offset=offset)

        results = []
        for row in rows:
            d = dict(row)

            # Serialize date/datetime values to ISO 8601 strings — Requirement 8.1
            for k, v in d.items():
                if hasattr(v, "isoformat"):
                    d[k] = v.isoformat()

            # Truncate long text fields to keep payload compact — Requirement 2.8
            for field in ("asset_details", "asset_schedule", "asset_address"):
                if d.get(field) and len(str(d[field])) > 200:
                    d[field] = str(d[field])[:200] + "..."

            results.append(d)

        return json.dumps(
            {"results": results, "total": int(total), "offset": offset, "limit": limit}
        )

    except Exception as exc:
        logger.exception("search_properties failed: %s", exc)
        return json.dumps({"error": str(exc)})


def get_property_details(listing_id: str, **kwargs) -> str:
    """
    Fetch full details for a single auction listing by listing_id.

    Preconditions:
      - listing_id is a non-empty string.

    Postconditions:
      - Returns a JSON string containing all COLUMN_LABELS fields for the listing.
      - Returns {"error": ...} if the listing_id is not found.
      - On any exception: returns JSON with an "error" key; never raises.

    Requirements: 2.5, 2.6, 2.7, 8.1, 8.2
    """
    try:
        # Late imports to avoid circular dependencies at module load time
        from services.database import _get_shared_db, TABLE  # noqa: PLC0415
        import psycopg2.extras  # noqa: PLC0415

        db = _get_shared_db()

        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    f"SELECT * FROM {TABLE} WHERE listing_id = %s LIMIT 1",
                    (listing_id,),
                )
                row = cur.fetchone()

        if not row:
            return json.dumps({"error": f"Listing {listing_id!r} not found"})

        d = dict(row)

        # Serialize date/datetime values to ISO 8601 strings — Requirement 8.1
        for k, v in d.items():
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()

        return json.dumps(d)

    except Exception as exc:
        logger.exception("get_property_details failed: %s", exc)
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# JSON schemas for Hermes tool registry
# ---------------------------------------------------------------------------

SEARCH_PROPERTIES_SCHEMA = {
    "name": "search_properties",
    "description": (
        "Search the bank auction property database. Call this as soon as the user "
        "mentions any location, property type, budget, or buying intent."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "City name, partial match accepted",
            },
            "asset_type": {
                "type": "string",
                "description": "Property type: Flat, House, Plot, Shop, Office",
            },
            "asset_category": {
                "type": "string",
                "description": "Category: Residential, Commercial, Land",
            },
            "institution": {
                "type": "string",
                "description": "Bank name, partial match",
            },
            "min_price": {
                "type": "string",
                "description": "Minimum reserve price in INR",
            },
            "max_price": {
                "type": "string",
                "description": "Maximum reserve price in INR",
            },
            "limit": {
                "type": "string",
                "description": "Results per page (default 5, max 10)",
            },
            "offset": {
                "type": "string",
                "description": "Pagination offset",
            },
        },
        "required": [],
    },
}

GET_PROPERTY_DETAILS_SCHEMA = {
    "name": "get_property_details",
    "description": "Fetch full details for a specific auction listing by listing_id.",
    "parameters": {
        "type": "object",
        "properties": {
            "listing_id": {
                "type": "string",
                "description": "listing_id from a previous search_properties result",
            },
        },
        "required": ["listing_id"],
    },
}


# ---------------------------------------------------------------------------
# Tool registration — wrapped in try/except so the module loads even outside
# the Hermes runtime (e.g. during unit tests or standalone imports).
# ---------------------------------------------------------------------------

try:
    from tools.registry import registry  # noqa: PLC0415

    registry.register(
        name="search_properties",
        toolset="real_estate",
        handler=search_properties,
        schema=SEARCH_PROPERTIES_SCHEMA,
    )
    registry.register(
        name="get_property_details",
        toolset="real_estate",
        handler=get_property_details,
        schema=GET_PROPERTY_DETAILS_SCHEMA,
    )
except ImportError:
    pass
