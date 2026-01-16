#!/usr/bin/env python3
"""
Metabase Sync Tool.

Handles backup, restore, inspect, and verify operations for Metabase.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import datetime


# --- UI Helpers ---
class UI:
    """Terminal UI helpers."""

    G, Y, R, B, BOLD, NC = (
        "\033[92m",
        "\033[93m",
        "\033[91m",
        "\033[94m",
        "\033[1m",
        "\033[0m",
    )

    @staticmethod
    def log(symbol, color, msg):
        """Log a formatted message to stdout."""
        print(f"{color}{symbol} {msg}{UI.NC}")


class MetabaseClient:
    """Interact with Metabase API."""

    def __init__(self, url, user, password):
        self.url, self.user, self.password = url.rstrip("/"), user, password
        self.session_id = None

    def _request(self, method, path, data=None):
        req = urllib.request.Request(f"{self.url}{path}", method=method)
        req.add_header("Content-Type", "application/json")
        if self.session_id:
            req.add_header("X-Metabase-Session", self.session_id)
        try:
            body = json.dumps(data).encode("utf-8") if data else None
            with urllib.request.urlopen(req, data=body, timeout=20) as resp:
                raw = resp.read()
                return json.loads(raw.decode("utf-8")) if raw else {}
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            UI.log("⚠", UI.Y, f"API Error {e.code} on {path}")
            return None
        except (urllib.error.URLError, ValueError) as e:
            UI.log("⚠", UI.Y, f"Connection error: {e}")
            return None

    def login(self):
        """Attempt to log in to Metabase."""
        UI.log("→", UI.B, f"Logging in to Metabase ({self.user})...")
        res = self._request(
            "POST", "/api/session", {"username": self.user, "password": self.password}
        )
        if res and "id" in res:
            self.session_id = res["id"]
            return True
        UI.log(
            "⚠",
            UI.Y,
            "Metabase might be starting up or unreachable. "
            "It usually takes 2-3 minutes to initialize.",
        )
        UI.log(
            "ℹ",
            UI.B,
            "If you just started the container, please wait a bit and try again.",
        )
        return False

    def _unwrap(self, res):
        return (
            res["data"]
            if isinstance(res, dict) and "data" in res
            else (res if isinstance(res, list) else [])
        )

    def get_content(self):
        """Retrieve cards and dashboards."""
        cards = self._unwrap(self._request("GET", "/api/card"))
        dashes = [
            self._request("GET", f"/api/dashboard/{d['id']}")
            for d in self._unwrap(self._request("GET", "/api/dashboard"))
        ]
        return cards, [d for d in dashes if d]

    def restore_content(self, db_id, cards, dashboards):
        """Restore content from backup."""
        # 1. Restore Cards (3 passes for dependencies)
        existing = {
            c["name"]: c["id"] for c in self._unwrap(self._request("GET", "/api/card"))
        }
        id_map = {
            str(c["id"]): existing[c["name"]] for c in cards if c["name"] in existing
        }
        to_restore = [c for c in cards if c["name"] not in existing]
        to_restore.sort(key=lambda x: x.get("id", 0))

        restored = 0
        for _ in range(3):
            if not to_restore:
                break
            rem = []
            for c in to_restore:
                payload = {**c, "collection_id": None}
                if "id" in payload:
                    del payload["id"]
                payload["dataset_query"]["database"] = db_id

                # Update nested dependencies
                dq = payload["dataset_query"]
                if dq.get("type") == "query" and "query" in dq:
                    st = dq["query"].get("source-table")
                    if isinstance(st, str) and st.startswith("card__"):
                        old_id = st.replace("card__", "")
                        if old_id in id_map:
                            dq["query"]["source-table"] = f"card__{id_map[old_id]}"
                        else:
                            rem.append(c)
                            continue

                res = self._request("POST", "/api/card", payload)
                if res and "id" in res:
                    id_map[str(c["id"])], restored = res["id"], restored + 1
                else:
                    rem.append(c)
            to_restore = rem

        UI.log(
            "✓",
            UI.G,
            f"Cards: {restored} restored, {len(cards) - len(to_restore) - restored} existing",
        )

        # 2. Restore Dashboards
        dash_map = {
            d["name"]: d["id"]
            for d in self._unwrap(self._request("GET", "/api/dashboard"))
        }
        for d in dashboards:
            d_id = dash_map.get(d["name"]) or (
                self._request("POST", "/api/dashboard", {"name": d["name"]}) or {}
            ).get("id")
            if not d_id:
                continue

            cards_payload = []
            for i, dc in enumerate(d.get("dashcards", d.get("ordered_cards", []))):
                cid = dc.get("card_id")
                if cid and str(cid) not in id_map:
                    continue

                # Extract clean card payload for bulk update
                ndc = {
                    "id": -(i + 1),
                    "row": dc.get("row", 0),
                    "col": dc.get("col", 0),
                    "size_x": dc.get("size_x", 4),
                    "size_y": dc.get("size_y", 4),
                    "visualization_settings": dc.get("visualization_settings", {}),
                    "parameter_mappings": dc.get("parameter_mappings", []),
                }
                if cid:
                    ndc["card_id"] = id_map[str(cid)]
                cards_payload.append(ndc)

            UI.log(
                "→",
                UI.B,
                f"Updating dashboard '{d['name']}' ({len(cards_payload)} cards)...",
            )
            self._request(
                "PUT", f"/api/dashboard/{d_id}/cards", {"cards": cards_payload}
            )
        return not to_restore

    def show_inspect(self):
        """Display current Metabase statistics."""
        props = self._request("GET", "/api/session/properties") or {}
        cards = self._unwrap(self._request("GET", "/api/card"))
        dashes = self._unwrap(self._request("GET", "/api/dashboard"))
        dbs = self._unwrap(self._request("GET", "/api/database"))

        print(
            f"\n{UI.BOLD}--- Metabase Overview ({props.get('version', {}).get('tag')}) ---{UI.NC}"
        )
        print(
            f"Stats: {len(cards)} cards, {len(dashes)} dashboards, {len(dbs)} databases"
        )

        def tree(title, items, fmt=lambda x: x):
            if not items:
                return
            print(f"\n{UI.BOLD}{title}{UI.NC}")
            for i, item in enumerate(items):
                print(f"{'└── ' if i == len(items) - 1 else '├── '}{fmt(item)}")

        dash_details = []
        for d in dashes:
            det = self._request("GET", f"/api/dashboard/{d['id']}")
            cnt = len(det.get("dashcards", det.get("ordered_cards", []))) if det else 0
            dash_details.append((d["name"], cnt))

        tree(
            "Dashboards", dash_details, lambda x: f"{x[0]} {UI.G}({x[1]} cards){UI.NC}"
        )
        tree("Databases", dbs, lambda x: x["name"])
        tree(
            "Users",
            self._unwrap(self._request("GET", "/api/user")),
            lambda x: f"{x.get('common_name', x.get('email'))} ({x.get('email')})",
        )

    def verify(self):
        """Check consistency of dashboards and cards."""
        UI.log("→", UI.B, "Verifying Metabase integrity...")

        # 1. Check Cards
        cards = self._unwrap(self._request("GET", "/api/card"))
        if not cards:
            UI.log("✗", UI.R, "No cards found in Metabase instance.")
            return False

        # 2. Check Dashboards
        dashes = self._unwrap(self._request("GET", "/api/dashboard"))
        if not dashes:
            UI.log("✗", UI.R, "No dashboards found in Metabase instance.")
            return False

        UI.log("ℹ", UI.B, f"Found {len(cards)} cards and {len(dashes)} dashboards.")

        # 3. Check Linkages
        success = True
        valid_card_ids = {c["id"] for c in cards}

        for d in dashes:
            # Detailed fetch to get dashcards
            detailed = self._request("GET", f"/api/dashboard/{d['id']}")
            if not detailed:
                UI.log("⚠", UI.Y, f"Could not get details for dashboard {d['name']}")
                success = False
                continue

            dash_cards = detailed.get(
                "dashcards", detailed.get("ordered_cards", detailed.get("cards", []))
            )

            if not dash_cards:
                UI.log("⚠", UI.Y, f"Dashboard '{d['name']}' is empty (no cards).")
                success = False
                continue

            missing_cards = []
            for dc in dash_cards:
                cid = dc.get("card_id")
                if cid and cid not in valid_card_ids:
                    missing_cards.append(cid)

            if missing_cards:
                UI.log(
                    "✗",
                    UI.R,
                    f"Dashboard '{d['name']}': Found {len(missing_cards)} missing cards "
                    f"(IDs: {missing_cards})",
                )
                success = False
            else:
                UI.log(
                    "✓",
                    UI.G,
                    f"Dashboard '{d['name']}': {len(dash_cards)} cards OK",
                )

        if success:
            UI.log("✓", UI.G, "Verification complete: All checks passed.")
        else:
            UI.log("✗", UI.R, "Verification failed: Integrity issues found.")
        return success


def main():
    """Execute the CLI application."""
    if os.path.exists(".env"):
        with open(".env", encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    os.environ.setdefault(k, v)

    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["backup", "restore", "inspect", "verify"])
    p.add_argument("-f", "--file", help="Backup ZIP file")
    p.add_argument("--db", type=int, help="Target DB ID")
    args = p.parse_args()

    c = MetabaseClient(
        os.getenv("METABASE_URL", ""),
        os.getenv("METABASE_USER", ""),
        os.getenv("METABASE_PASS", ""),
    )
    if not c.login():
        sys.exit(1)

    if args.action == "inspect":
        c.show_inspect()
    elif args.action == "backup":
        fname = (
            args.file
            or f"metabase_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        )
        cards, dashes = c.get_content()
        with zipfile.ZipFile(
            fname, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as zf:
            zf.writestr("cards.json", json.dumps(cards))
            zf.writestr("dashboards.json", json.dumps(dashes))
        UI.log("✓", UI.G, f"Saved to {fname}")
    elif args.action == "restore":
        if not args.file:
            UI.log("✗", UI.R, "File required for restore (-f)")
            return
        if not os.path.exists(args.file):
            UI.log("✗", UI.R, f"File not found: {args.file}")
            return
        if not zipfile.is_zipfile(args.file):
            UI.log("✗", UI.R, f"File is not a valid ZIP archive: {args.file}")
            return

        with zipfile.ZipFile(args.file, "r") as zf:
            c.restore_content(
                args.db or 1,
                json.loads(zf.read("cards.json")),
                json.loads(zf.read("dashboards.json")),
            )
    elif args.action == "verify":
        if not c.verify():
            sys.exit(1)


if __name__ == "__main__":
    main()
