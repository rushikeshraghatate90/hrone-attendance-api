# 🏢 HROne Attendance Analytics API

<p align="center">
  A RESTful employee attendance management and analytics platform built with FastAPI and MongoDB. Track employee attendance, analyze workforce patterns, generate department summaries, and inspect database query performance.
</p>

<p align="center">
  <a href="https://hrone-attendance-api-9cfu.onrender.com"><img src="https://img.shields.io/badge/🚀_LIVE_DEMO-Visit_API-46E3B7?style=for-the-badge" alt="Live Demo"/></a>
  <a href="https://hrone-attendance-api-9cfu.onrender.com/docs"><img src="https://img.shields.io/badge/API-SWAGGER_UI-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="Swagger UI"/></a>
  <a href="https://github.com/rushikeshraghatate90/hrone-attendance-api"><img src="https://img.shields.io/badge/GITHUB-REPOSITORY-181717?style=for-the-badge&logo=github&logoColor=white" alt="GitHub Repository"/></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/FastAPI-REST_API-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/MongoDB-Database-47A248?style=flat-square&logo=mongodb&logoColor=white" alt="MongoDB"/>
  <img src="https://img.shields.io/badge/PyMongo-Database_Driver-4EA94B?style=flat-square" alt="PyMongo"/>
  <img src="https://img.shields.io/badge/Pydantic-Validation-E92063?style=flat-square" alt="Pydantic"/>
  <img src="https://img.shields.io/badge/Docker-Containerization-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker"/>
  <img src="https://img.shields.io/badge/Render-Deployment-46E3B7?style=flat-square&logo=render&logoColor=black" alt="Render"/>
</p>

---

## 📌 Overview

The **HROne Attendance Analytics API** is a backend application developed to manage employee records, record daily attendance, and generate workforce analytics.

Built using FastAPI and MongoDB, the application provides REST endpoints for employee management, punch-in and punch-out operations, attendance corrections, monthly analytics, department summaries, late-arrival rankings, and attendance trends.

The project also incorporates MongoDB indexes, duplicate-record protection, pagination, and query execution-plan inspection to support data integrity and database performance analysis.

## ✨ Features

- **Employee Management:** Register employees and retrieve employee records.
- **Attendance Tracking:** Record employee punch-in and punch-out events.
- **Duplicate Prevention:** Use a unique employee-and-date database constraint to prevent duplicate daily attendance records.
- **Attendance Filtering:** Query attendance records with filters and pagination.
- **Attendance Corrections:** Update attendance records while maintaining a change history.
- **Monthly Analytics:** Calculate monthly attendance statistics, late arrivals, and overtime.
- **Department Analytics:** Generate department-level attendance summaries and headcount statistics.
- **Late-Arrival Leaderboard:** Rank employees by recorded late minutes.
- **Attendance Trends:** Analyze department attendance over a specified date range.
- **Database Performance Inspection:** Examine query execution plans and index usage through an administrative endpoint.
- **Interactive API Documentation:** Explore endpoints and test requests using Swagger UI.
- **Docker Support:** Build and run the API in a container.
- **Cloud Deployment:** Configure the application for deployment on Render.

## 🛠️ Technology Stack

| Category | Technologies |
|---|---|
| Programming language | Python 3.12 |
| API framework | FastAPI |
| Database | MongoDB |
| Database driver | PyMongo |
| Data validation | Pydantic |
| Configuration | python-dotenv and environment variables |
| API documentation | OpenAPI and Swagger UI |
| Containerization | Docker |
| Deployment | Render |
| Testing and debugging | Swagger UI, HTTP requests, database execution statistics |

## 🌐 Live Application

