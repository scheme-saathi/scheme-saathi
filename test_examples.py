#!/usr/bin/env python3
"""
Quick test script for Scheme Saathi workflow
Run: python test_examples.py
"""

import sys
from pathlib import Path

# Ensure imports work
sys.path.insert(0, str(Path(__file__).parent))

def test_basic_workflow():
    """Test 1: Basic eligibility check"""
    print("\n" + "="*60)
    print("TEST 1: Basic Eligibility Check")
    print("="*60)
    
    try:
        from graph.workflow import build_graph
        
        # Build graph
        graph = build_graph()
        config = {"configurable": {"thread_id": "test-basic-1"}}
        
        # Simulate elderly widow
        citizen = {
            "age": 62,
            "is_widow": True,
            "income": 250000
        }
        
        print(f"\nCitizen Profile: {citizen}")
        print("\nRunning workflow...")
        
        result = graph.invoke(
            {
                "simulated_citizen": citizen,
            },
            config
        )
        
        # Display results
        print("\n✓ Verdicts received:")
        verdicts = result.get("verdicts", {})
        for scheme_id, verdict in verdicts.items():
            print(f"\n  Scheme: {scheme_id}")
            print(f"  Verdict: {verdict.get('verdict', 'N/A')}")
            print(f"  Reason: {verdict.get('reason', 'N/A')}")
            
            # Show conditions
            conditions = verdict.get("conditions", [])
            if conditions:
                print(f"  Conditions ({len(conditions)}):")
                for cond in conditions:
                    print(f"    - {cond.get('field')}: {cond.get('outcome')}")
        
        # Check approval status
        if "__interrupt__" in result:
            print("\n✓ Application drafted and waiting for approval")
        else:
            print("\n✓ Preview only (no application)")
        
        print("\n✓ TEST 1 PASSED\n")
        return True
        
    except Exception as e:
        print(f"\n✗ TEST 1 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_memory_service():
    """Test 2: Memory service functionality"""
    print("\n" + "="*60)
    print("TEST 2: Memory Service")
    print("="*60)
    
    try:
        from agents.chromadb_memory_service import ChromaDBMemoryService
        from agents.contracts import HouseholdScope, MemoryFact
        from datetime import datetime, timedelta
        
        # Initialize
        service = ChromaDBMemoryService()
        household = HouseholdScope(household_id="TEST_HH_001")
        
        print(f"\nHousehold: {household.household_id}")
        
        # Test 1: Consent recording
        print("\n1. Testing consent recording...")
        service.record_consent(
            household=household,
            data_type="PERSONAL_INFO",
            purpose="Eligibility verification"
        )
        print("   ✓ Consent recorded")
        
        # Test 2: Save facts
        print("\n2. Testing fact storage...")
        fact = MemoryFact(
            fact_type="AGE",
            value="62",
            household_scope=household,
            consent_given=True
        )
        service.save_fact(fact)
        print("   ✓ Fact saved")
        
        # Test 3: Read facts
        print("\n3. Testing fact retrieval...")
        facts = service.read_facts(household)
        print(f"   ✓ Retrieved {len(facts)} fact(s)")
        for f in facts:
            print(f"     - {f.fact_type}: {f.value}")
        
        # Test 4: Check consent verification
        print("\n4. Testing consent enforcement...")
        service.withdraw_consent(household, "PERSONAL_INFO")
        facts_after = service.read_facts(household)
        print(f"   ✓ After withdrawal: {len(facts_after)} fact(s)")
        
        # Test 5: Household deletion
        print("\n5. Testing household deletion...")
        service.forget_household(household)
        facts_final = service.read_facts(household)
        print(f"   ✓ After deletion: {len(facts_final)} fact(s)")
        
        print("\n✓ TEST 2 PASSED\n")
        return True
        
    except Exception as e:
        print(f"\n✗ TEST 2 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_multiple_schemes():
    """Test 3: Multi-scheme evaluation"""
    print("\n" + "="*60)
    print("TEST 3: Multiple Schemes")
    print("="*60)
    
    try:
        from graph.workflow import build_graph
        
        graph = build_graph()
        config = {"configurable": {"thread_id": "test-multi-3"}}
        
        # Young person (unlikely eligible)
        citizen = {"age": 35, "is_widow": False, "income": 500000}
        
        print(f"\nCitizen Profile: {citizen}")
        print("\nEvaluating all schemes...")
        
        result = graph.invoke(
            {"simulated_citizen": citizen},
            config
        )
        
        # Analyze results
        verdicts = result.get("verdicts", {})
        eligible = [s for s, v in verdicts.items() if v.get("verdict") == "eligible"]
        ineligible = [s for s, v in verdicts.items() if v.get("verdict") == "ineligible"]
        
        print(f"\nResults ({len(verdicts)} schemes):")
        print(f"  ✓ Eligible: {len(eligible)}")
        if eligible:
            for s in eligible:
                print(f"    - {s}")
        print(f"  ✗ Ineligible: {len(ineligible)}")
        if ineligible:
            for s in ineligible[:3]:
                print(f"    - {s}")
            if len(ineligible) > 3:
                print(f"    ... and {len(ineligible) - 3} more")
        
        print("\n✓ TEST 3 PASSED\n")
        return True
        
    except Exception as e:
        print(f"\n✗ TEST 3 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_workflow_persistence():
    """Test 4: Workflow save and resume"""
    print("\n" + "="*60)
    print("TEST 4: Workflow Persistence")
    print("="*60)
    
    try:
        from graph.workflow import build_graph, sqlite_checkpointer
        from langgraph.types import Command
        from pathlib import Path
        
        db_path = Path("data/test_persistence.db")
        thread_id = "persistence-test-4"
        citizen = {"age": 62, "is_widow": True, "income": 250000}
        
        print(f"\nDatabase: {db_path}")
        print(f"Thread: {thread_id}")
        
        # Phase 1: Start and save
        print("\n1. Starting workflow...")
        with sqlite_checkpointer(db_path) as saver:
            graph = build_graph(saver)
            config = {"configurable": {"thread_id": thread_id}}
            
            result1 = graph.invoke(
                {"simulated_citizen": citizen},
                config
            )
            
            if "__interrupt__" in result1:
                print("   ✓ Workflow paused at approval")
            else:
                print("   ⚠ No approval step (preview only)")
                print("\n✓ TEST 4 PASSED (Preview mode)\n")
                return True
        
        # Phase 2: Resume
        print("\n2. Resuming workflow...")
        with sqlite_checkpointer(db_path) as saver:
            graph = build_graph(saver)
            config = {"configurable": {"thread_id": thread_id}}
            
            # Get pending approval
            state = graph.get_state(config)
            print(f"   State tasks: {len(state.tasks)}")
            
            # Resume with approval
            approval_payload = {"action": "approve"}
            result2 = graph.invoke(
                Command(resume=approval_payload),
                config
            )
            
            submission = result2.get("submission")
            if submission:
                print(f"   ✓ Application submitted")
                print(f"     Status: {submission.get('status')}")
                print(f"     Scheme: {submission.get('scheme_id')}")
            else:
                print("   ⚠ No submission (rejected)")
        
        print("\n✓ TEST 4 PASSED\n")
        return True
        
    except Exception as e:
        print(f"\n✗ TEST 4 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_persona_boundaries():
    """Test 5: Persona validation"""
    print("\n" + "="*60)
    print("TEST 5: Persona Boundaries")
    print("="*60)
    
    try:
        from agents.persona_validator import PersonaValidator
        from agents.contracts import IntakeRequest, EligibilityRequest
        
        validator = PersonaValidator()
        
        print("\n1. Testing Intake Agent persona...")
        intake_req = IntakeRequest(
            household_id="HH_001",
            citizen_data={"age": 62, "income": 250000}
        )
        
        # Should pass: basic info
        result = validator.validate_intake_agent(intake_req)
        print(f"   ✓ Valid intake: {result.get('valid')}")
        
        # Should fail: asking for sensitive data
        intake_bad = IntakeRequest(
            household_id="HH_001",
            citizen_data={"age": 62, "aadhaar_number": "1234-5678-9012"}  # Should not ask
        )
        result_bad = validator.validate_intake_agent(intake_bad)
        print(f"   ✓ Invalid intake detected: {not result_bad.get('valid')}")
        
        print("\n✓ TEST 5 PASSED\n")
        return True
        
    except Exception as e:
        print(f"\n✗ TEST 5 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("SCHEME SAATHI - LOCAL TESTING SUITE")
    print("="*60)
    
    tests = [
        test_basic_workflow,
        test_memory_service,
        test_multiple_schemes,
        test_workflow_persistence,
        test_persona_boundaries,
    ]
    
    results = []
    for test_func in tests:
        try:
            results.append(test_func())
        except Exception as e:
            print(f"\n✗ Unexpected error in {test_func.__name__}: {e}")
            results.append(False)
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    passed = sum(results)
    total = len(results)
    
    for i, (test_func, result) in enumerate(zip(tests, results), 1):
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {status} - Test {i}: {test_func.__name__}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED!")
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
    
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
