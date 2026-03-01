# Priority Action Items - ch.ai Improvements

**Date:** 2026-03-01
**Status:** Ready for Implementation
**Estimated Total Effort:** 30 days (6 weeks)

---

## Critical Issues - Start Immediately (Week 1)

### 🔴 P0: Production Blockers

These issues **must** be resolved before production deployment:

#### 1. Add Logging Infrastructure (2 days)
**Problem:** Zero logging in entire codebase - impossible to debug production issues

**Action Items:**
- [ ] Create `src/chai/logging_config.py` with structured logging setup
- [ ] Add logger to `src/chai/api.py` (all endpoints)
- [ ] Add logger to `src/chai/core/team.py` (task execution)
- [ ] Add logger to `src/chai/core/agent.py` (agent runs)
- [ ] Add logger to `src/chai/sessions/db.py` (database operations)
- [ ] Configure log rotation (10MB per file, 5 backups)
- [ ] Add startup event to configure logging level from env var

**Files to Modify:**
```
src/chai/logging_config.py (NEW)
src/chai/api.py
src/chai/core/team.py
src/chai/core/agent.py
src/chai/sessions/db.py
```

**Validation:**
```bash
# After implementation
chai api  # Should log startup message
curl http://localhost:8000/api/health  # Should log request
cat ~/.chai/logs/api.log  # Should contain structured logs
```

---

#### 2. Create Custom Exception Hierarchy (1 day)
**Problem:** 109+ bare `except Exception` catches, no way to handle specific errors

**Action Items:**
- [ ] Create `src/chai/exceptions.py` with base `ChaiError` class
- [ ] Add specific exceptions: `ProviderAuthError`, `TaskError`, `DatabaseError`, `ValidationError`
- [ ] Replace `ValueError("API key missing")` with `ProviderAuthError(...)`
- [ ] Replace `RuntimeError(...)` in task.py with `TaskError(...)`
- [ ] Add FastAPI exception handler for `ChaiError`
- [ ] Update error responses to include error_type, message, details

**Files to Modify:**
```
src/chai/exceptions.py (NEW)
src/chai/api.py (add exception handler)
src/chai/providers/anthropic_api.py (replace ValueError)
src/chai/providers/openai_api.py (replace ValueError)
src/chai/core/task.py (replace RuntimeError)
```

**Example Change:**
```python
# BEFORE
if not api_key:
    raise ValueError("API key missing")

# AFTER
if not api_key:
    raise ProviderAuthError(
        "Anthropic API key not configured",
        details={"help": "Set with: chai config set keys.anthropic_api YOUR_KEY"}
    )
```

---

#### 3. Add API Input Validation (1 day)
**Problem:** No validation on WebSocket messages, path traversal risk

**Action Items:**
- [ ] Create Pydantic model `StreamRequest` with validators
- [ ] Validate prompt: min_length=1, max_length=10000
- [ ] Validate project_dir: check exists, no ".." in path
- [ ] Add validation to `/api/teams/{name}/run` endpoint
- [ ] Add validation to WebSocket handler
- [ ] Return 400 Bad Request for validation failures (not 500)

**Files to Modify:**
```
src/chai/api.py (lines 24-27, 193-198)
```

**Example Implementation:**
```python
from pydantic import BaseModel, Field, validator

class StreamRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=10000)
    project_dir: Optional[str] = None

    @validator("prompt")
    def validate_prompt(cls, v):
        if not v.strip():
            raise ValueError("Prompt cannot be empty")
        return v.strip()

    @validator("project_dir")
    def validate_path(cls, v):
        if v and ".." in str(Path(v)):
            raise ValueError("Path traversal not allowed")
        return v
```

---

#### 4. Fix Database Connection Pool (1 day)
**Problem:** Opens new connection on every query, async/sync bridge fails in threads

**Action Items:**
- [ ] Remove `_run()` sync/async bridge method (lines 35-41)
- [ ] Make Database fully async or fully sync (recommend: fully async)
- [ ] Implement connection pool (5 connections)
- [ ] Add `connect()` and `close()` methods
- [ ] Call `await db.connect()` once at startup
- [ ] Add `_ensure_initialized()` to run schema init only once
- [ ] Add connection health check method

**Files to Modify:**
```
src/chai/sessions/db.py (major refactor)
src/chai/api.py (add startup event for db.connect())
```

**Key Changes:**
```python
# Remove this anti-pattern:
def _run(self, coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)

# Replace all methods like:
def create_session(self, session_id: str):
    return self._run(self._create_session(session_id))

# With fully async:
async def create_session(self, session_id: str):
    await self._ensure_initialized()
    conn = await self._get_connection()
    # ... rest of method
```

---

#### 5. Fix Memory Leak in API (2 hours - Quick Win!)
**Problem:** `_active_runs` dict grows unbounded, will OOM in production

