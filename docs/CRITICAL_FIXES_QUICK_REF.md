# Critical Fixes - Quick Reference Card

**Use this card for immediate implementation guidance**

---

## 🔴 BLOCKER #1: No Logging (2 days)

### Problem
```python
# Current: Zero logging anywhere
# Can't debug production issues
```

### Fix
```python
# src/chai/logging_config.py
import logging
import sys

def setup_logging(level="INFO"):
    logger = logging.getLogger("chai")
    logger.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger

# In every module:
import logging
logger = logging.getLogger("chai.api")

logger.info("Server starting")
logger.error(f"Request failed: {e}")
```

### Files
- Create: `src/chai/logging_config.py`
- Modify: `src/chai/api.py`, `core/team.py`, `core/agent.py`, `sessions/db.py`

---

## 🔴 BLOCKER #2: Memory Leak (2 hours)

### Problem
```python
# Line 78 in api.py
_active_runs: Dict[str, Any] = {}  # ❌ Grows forever

# Line 133
_active_runs[run_id] = data  # ❌ Never removed
```

### Fix
```python
from collections import OrderedDict

class RunCache:
    def __init__(self, max_size=100):
        self._cache = OrderedDict()
        self._max_size = max_size

    def add(self, run_id, data):
        if len(self._cache) >= self._max_size:
            self._cache.popitem(last=False)  # Remove oldest
        self._cache[run_id] = data

    def get(self, run_id):
        return self._cache.get(run_id)

# Replace global dict
_active_runs = RunCache(max_size=100)  # ✅ Bounded
```

### Files
- Modify: `src/chai/api.py` lines 78, 133-136

---

## 🔴 BLOCKER #3: Database Threading Issues (1 day)

### Problem
```python
# Lines 35-41 in sessions/db.py
def _run(self, coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)  # ❌ Crashes in FastAPI
    return loop.run_until_complete(coro)  # ❌ Blocks
```

### Fix
```python
# Option 1: Make fully async
class Database:
    def __init__(self, db_path=None):
        self._db_path = db_path or str(Path.home() / ".chai" / "sessions.db")
        self._pool = []
        self._initialized = False

    async def connect(self):
        if not self._initialized:
            for _ in range(5):  # Pool size
                conn = await aiosqlite.connect(self._db_path)
                self._pool.append(conn)
            self._initialized = True

    async def create_session(self, session_id):
        await self.connect()
        conn = self._pool[0]  # Or implement pool management
        await conn.execute(
            "INSERT OR IGNORE INTO sessions (id, created_at) VALUES (?, ?)",
            (session_id, time.time())
        )
        await conn.commit()

# Remove all _run() calls
# Make all methods async
```

### Files
- Modify: `src/chai/sessions/db.py` (major refactor)
- Modify: `src/chai/api.py` (add startup event)

---

## 🔴 BLOCKER #4: No Input Validation (1 day)

### Problem
```python
# Lines 193-198 in api.py
data = await websocket.receive_text()
payload = json.loads(data) if data else {}
prompt = payload.get("prompt", "")  # ❌ Allows empty
project_dir = payload.get("project_dir")  # ❌ Path traversal risk
```

### Fix
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
        if v is None:
            return v
        if ".." in str(Path(v)):
            raise ValueError("Path traversal not allowed")
        if not Path(v).exists():
            raise ValueError("Directory does not exist")
        return str(Path(v).resolve())

# In WebSocket handler:
try:
    data = await websocket.receive_text()
    request = StreamRequest(**json.loads(data))  # ✅ Validates
except ValidationError as e:
    await websocket.send_json({"type": "error", "data": str(e)})
    return
```

### Files
- Modify: `src/chai/api.py` lines 24-27, 193-198

---

## 🔴 BLOCKER #5: Custom Exceptions (1 day)

### Problem
```python
# Scattered everywhere:
raise ValueError("API key missing")
raise RuntimeError("Task not found")
raise Exception("Unknown error")

# Caught generically:
except Exception:
    pass  # ❌ Can't handle specific errors
```

### Fix
```python
# src/chai/exceptions.py (NEW)
class ChaiError(Exception):
    """Base exception for ch.ai."""
    def __init__(self, message, details=None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

class ProviderAuthError(ChaiError):
    """Provider authentication failed."""
    pass

class TaskError(ChaiError):
    """Task execution error."""
    pass

class DatabaseError(ChaiError):
    """Database operation error."""
    pass

class ValidationError(ChaiError):
    """Input validation error."""
    pass

# Usage:
if not api_key:
    raise ProviderAuthError(
        "API key missing",
        details={"help": "Set with: chai config set keys.anthropic_api KEY"}
    )

# In FastAPI:
@app.exception_handler(ChaiError)
async def chai_error_handler(request, exc):
    logger.error(f"{exc.__class__.__name__}: {exc.message}")
    return JSONResponse(
        status_code=400 if isinstance(exc, ValidationError) else 500,
        content={
            "error_type": exc.__class__.__name__,
            "message": exc.message,
            "details": exc.details
        }
    )
```

### Files
- Create: `src/chai/exceptions.py`
- Modify: `src/chai/api.py` (add handler)
- Modify: `providers/*.py`, `core/*.py` (replace exceptions)

---

## Testing Commands

### After Each Fix
```bash
# Run existing tests
pytest tests/ -v

# Manual smoke test
python -m chai.api &
sleep 2
curl http://localhost:8000/api/health
kill %1

# Check for bare exceptions
grep -r "except Exception:" src/chai/ | grep -v "# OK"
```

### After All Fixes
```bash
# Memory leak test
python -m chai.api &
PID=$!
for i in {1..100}; do
    curl -X POST http://localhost:8000/api/teams/default/run \
      -H "Content-Type: application/json" \
      -d '{"prompt": "test"}' &
done
wait
ps aux | grep $PID  # Check memory usage
kill $PID
```

---

## Validation Checklist

After implementing all 5 blockers:

- [ ] Server logs to console on startup
- [ ] Server logs to file in ~/.chai/logs/
- [ ] Memory stays bounded after 100 requests
- [ ] Database handles 50 concurrent sessions
- [ ] Empty prompt returns 400 error
- [ ] Path traversal attempt blocked
- [ ] All errors have error_type field
- [ ] No bare `except Exception:` in core modules

---

## Time Estimate

| Fix | Time | Can Parallelize? |
|-----|------|------------------|
| 1. Logging | 2 days | No (foundation) |
| 2. Memory Leak | 2 hours | Yes (after #1) |
| 3. Database | 1 day | Yes (after #1) |
| 4. Validation | 1 day | Yes (after #1) |
| 5. Exceptions | 1 day | No (use in #2-4) |

**Sequential:** 5 days
**Optimal (with planning):** 3-4 days

---

## Order of Implementation

**Day 1:**
1. Logging infrastructure
2. Add logging to api.py

**Day 2:**
1. Finish logging in all modules
2. Custom exceptions
3. Memory leak fix

**Day 3:**
1. API validation
2. Database refactor

**Day 4:**
1. Replace exceptions everywhere
2. Testing and validation

**Day 5:**
1. Code review
2. Integration testing
3. Documentation

---

## Help

**Stuck?** Check full docs:
- `docs/IMPROVEMENT_RECOMMENDATIONS.md` - Detailed explanations
- `docs/PRIORITY_ACTION_ITEMS.md` - Full checklists
- `docs/EXECUTIVE_SUMMARY.md` - Overview

**Questions?** All code examples are in the full recommendations document.

---

**Print this card and keep it handy while implementing!**
