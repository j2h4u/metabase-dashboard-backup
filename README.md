# Metabase Content Sync Tool

> Ever struggled with migrating dashboards and questions between Metabase instances without hauling the entire binary database?
>
> This tool is the lightweight answer.

## Description
This script is designed for backing up and restoring Metabase content (cards and dashboards) via the official API. Unlike simple database copying, this method allows for seamless content migration between different Metabase instances, even if they use different underlying databases (H2, Postgres, MySQL).

## Key Features
- **Idempotency**: The script can be run multiple times safely. If a card or dashboard already exists (matched by name), it won't be duplicated; instead, its content and linkages will be updated.
- **Developer Experience**: Automatic configuration loading from `.env`, interactive database selection during restore, and clear tree-like instance statistics (`inspect`).
- **Dependency Resolution**: A multi-pass restoration algorithm ensures that nested queries (cards based on other cards) are restored in the correct order.
- **Flexible Migration**: Re-map content to a new Database ID on the fly when migrating to a different environment.

## Problem Solving
Metabase does not provide a built-in mechanism for selective export/import of dashboards. This script handles the technical nuances that occur when using the API:
1.  **Card Linkages**: Metabase's bulk-update mechanism requires unique negative IDs for new elements. The script correctly constructs these data payloads.
2.  **Source IDs**: During migration, the target Database ID often changes. The script automatically updates all queries to use the correct target ID.

For more technical details on how these problems are solved at the API level, see the [API Guide](API_GUIDE.md).

## Requirements
The script is standalone and only requires **Python 3**.

## Getting Started

### Configuration
Copy the example environment file and fill in your credentials:
```bash
cp .env.example .env
```

Alternatively, set the environment variables manually:
```bash
export METABASE_URL=http://localhost:3000
export METABASE_USER=admin@example.com
export METABASE_PASS=password123
```

## Commands

### 1. Backup
Create a backup of all cards and dashboards:
```bash
./metabase_sync.py backup -f my_backup.zip
```

### 2. Restore
Restore content from a backup file:
```bash
./metabase_sync.py restore -f my_backup.zip --db 2
```
*(If `--db` is not provided, the script will show a list of available databases for interactive selection)*

### 3. Inspect
View instance statistics and structure:
```bash
./metabase_sync.py inspect
```
*(Displays version, counts of cards/dashboards/users, and a detailed breakdown of dashboard statistics)*

## License
This project is licensed under the [Polyform Noncommercial 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0/) license.

- **Non-commercial use**: Free for personal, educational, and non-profit projects.
- **Commercial use**: Requires prior written permission from the author. For commercial licensing inquiries, please contact the repository owner.
