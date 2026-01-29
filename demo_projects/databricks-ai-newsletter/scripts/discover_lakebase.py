#!/usr/bin/env python3
"""
Discover Lakebase configuration for databricks.yml
"""

from databricks.sdk import WorkspaceClient
import sys

print("="*70)
print("LAKEBASE CONFIGURATION DISCOVERY")
print("="*70)
print()

try:
    w = WorkspaceClient()

    # Get current user
    current_user = w.current_user.me()
    print(f"Current user: {current_user.user_name}")
    print(f"Workspace: {w.config.host}")
    print()

    print("="*70)
    print("LAKEBASE PROJECTS")
    print("="*70)

    projects = list(w.postgres.list_projects())

    if not projects:
        print("⚠️  No Lakebase projects found.")
        print()
        print("Create a Lakebase project in the Databricks UI:")
        print("  Data → Lakebase → Create Project")
        sys.exit(1)

    for project in projects:
        display_name = project.status.display_name
        project_id = project.uid

        print()
        print(f"📦 Project: {display_name}")
        print(f"   ID: {project_id}")
        print(f"   Path: {project.name}")

        # List branches
        branches = list(w.postgres.list_branches(parent=project.name))

        if not branches:
            print("   ⚠️  No branches found")
            continue

        for branch in branches:
            branch_id = branch.uid
            print(f"   └─ Branch: {branch_id}")

            # List endpoints
            endpoints = list(w.postgres.list_endpoints(parent=branch.name))

            if not endpoints:
                print(f"      ⚠️  No endpoints found")
                continue

            for endpoint in endpoints:
                endpoint_id = endpoint.uid
                endpoint_path = endpoint.name

                # Get DNS from status if available
                try:
                    if hasattr(endpoint, 'status') and hasattr(endpoint.status, 'dns'):
                        dns = endpoint.status.dns
                    else:
                        # Construct DNS from endpoint ID (common pattern)
                        dns = f"{endpoint_id}.database.us-west-2.cloud.databricks.com"
                except:
                    dns = "unknown"

                print(f"      └─ Endpoint: {endpoint_id}")
                print(f"         Full path: {endpoint_path}")
                print(f"         DNS: {dns}")

                # Print configuration for databricks.yml
                print()
                print("      " + "─"*60)
                print("      Configuration for databricks.yml:")
                print("      " + "─"*60)
                print(f"      lakebase_endpoint: {endpoint_path}")
                print(f"      pghost: {dns}")
                print(f"      pgdatabase: databricks_postgres")
                print()

    print()
    print("="*70)
    print("✅ DISCOVERY COMPLETE")
    print("="*70)
    print()
    print("Next steps:")
    print("1. Copy the configuration values above")
    print("2. Update the 'variables' section in databricks.yml")
    print("3. Run: databricks bundle validate")
    print("4. Deploy: databricks bundle deploy -t dev")

except Exception as e:
    print(f"❌ Error: {e}")
    print()
    print("Make sure:")
    print("1. You're authenticated: databricks auth login")
    print("2. You have access to Lakebase in this workspace")
    sys.exit(1)