**Action Items:**
- [ ] Create `RunCache` class with LRU eviction (max 100 items)
- [ ] Replace `_active_runs: Dict` with `RunCache()` instance
- [ ] Add TTL-based cleanup (remove runs older than 1 hour)
- [ ] Add background task to cleanup every 10 minutes
- [ ] Log cache size and evictions

**Files to Modify:**
```
src/chai/api.py (lines 78, 133-136)
```

**Implementation:**
```python
from collections import OrderedDict

class RunCache:
    def __init__(self, max_size: int = 100):
        self._cache = OrderedDict()
        self._max_size = max_size

    def add(self, run_id: str, data: Dict[str, Any]):
        if len(self._cache) >= self._max_size:
            oldest = self._cache.popitem(last=False)
            logger.info(f"Evicted run: {oldest[0]}")
        self._cache[run_id] = data

    def get(self, run_id: str) -> Optional[Dict[str, Any]]:
        return self._cache.get(run_id)

_active_runs = RunCache(max_size=100)  # ✅ Bounded
```

---

## Week 1 Checklist

**Day 1:**
- [ ] Set up logging infrastructure
- [ ] Add logging to api.py
- [ ] Add logging to core/team.py

**Day 2:**
- [ ] Finish logging in all core modules
- [ ] Test log rotation and formatting

**Day 3:**
- [ ] Create exceptions.py
- [ ] Add FastAPI exception handler
- [ ] Replace exceptions in providers/

**Day 4:**
- [ ] Add API input validation
- [ ] Fix memory leak (RunCache)
- [ ] Add validation tests

**Day 5:**
- [ ] Refactor database connection pooling
- [ ] Test database under concurrent load
- [ ] Code review and testing

---

## High Priority - Testing (Weeks 2-3)

### 🟡 P1: Production Readiness

#### 6. Create API Test Suite (3 days)
**Current:** 0% coverage on api.py (183 lines)
**Target:** 80%+ coverage

**Action Items:**
- [ ] Create `tests/api/` directory structure
- [ ] Test `/api/health` endpoint
- [ ] Test `/api/teams` endpoint
- [ ] Test `/api/teams/{name}/run` with mock harness
- [ ] Test WebSocket streaming
- [ ] Test error scenarios (missing config, invalid input)
- [ ] Test concurrent requests
- [ ] Add pytest fixtures for TestClient and mock dependencies

**Files to Create:**
```
tests/api/__init__.py
tests/api/test_health.py
tests/api/test_teams.py
tests/api/test_websocket.py
tests/api/test_errors.py
tests/api/conftest.py (fixtures)
```

---

#### 7. Create Database Test Suite (2 days)
**Current:** 0% coverage on sessions/db.py (237 lines)
**Target:** 80%+ coverage

**Action Items:**
- [ ] Create `tests/sessions/test_database.py`
- [ ] Test session creation and retrieval
- [ ] Test message storage and retrieval
- [ ] Test concurrent writes (10+ parallel messages)
- [ ] Test transaction rollback on error
- [ ] Test connection pool exhaustion
- [ ] Test database file permissions errors

---

#### 8. Fix WebSocket Race Condition (2 days)
**Problem:** Using sync queue with async, 1-second timeout can drop events

**Action Items:**
- [ ] Replace `std_queue.Queue` with `asyncio.Queue`
- [ ] Rewrite `_stream_harness` to be fully async
- [ ] Remove polling loop with timeout
- [ ] Use `await queue.get()` instead of `asyncio.to_thread`
- [ ] Add tests for event delivery under load
- [ ] Test WebSocket disconnect handling

---

#### 9. Integration Tests (3 days)
**Current:** No end-to-end tests

**Action Items:**
- [ ] Create `tests/integration/` directory
- [ ] Test full team run: prompt → task decomposition → execution → result
- [ ] Test multi-agent coordination with dependencies
- [ ] Test feedback loop: task → review → fix → complete
- [ ] Test validation gate: task → test → fix → retry
- [ ] Test plan execution workflow
- [ ] Mark integration tests with `@pytest.mark.integration`

---

## Weeks 2-3 Checklist

**Week 2:**
- [ ] API test suite complete (80%+ coverage)
- [ ] Database test suite complete (80%+ coverage)
- [ ] Fix WebSocket race condition
- [ ] 3+ integration tests passing

**Week 3:**
- [ ] 5+ integration test scenarios
- [ ] Load testing (100 concurrent requests)
- [ ] Memory leak verification (24-hour run)
- [ ] Overall coverage ≥ 60%

---

## Medium Priority - Code Quality (Weeks 4-6)

### 🟢 P2: Long-term Maintainability

#### 10. Refactor Large Files (5 days)
**Current:** cli.py (504 lines), filesystem.py (365 lines)

