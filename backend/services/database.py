import os
import psycopg2
import psycopg2.extras

TABLE = "free_banks_auctions_stage_2_22_38_05_08_06_26"

FILTERABLE_COLUMNS = [
    "city", "asset_type", "asset_category", "institution",
    "reserve_price", "auction_type", "asset_location",
]

COLUMN_LABELS = {
    "listing_id": "Listing ID",
    "institution": "Institution",
    "institution_branch": "Branch",
    "contact_details": "Contact",
    "auction_type": "Auction Type",
    "borrower_name": "Borrower",
    "asset_category": "Asset Category",
    "asset_type": "Asset Type",
    "asset_details": "Details",
    "asset_schedule": "Schedule",
    "asset_address": "Address",
    "asset_location": "Location",
    "city": "City",
    "reserve_price": "Reserve Price",
    "emd": "EMD",
    "publication_date": "Published",
    "auction_date_time": "Auction Date",
    "auction_end_date_time": "Auction End",
    "application_submission_deadline": "Submission Deadline",
    "e_auctionprovider": "Auction Provider",
    "documents_available": "Documents",
}


class DatabaseService:
    def __init__(self):
        self.dsn = os.getenv("DATABASE_URL")
        self._conn = None

    def get_connection(self):
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self.dsn)
            self._conn.autocommit = False
        return self._conn

    def close(self):
        if self._conn and not self._conn.closed:
            self._conn.close()

    def get_distinct_values(self, column):
        query = f"SELECT DISTINCT {column} FROM {TABLE} WHERE {column} IS NOT NULL ORDER BY {column} LIMIT 50"
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                return [row[0] for row in cur.fetchall()]

    def search_auctions(self, filters=None, limit=10, offset=0):
        conditions = []
        params = []

        if filters:
            if filters.get("city"):
                conditions.append("LOWER(city) LIKE LOWER(%s)")
                params.append(f"%{filters['city']}%")

            if filters.get("asset_type"):
                conditions.append("LOWER(asset_type) LIKE LOWER(%s)")
                params.append(f"%{filters['asset_type']}%")

            if filters.get("asset_category"):
                conditions.append("LOWER(asset_category) LIKE LOWER(%s)")
                params.append(f"%{filters['asset_category']}%")

            if filters.get("institution"):
                conditions.append("LOWER(institution) LIKE LOWER(%s)")
                params.append(f"%{filters['institution']}%")

            if filters.get("auction_type"):
                conditions.append("LOWER(auction_type) LIKE LOWER(%s)")
                params.append(f"%{filters['auction_type']}%")

            if filters.get("asset_location"):
                conditions.append("LOWER(asset_location) LIKE LOWER(%s)")
                params.append(f"%{filters['asset_location']}%")

            if filters.get("min_reserve_price"):
                conditions.append("CAST(REGEXP_REPLACE(reserve_price, '[^0-9.]', '', 'g') AS NUMERIC) >= %s")
                params.append(filters["min_reserve_price"])

            if filters.get("max_reserve_price"):
                conditions.append("CAST(REGEXP_REPLACE(reserve_price, '[^0-9.]', '', 'g') AS NUMERIC) <= %s")
                params.append(filters["max_reserve_price"])

        where_clause = " AND ".join(conditions) if conditions else "TRUE"
        query = f"""
            SELECT * FROM {TABLE}
            WHERE {where_clause}
            ORDER BY auction_date_time DESC NULLS LAST, city
            LIMIT %s OFFSET %s
        """
        params.extend([limit, offset])

        count_query = f"SELECT COUNT(*) FROM {TABLE} WHERE {where_clause}"

        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(count_query, params[:-2])
                total = cur.fetchone()["count"]

                cur.execute(query, params)
                rows = cur.fetchall()

        return rows, total

    def _parse_price(self, price_str):
        if price_str is None:
            return None
        cleaned = str(price_str).replace("₹", "").replace(",", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None

    def format_auction_brief(self, row):
        parts = []
        parts.append(f"*{row.get('asset_type', 'Property')}*")
        if row.get("city"):
            parts.append(f"📍 {row['city']}")
        if row.get("reserve_price"):
            parts.append(f"💰 {row['reserve_price']}")
        if row.get("auction_date_time") and hasattr(row['auction_date_time'], 'strftime'):
            parts.append(f"📅 Auction: {row['auction_date_time'].strftime('%d %b %Y %I:%M %p')}")
        if row.get("institution"):
            parts.append(f"🏦 {row['institution']}")
        if row.get("asset_category"):
            parts.append(f"📋 {row['asset_category']}")
        return " | ".join(parts)

    def format_auction_detail(self, row):
        lines = []
        for key, label in COLUMN_LABELS.items():
            val = row.get(key)
            if val is not None and val != "":
                if hasattr(val, 'strftime'):
                    lines.append(f"{label}: {val.strftime('%d %b %Y %I:%M %p')}")
                else:
                    lines.append(f"{label}: {val}")
        return "\n".join(lines)
