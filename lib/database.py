import time
from contextlib import contextmanager
import psycopg
from psycopg.sql import SQL, Placeholder, Composed, Identifier
from lib.config import get_config, get_env
from lib.models import NewListing
from datetime import datetime
import zoneinfo
from lib.logger import get_logger

berlin_tz = zoneinfo.ZoneInfo("Europe/Berlin")

config = get_config()
env = get_env()


GET_KLEINANZEIGEN_IDS_BY_STATE_SQL = SQL(
    """
    SELECT DISTINCT f.kleinanzeigen_location_id
    FROM germany.custom f
    JOIN germany.zuordnung_plz_ags z ON f.plz = z.plz
    WHERE z.bundesland = {state}
    """
).format(state=Placeholder("state"))

SET_NEW_LISTING_DATA_SQL: Composed = SQL(
    "INSERT INTO {schema}.{table} ({fields}) VALUES ({values}) " "ON CONFLICT ({conflict}) DO UPDATE SET {updates}"
).format(
    schema=Identifier("fixnflip_v2"),
    table=Identifier("property"),
    fields=SQL(", ").join(
        [
            Identifier("source"),
            Identifier("external_id"),
            Identifier("modified_at"),
            Identifier("created_at"),
        ]
    ),
    values=SQL(", ").join(
        [
            Placeholder("source"),
            Placeholder("external_id"),
            Placeholder("modified_at"),
            Placeholder("created_at"),
        ]
    ),
    conflict=SQL(", ").join([Identifier("external_id"), Identifier("source")]),
    updates=SQL("{0} = EXCLUDED.{0}").format(Identifier("modified_at")),
)

SELECT_PROPERTY_IDS_SQL = SQL(
    """
    SELECT id, external_id 
    FROM {schema}.{table} 
    WHERE (external_id, source::text) IN (SELECT unnest(%(external_ids)s::text[]), unnest(%(sources)s::text[]))
    """
).format(schema=Identifier("fixnflip_v2"), table=Identifier("property"))

GENERAL_INSERT_SQL: Composed = SQL(
    # Dont update active status to True on conflicts since this will be handled by scraper and not finder
    "INSERT INTO {schema}.{table} ({fields}) VALUES ({values}) ON CONFLICT ({conflict}) DO NOTHING"
    # "INSERT INTO {schema}.{table} ({fields}) VALUES ({values}) ON CONFLICT ({conflict}) DO UPDATE SET active = EXCLUDED.active"
).format(
    schema=Identifier("fixnflip_v2"),
    table=Identifier("general"),
    fields=SQL(", ").join([Identifier("property_id"), Identifier("active")]),
    values=SQL(", ").join([Placeholder("property_id"), Placeholder("active")]),
    conflict=Identifier("property_id"),
)

SYSTEM_INSERT_SQL: Composed = SQL(
    "INSERT INTO {schema}.{table} ({fields}) VALUES ({values}) " "ON CONFLICT ({conflict}) DO UPDATE SET {updates}"
).format(
    schema=Identifier("fixnflip_v2"),
    table=Identifier("system"),
    fields=SQL(", ").join([Identifier("property_id"), Identifier("last_seen_at")]),
    values=SQL(", ").join([Placeholder("property_id"), Placeholder("last_seen_at")]),
    conflict=Identifier("property_id"),
    updates=SQL("{0} = EXCLUDED.{0}").format(Identifier("last_seen_at")),
)

def db_operation_with_retry(func):
    def wrapper(self, *args, **kwargs):
        attempts = config.database.max_retries
        delay = config.database.retry_delay
        for attempt in range(1, attempts + 1):
            try:
                return func(self, *args, **kwargs)
            except Exception as exc:
                self.logger.warning(f"DB operation failed (attempt {attempt}/{attempts}): {exc}")
                if attempt == attempts:
                    raise
                time.sleep(delay)
    return wrapper


class Database:
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)
        self._conn_kwargs = {
            "host": env.DATABASE__HOST,
            "port": int(env.DATABASE__PORT),
            "dbname": env.DATABASE__NAME,
            "user": env.DATABASE__USER,
            "password": env.DATABASE__PASSWORD,
            "connect_timeout": config.database.timeout,
        }

    @contextmanager
    def _db(self):
        conn = psycopg.connect(**self._conn_kwargs, row_factory=psycopg.rows.dict_row)
        try:
            with conn.cursor() as cursor:
                yield conn, cursor
        finally:
            conn.close()

    @db_operation_with_retry
    def get_kleinanzeigen_ids_by_state(self, state: str) -> list[str]:
        self.logger.debug(f"Getting Kleinanzeigen IDs for state: {state}")
        with self._db() as (_, cursor):
            cursor.execute(
                GET_KLEINANZEIGEN_IDS_BY_STATE_SQL,
                {"state": state},
            )
            results = cursor.fetchall()
        ids = [row["kleinanzeigen_location_id"] for row in results]
        self.logger.debug(f"Found {len(ids)} IDs for state: {state}")
        return ids
    
    @db_operation_with_retry
    def set_new_listing_data(self, listings: list[NewListing]) -> None:
        if not listings:
            self.logger.debug("No listings to process")
            return

        # Log the listings being saved
        self.logger.debug(
            "Saving listings to DB: %s",
            [
                {
                    "external_id": l.external_id,
                    "source": l.source.value,
                    "created_at": l.created_at,
                    "modified_at": l.modified_at,
                }
                for l in listings
            ]
        )

        with self._db() as (connection, cursor):
            self.logger.debug(f"Batch setting property data for {len(listings)} listings")
            cursor.executemany(
                SET_NEW_LISTING_DATA_SQL,
                [
                    {
                        "source": listing.source.value,
                        "external_id": listing.external_id,
                        "modified_at": listing.modified_at,
                        "created_at": listing.created_at if listing.created_at else datetime.now(berlin_tz),
                    }
                    for listing in listings
                ],
            )

            self.logger.debug(f"Selecting property IDs")

            external_ids = [l.external_id for l in listings]
            sources = [l.source.value for l in listings]
            cursor.execute(SELECT_PROPERTY_IDS_SQL, {"external_ids": external_ids, "sources": sources})
            results = cursor.fetchall()
            property_id_mapping: dict[str, str] = {row["external_id"]: row["id"] for row in results}

            if len(property_id_mapping) != len(listings):
                raise ValueError(f"Expected {len(listings)} property IDs, but got {len(property_id_mapping)}")

            self.logger.debug(f"Setting general and system data")
            cursor.executemany(
                GENERAL_INSERT_SQL,
                [
                    {
                        "property_id": property_id_mapping[listing.external_id],
                        "active": True,
                    }
                    for listing in listings
                ],
            )

            self.logger.debug(f"Setting system data")
            cursor.executemany(
                SYSTEM_INSERT_SQL,
                [
                    {
                        "property_id": property_id_mapping[listing.external_id],
                        "last_seen_at": datetime.now(berlin_tz),
                    }
                    for listing in listings
                ],
            )

            connection.commit()
            self.logger.debug(f"Batch listing data set for {len(listings)} listings")