**Action Items:**
- [ ] Split `cli.py` into `cli/commands/` modules
- [ ] Split `filesystem.py` into `tools/filesystem/` modules
- [ ] Extract shared utilities
- [ ] Update imports
- [ ] Ensure tests still pass

---

#### 11. Complete Type Hints (3 days)
**Current:** ~70% coverage

**Action Items:**
- [ ] Add return types to all functions
- [ ] Add parameter types where missing
- [ ] Configure mypy strict mode
- [ ] Fix all mypy errors
- [ ] Add type hints to tool methods

---

#### 12. Implement Dependency Injection (4 days)
**Action Items:**
- [ ] Create `Container` class for DI
- [ ] Refactor `Team` to accept injected dependencies
- [ ] Refactor `Harness` to use DI container
- [ ] Add interfaces (Protocols) for main components
- [ ] Update tests to use mocked dependencies

---

## Success Metrics

### Week 1 Success Criteria
```
✅ Logging: All modules have logger configured
✅ Exceptions: 80%+ use custom exception types
✅ Validation: All API inputs validated
✅ Database: Connection pool working, no sync/async bridge
✅ Memory: RunCache implemented, memory bounded
```

### Week 2-3 Success Criteria
```
✅ Test Coverage: Overall ≥ 60%
✅ API Coverage: ≥ 80%
✅ Database Coverage: ≥ 80%
✅ Integration Tests: 5+ scenarios passing
✅ Memory Test: 24-hour run stays under 500MB
```

### Week 4-6 Success Criteria
```
✅ File Size: All files < 300 lines
✅ Type Hints: mypy --strict passes
✅ Dependency Injection: Implemented for core components
✅ Code Duplication: < 5%
✅ Overall Coverage: ≥ 70%
```

---

## Quick Wins (< 2 hours each)

These can be done anytime for immediate improvement:

1. **Add Constants File** (30 min)
   ```python
   # src/chai/constants.py
   class AgentDefaults:
       MAX_ITERATIONS = 10
       MAX_CONSECUTIVE_FAILURES = 3
       DEFAULT_MAX_TOKENS = 8192
   ```

2. **Add .coveragerc** (15 min)
   ```ini
   [run]
   source = src/chai
   [report]
   fail_under = 70
   ```

3. **Add mypy.ini** (15 min)
   ```ini
   [mypy]
   python_version = 3.10
   warn_return_any = True
   ```

4. **Add Pre-commit Hooks** (30 min)
   - Install: `pip install pre-commit`
   - Configure: black, isort, flake8
   - Run: `pre-commit install`

5. **Add Database Health Check** (1 hour)
   ```python
   async def health_check(self) -> bool:
       """Check database connectivity."""
       try:
           await self._connection.execute("SELECT 1")
           return True
       except:
           return False
   ```

---

## Commands to Run

### After Week 1
```bash
# Verify logging
chai api
curl http://localhost:8000/api/health
cat ~/.chai/logs/api.log

# Verify no bare exceptions
grep -r "except Exception:" src/chai/*.py  # Should be minimal

# Verify validation
curl -X POST http://localhost:8000/api/teams/default/run \
  -H "Content-Type: application/json" \
  -d '{"prompt": ""}'  # Should return 400
```

### After Week 2-3
```bash
# Run all tests
pytest -v --cov=src/chai --cov-report=html

# Check coverage
open htmlcov/index.html

# Integration tests only
pytest tests/integration/ -v -m integration

# Load test
locust -f tests/load/locustfile.py --host=http://localhost:8000
```

### After Week 4-6
```bash
# Type checking
mypy src/chai/ --strict

# Code quality
flake8 src/chai/ --max-line-length=120
black src/chai/ --check
isort src/chai/ --check

# Final coverage
pytest --cov=src/chai --cov-fail-under=70
```

---

## Getting Started

### Immediate Next Steps

1. **Read full recommendations:**
   ```bash
   cat docs/IMPROVEMENT_RECOMMENDATIONS.md
   ```

2. **Create feature branch:**
   ```bash
   git checkout -b improvements/week1-critical-fixes
   ```

3. **Start with logging:**
   ```bash
   touch src/chai/logging_config.py
   # Implement as per recommendation
   ```

4. **Test as you go:**
   ```bash
   # After each change
   pytest tests/
   python -m chai.api  # Manual smoke test
   ```

5. **Commit frequently:**
   ```bash
   git commit -m "Add logging infrastructure"
   git commit -m "Create custom exception hierarchy"
   # etc.
   ```

---

## Questions?

**Need clarification on any recommendation?**
- See full details in `docs/IMPROVEMENT_RECOMMENDATIONS.md`
- Check code examples in specific sections
- Review architecture diagrams in `docs/architecture-diagram.md`

**Ready to start?**
Begin with Week 1, Day 1: Logging Infrastructure!

---

**Document Version:** 1.0
**Last Updated:** 2026-03-01
**Owner:** Backend Team
