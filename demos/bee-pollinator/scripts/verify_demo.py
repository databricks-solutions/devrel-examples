"""
Bee Pollinator Demo - Verification Script

Tests the deployed Supervisor Agent with sample queries to verify everything works.

Usage:
    python verify_demo.py --supervisor "Bee Colony Health Advisor"
    python verify_demo.py --supervisor "Bee Colony Health Advisor" --profile your_profile
"""

import argparse
import sys
import time

try:
    from databricks_openai import DatabricksOpenAI
    from databricks.sdk import WorkspaceClient
    import mlflow
except ImportError:
    print("Error: Required packages not installed.")
    print("Run: pip install databricks-sdk databricks-openai mlflow")
    sys.exit(1)


# Test queries covering all routing patterns
TEST_QUERIES = [
    {
        "name": "Data Query (Genie)",
        "query": "Which 5 states had the highest colony loss rates in 2023?",
        "expected_agent": "genie",
        "success_indicators": ["state", "loss", "percent", "%", "California"],
    },
    {
        "name": "Document Query (Knowledge Assistant)",
        "query": "What does the Varroa Management Guide recommend for monitoring mite levels?",
        "expected_agent": "knowledge_assistant",
        "success_indicators": ["alcohol", "sugar", "threshold", "treatment", "varroa"],
    },
    {
        "name": "Cross-Modal Query (Both Agents)",
        "query": "California lost 35% of colonies in 2023. What varroa management practices should California beekeepers prioritize?",
        "expected_agent": "both",
        "success_indicators": ["California", "varroa", "treatment", "mite", "protocol"],
    },
]


def query_agent(client: DatabricksOpenAI, supervisor_name: str, query: str) -> str:
    """Query the supervisor agent and return response text."""
    try:
        response = client.responses.create(
            model=supervisor_name,
            input=[{"role": "user", "content": query}],
        )

        # Extract text from response
        answer = "".join(
            block.text
            for item in response.output
            if hasattr(item, "content")
            for block in item.content
            if hasattr(block, "text")
        )

        return answer

    except Exception as e:
        return f"ERROR: {str(e)}"


def check_success(response: str, indicators: list) -> bool:
    """Check if response contains expected success indicators."""
    response_lower = response.lower()
    matches = sum(1 for indicator in indicators if indicator.lower() in response_lower)
    return matches >= 2  # At least 2 indicators should match


def main():
    parser = argparse.ArgumentParser(description="Verify bee pollinator demo")
    parser.add_argument("--supervisor", required=True, help="Supervisor agent name or endpoint")
    parser.add_argument("--profile", default=None, help="Databricks CLI profile name")
    parser.add_argument("--verbose", action="store_true", help="Show full responses")

    args = parser.parse_args()

    print("="*60)
    print("BEE POLLINATOR DEMO VERIFICATION")
    print("="*60)

    # Initialize clients
    print(f"\nConnecting to Databricks (profile: {args.profile or 'default'})...")
    w = WorkspaceClient(profile=args.profile) if args.profile else WorkspaceClient()
    client = DatabricksOpenAI()

    # Get experiment for MLflow tracing
    try:
        experiment = mlflow.get_experiment_by_name(args.supervisor)
        if experiment:
            print(f"✓ Found MLflow experiment: {experiment.experiment_id}")
    except Exception as e:
        print(f"⚠ Could not find MLflow experiment: {e}")

    print(f"\nTesting Supervisor Agent: {args.supervisor}")
    print(f"Running {len(TEST_QUERIES)} test queries...\n")

    # Run test queries
    results = []
    for i, test in enumerate(TEST_QUERIES, 1):
        print(f"[{i}/{len(TEST_QUERIES)}] {test['name']}")
        print(f"Query: {test['query'][:80]}...")

        # Query the agent
        start_time = time.time()
        response = query_agent(client, args.supervisor, test["query"])
        elapsed = time.time() - start_time

        # Check success
        if response.startswith("ERROR:"):
            status = "❌ FAILED"
            success = False
            print(f"  {status} - {response}")
        else:
            success = check_success(response, test["success_indicators"])
            status = "✓ PASSED" if success else "⚠ PARTIAL"
            print(f"  {status} ({elapsed:.1f}s)")

            if args.verbose:
                print(f"  Response: {response[:200]}...")

            if not success:
                print(f"  Expected indicators: {', '.join(test['success_indicators'][:3])}...")

        results.append({
            "name": test["name"],
            "success": success,
            "time": elapsed
        })

        print()

    # Summary
    print("="*60)
    print("VERIFICATION SUMMARY")
    print("="*60)

    passed = sum(1 for r in results if r["success"])
    total = len(results)

    print(f"\nTests passed: {passed}/{total}")
    print(f"Average response time: {sum(r['time'] for r in results) / total:.1f}s")

    if passed == total:
        print("\n🎉 All tests passed! Demo is ready.")
        print("\nNext steps:")
        print("1. Review DEMO_GUIDE.md for booth demo flow")
        print("2. Bookmark the Supervisor Agent URL")
        print("3. Test on conference WiFi if possible")
        sys.exit(0)
    else:
        print("\n⚠ Some tests failed. Review errors above.")
        print("\nTroubleshooting:")
        print("- Verify Genie Space has all 3 tables")
        print("- Verify Knowledge Assistant has 4 PDFs indexed")
        print("- Check Supervisor Agent instructions")
        print("- Test sub-agents individually")
        sys.exit(1)


if __name__ == "__main__":
    main()
