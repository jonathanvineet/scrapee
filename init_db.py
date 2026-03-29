#!/usr/bin/env python3
"""
Database initialization script for scrapee MCP server.

Usage:
    python3 init_db.py                          # Create DB at default location
    python3 init_db.py --db-path /custom/path   # Create DB at custom location
    python3 init_db.py --reset                  # Reset existing database
"""

import argparse
import sys
from pathlib import Path

from mcp_server.config import DB_PATH
from mcp_server.storage.sqlite_store import SQLiteStore


def init_database(db_path: str, reset: bool = False) -> bool:
    """Initialize the SQLite database with proper schema."""
    db_file = Path(db_path)
    
    # Ensure parent directory exists
    db_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Reset if requested
    if reset and db_file.exists():
        print(f"🗑️  Removing existing database at {db_path}")
        db_file.unlink()
    
    try:
        # Initialize store (this creates schema if needed)
        store = SQLiteStore(db_path)
        
        # Verify schema was created
        stats = store.get_stats()
        
        print(f"✅ Database initialized at: {db_path}")
        print(f"   Location: {db_file.absolute()}")
        print(f"   Status: Ready for use")
        print(f"   Current stats: {stats}")
        return True
        
    except Exception as e:
        print(f"❌ Failed to initialize database: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Initialize scrapee MCP database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 init_db.py                    # Use default location
  python3 init_db.py --reset            # Reset existing database
  python3 init_db.py --db-path ./my.db  # Use custom location
        """
    )
    
    parser.add_argument(
        "--db-path",
        default=DB_PATH,
        help=f"Path to SQLite database (default: {DB_PATH})"
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset (delete and recreate) existing database"
    )
    
    args = parser.parse_args()
    
    print("🗄️  Initializing scrapee MCP database...")
    print()
    
    success = init_database(args.db_path, reset=args.reset)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