| Resource | Link |
|---|---|
| API Base URL | [Open API](https://hrone-attendance-api-9cfu.onrender.com) |
| Swagger UI | [Explore and test endpoints](https://hrone-attendance-api-9cfu.onrender.com/docs) |
| Health Check | [Check API status](https://hrone-attendance-api-9cfu.onrender.com/health) |
| GitHub Repository | [View source code](https://github.com/rushikeshraghatate90/hrone-attendance-api) |

**Note:** The deployment URLs are provided for convenience. Confirm that the Render service is running and up to date before relying on the live endpoints.

## 📋 API Endpoints

### Health and Employee Management

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Check API health |
| `POST` | `/employees` | Register an employee |
| `GET` | `/employees` | Retrieve employee records |

### Attendance Management

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/attendance/punch-in` | Record employee punch-in |
| `GET` | `/attendance` | Retrieve attendance records with supported filters |
| `POST` | `/attendance/punch-out` | Record employee punch-out |
| `PATCH` | `/attendance/{emp_code}/{day}` | Correct an attendance record |

### Analytics

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/analytics/employees/{emp_code}/monthly` | Retrieve monthly employee attendance analytics |
| `GET` | `/analytics/departments/summary` | Generate department attendance summaries |
| `GET` | `/analytics/leaderboard/late` | Retrieve late-arrival rankings |
| `GET` | `/analytics/departments/{department}/trend` | Analyze department attendance trends |

### Database Performance

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/admin/explain/{endpoint}` | Inspect query execution plans for supported endpoints |

Refer to the [Swagger documentation](https://hrone-attendance-api-9cfu.onrender.com/docs) for request schemas, available parameters, and response formats.

## 🗄️ Database Design

The application separates employee information from attendance records.

- **Employees:** Stores employee details used for employee management and department-level analysis.
- **Attendance Records:** Stores daily attendance information associated with employee codes and dates.

MongoDB indexes support frequently used query patterns. A unique employee-and-date index enforces the daily attendance uniqueness rule at the database level, helping protect against concurrent duplicate punch-in requests.

Department summaries start from employee records and incorporate attendance data, allowing employees without attendance logs to remain included in department headcount calculations.

## ⚙️ Prerequisites

Before running the application locally, install:

- Python 3.12
- MongoDB 6.0 or newer, or a compatible MongoDB Atlas deployment
- Git
- Docker Desktop, if using the containerized setup

You also need a MongoDB database connection string and appropriate database permissions.

## 🚀 Local Installation and Setup

### 1. Clone the repository

```bash
git clone https://github.com/rushikeshraghatate90/hrone-attendance-api.git
cd hrone-attendance-api
```

### 2. Create a virtual environment

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks virtual environment activation, you can invoke the virtual environment's Python executable directly instead.

### 3. Install dependencies

```bash
python -m pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the project root:

```env
MONGO_URI=your_mongodb_connection_string
MONGO_DB=attendance_db
```

Replace the placeholder with your own MongoDB connection string.

For MongoDB Atlas, ensure that your database user has the necessary permissions and that your network access configuration permits connections from your development environment.

**Security best practices:**

- Never commit `.env` files or database credentials to GitHub.
- Keep production credentials in Render's environment-variable settings.
- Use a database account with only the permissions the application requires.
- If credentials have been exposed, rotate them before deploying.

### 5. Start the API server

```bash
python -m uvicorn app.main:app --reload --port 8000
```

### 6. Access the application

Once the server starts, open:

- **Swagger UI:** http://127.0.0.1:8000/docs
- **OpenAPI schema:** http://127.0.0.1:8000/openapi.json
- **Health check:** http://127.0.0.1:8000/health

Use Swagger UI to submit requests, inspect response schemas, and test the API interactively.

## 🐳 Docker Setup

The repository includes a `Dockerfile` for building a container image and a `.dockerignore` file for excluding local development files and secrets from the build context.

### 1. Build the Docker image

Run the following command from the repository root:

```bash
docker build -t hrone-attendance-api:latest .
```

### 2. Run the container

On Windows PowerShell, with a correctly configured local `.env` file:

```powershell
docker run --rm -p 8000:8000 --env-file .env hrone-attendance-api:latest
```

The container exposes port `8000`. Open http://127.0.0.1:8000/docs to test the API.

The application reads the MongoDB configuration from environment variables, so database credentials do not need to be embedded in the Docker image.

## ☁️ Deployment

The application is configured for container-based deployment.

For Render deployment:

1. Push the project to GitHub.
2. Create a new Render web service connected to the repository.
3. Select the Docker runtime.
4. Set the repository root as the build context because the `Dockerfile` is in the repository root.
5. Configure `MONGO_URI` and `MONGO_DB` in the service's environment variables.
6. Deploy the service and inspect the build and runtime logs.
7. Verify the health endpoint and test the API through Swagger UI.

Do not commit production credentials or add them to the Dockerfile.

## 🧪 Testing and Validation

During development, the API was manually exercised through Swagger UI and local HTTP requests.

The scenarios tested included:

- Creating an employee
- Recording a successful punch-in
- Rejecting a duplicate punch-in
- Handling punch-out for an unknown employee
- Filtering attendance records
- Correcting an attendance record
- Retrieving monthly attendance analytics
- Generating department summaries
- Retrieving the late-arrival leaderboard
- Querying department attendance trends
- Inspecting database execution plans

These are manually tested scenarios, not a claim of complete automated test coverage. Additional automated integration tests, concurrency tests, and load tests would improve confidence in production readiness.

## 📈 Database Performance and Design Decisions

The implementation uses MongoDB indexes to support common query patterns and enforce data integrity. Sorting and pagination are applied within database queries rather than loading all matching attendance records into application memory.

The explain endpoint provides execution-plan information for supported query patterns. For the department trend endpoint, the inspected plan uses a representative collection-backed pipeline rather than explaining the complete trend aggregation pipeline. This distinction is documented to avoid overstating the scope of the analysis.

Further optimization should be guided by representative workloads, query execution statistics, and load testing.

## 📚 Project Documentation

- **[REVIEW.md](REVIEW.md):** Review of the starter implementation, identified defects, and corresponding fixes.
- **[DECISIONS.md](DECISIONS.md):** Design choices, index strategy, punch-in concurrency, leaderboard ties, headcount handling, and scalability considerations.

## 🔮 Potential Improvements

- Add automated unit and integration tests.
- Test concurrent punch-in requests under load.
- Benchmark analytics queries against larger datasets.
- Expand execution-plan inspection to cover complete aggregation pipelines where supported.
- Add structured logging and monitoring for production debugging.
- Tune indexes based on measured query workloads.
- Add authentication and role-based authorization before exposing administrative functionality publicly.

## 👨‍💻 Author

Developed as part of the HROne Software Engineer Trainee assignment.

---

<p align="center">
  Built with Python, FastAPI, and MongoDB.
</p>
