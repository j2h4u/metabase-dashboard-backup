# Metabase API: Key Nuances and Restoration Lessons

During the debugging and restoration of Metabase dashboards and cards, several critical technical nuances were identified. This document serves as a reference for future interactions with the Metabase API (v0.50+).

## 1. Authentication
- **Session-Based**: Use `POST /api/session` to get a `session_id`.
- **Header**: All subsequent requests must include the header `X-Metabase-Session: <session_id>`.

## 2. Card (Question) Restoration
- **ID Mapping**: Cards in backups usually contain internal dependencies. When restoring to a new database, you must map the `database_id` and any nested `card__ID` references in `dataset_query`.
- **Dependency Resolution**: Some cards are built on top of other cards (nested queries). A **multi-pass** approach is necessary:
    1. Identify existing cards.
    2. Try restoring new cards.
    3. If a card fails because its "source-table" (parent card) doesn't exist yet, defer it to the next pass.
- **Required Fields**: The `type` field is now mandatory (`question` or `model`). The legacy `dataset` boolean is deprecated.
- **Payload Cleaning**: Stripping `creator_id`, `created_at`, and `id` from the card payload prevents `400 Bad Request` errors caused by trying to overwrite system-managed fields.

## 3. Dashboard Card (Linkage) Management
This is the most sensitive part of the API.
- **Bulk Update (Idempotency)**: Use `PUT /api/dashboard/:id/cards` with a `{"cards": [...]}` payload to sync the dashboard content in one call.
- **Unique Negative IDs**: When adding *new* cards via the bulk update API, you **must** assign them unique negative IDs (e.g., `-1`, `-2`, `-3`). Metabase uses these temporary IDs to distinguish new entries from existing ones in the transaction.
- **Individual Addition**: `POST /api/dashboard/:id/cards` exists but is often less reliable for full restoration because it doesn't support the same atomic dependency handling as the bulk PUT.
- **Payload Structure**:
    - Use `card_id` (underscore) for regular cards.
    - Omit `card_id` for text cards.
    - Ensure `row`, `col`, `size_x`, and `size_y` are present to avoid overlapping or layout errors.

## 4. Verification and Keys
- **Dashcard Keys**: Depending on the version and endpoint (`GET /api/dashboard/:id`), the list of cards might be under `dashcards`, `ordered_cards`, or `cards`. Always check all three.
- **Empty Responses**: Success on `DELETE` or certain `PUT` operations often returns an empty body (`204 No Content`). Ensure the HTTP client doesn't crash on empty JSON parsing.

## 5. Environment Readiness
- **Startup Latency**: When Metabase starts, the `/api/health` endpoint returns `200` quickly, but specific data endpoints might still return `503` or timeout while the backend initializes its internal DB and plugins. Implement a retry/wait loop for the first authenticated request.
