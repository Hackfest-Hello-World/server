- Runs on port `5003`.
- Endpoints:
  - `/home`: Aggregates sentiment data from Twitter, Instagram, and YouTube.

---

## Example Workflow

### Step-by-Step Process:

1. **Start Individual Services**:
    - Start Twitter (`api.py` in `Twitter/`).
    - Start Instagram (`api.py` in `Instagram/`).
    - Start YouTube (`api.py` in `YouTube/`).

2. **Authenticate YouTube**:
    Visit `http://localhost:5002/authorize` to authenticate via Google OAuth.

3. **Access Aggregated Dashboard**:
    Visit `http://localhost:5003/home` to view overall sentiment statistics.
