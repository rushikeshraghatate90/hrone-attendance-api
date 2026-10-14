# HROne Employee Attendance & Analytics API

FastAPI and MongoDB API for employee management, attendance tracking, regularization, and analytics.

## Setup

1. Create and activate a Python virtual environment.
2. Install dependencies with `pip install -r requirements.txt`.
3. Configure `MONGO_URI` and `MONGO_DB` in your local `.env` file.
4. Start the API with `uvicorn app.main:app --reload --port 8000`.
5. Open `http://127.0.0.1:8000/docs` to explore the API.

MongoDB 6.0 or newer is required.

## Implementation notes

See `REVIEW.md` for the starter-code review and `DECISIONS.md` for implementation decisions. Any remaining limitations will be documented after testing.