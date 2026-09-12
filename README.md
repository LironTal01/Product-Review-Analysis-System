<div align="center">

# PRAS

### Product Review Analysis System

**From an Amazon product link to evidence-grounded buying insights.**

PRAS retrieves customer reviews, removes noisy and duplicate data, selects representative evidence with semantic embeddings, and produces a structured purchase analysis through a FastAPI application.

<p>
  <img src="https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.11">
  <img src="https://img.shields.io/badge/FastAPI-API-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/OpenAI-GPT--5--nano-412991?style=flat-square&logo=openai&logoColor=white" alt="OpenAI GPT-5-nano">
  <img src="https://img.shields.io/badge/Redis-24h_cache-DC382D?style=flat-square&logo=redis&logoColor=white" alt="Redis">
  <img src="https://img.shields.io/badge/Docker-containerized-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/Azure-Container_Apps-0078D4?style=flat-square&logo=microsoftazure&logoColor=white" alt="Azure Container Apps">
</p>

[Demo](#demo) · [Architecture](#architecture) · [Technical Design](#technical-design) · [Technology Stack](#technology-stack) · [Run Locally](#run-locally) · [Deploy to Azure](#deploy-to-azure)

</div>

## Demo

<p align="center">
  <img src="docs/images/pras-demo.webp" width="720" alt="PRAS demo: submit an Amazon URL and receive a review analysis">
</p>

<p align="center"><sub>Recorded from the working PRAS interface: URL submission → analysis → summary, recommendation, confidence, pros, and cons.</sub></p>

<details>
<summary><strong>View static screenshots</strong></summary>
<br>
<p align="center">
  <img src="docs/images/pras-input.webp" width="48%" alt="Amazon product URL input and review-count selector">
  <img src="docs/images/pras-analysis.webp" width="48%" alt="Generated summary, purchase recommendation, and confidence score">
</p>
<p align="center">
  <img src="docs/images/pras-insights.webp" width="80%" alt="Pros, cons, and recurring issues from low-rated reviews">
</p>
</details>

## At a Glance

| Input | Processing | Output |
|---|---|---|
| Amazon product URL and a target of 25–250 reviews | Scraping → cleaning → statistics → embeddings → semantic selection → LLM analysis | Review consensus, buy signal, pros, cons, recurring complaints, and analysis confidence |

PRAS is intentionally more than a prompt wrapped in a web page. The LLM is one stage inside a larger data and software-engineering pipeline.

## Engineering Highlights

- **Representative evidence instead of prompt dumping.** Review texts are embedded with OpenAI's `text-embedding-3-small`; NumPy computes the collection centroid and scikit-learn ranks reviews by cosine similarity.
- **Confidence is deterministic.** The displayed score is calculated from review count, rating spread, and average text depth. It is not a confidence value invented by the language model.
- **Two Redis cache layers.** Raw review payloads and completed analyses are cached separately for 24 hours using the ASIN and requested review count.
- **Real acquisition and preprocessing.** ScraperAPI retrieves Amazon pages, Beautiful Soup parses review and product metadata, and the cleaning pipeline validates ratings, removes empty or promotional rows, and deduplicates canonicalized text.
- **Resilient external-service boundaries.** Cache failures degrade to fresh computation, invalid cache records are ignored, the LLM call is retried, and deterministic statistics provide a safe fallback.
- **Production-oriented delivery.** The application includes a typed FastAPI API, responsive browser UI, structured logging, automated tests, a non-root Docker image, health checks, and Azure deployment scripts.

## Architecture

```mermaid
flowchart TB
    UI["Browser UI"] -->|"POST URL + limit"| API["FastAPI"]
    API -->|"validate + extract ASIN"| RESULT_CACHE{"Redis result cache?"}
    RESULT_CACHE -->|"hit: read JSON"| OUTPUT["JSON result"]
    RESULT_CACHE -->|"miss: run pipeline"| CORE["Analyzer"]

    CORE -->|"look up raw reviews"| REVIEW_CACHE{"Redis review cache?"}
    REVIEW_CACHE -->|"hit: load reviews"| CLEAN["Clean reviews"]
    REVIEW_CACHE -->|"miss: fetch pages"| SCRAPER["ScraperAPI"]
    SCRAPER -->|"return Amazon HTML"| PARSER["Beautiful Soup"]
    PARSER -->|"parse + cache reviews"| CLEAN

    CLEAN -->|"ratings + text"| METRICS["Stats + confidence"]
    CLEAN -->|"text batches"| EMBEDDINGS["OpenAI embeddings"]
    EMBEDDINGS -->|"vectors"| RANK["Centroid + cosine"]
    RANK -->|"representative Top-K"| LLM["GPT-5-nano"]
    METRICS -->|"aggregate context"| LLM

    LLM -->|"structured JSON"| ASSEMBLE["AnalysisResult"]
    METRICS -->|"deterministic metrics"| ASSEMBLE
    ASSEMBLE -->|"cache for 24h"| OUTPUT
    OUTPUT -->|"render result cards"| UI
```

The result cache and raw-review cache use separate Redis key spaces. On real-data runs, product metadata is retrieved separately so the response can include the title, image, price, Amazon rating, and total review count.

## Technical Design

### 1. Review acquisition

The API validates the URL, extracts the ASIN, and checks the completed-analysis cache. On a miss, the scraper checks the raw-review cache before requesting paginated Amazon pages through ScraperAPI.

The parser collects:

- Review text and rating
- Review date
- Helpful-vote count
- Verified-purchase status
- Product title, image, price, rating, and total review count when available

### 2. Cleaning and statistics

The processing layer removes unusable text, clamps ratings into the valid range, filters explicit promotional spam, and deduplicates normalized review bodies. It then calculates the average rating, 1–5 star distribution, negative-review count, and number of analyzed reviews.

### 3. Semantic review selection

1. Review texts are embedded with `text-embedding-3-small` in batches of up to 150.
2. The mean embedding forms a centroid representing the collection.
3. Cosine similarity ranks every review by its distance from that centroid.
4. The selected context scales with the cleaned dataset: `k = max(20, floor(0.70 × n))`, capped by the number of available reviews.

This reduces redundant context while keeping the LLM grounded in reviews that are representative of the retrieved collection.

### 4. Structured LLM analysis

The representative reviews and aggregate statistics are sent through the OpenAI Responses API. `GPT-5-nano` is the default model, with configuration support for a compatible GPT-5 model.

The analyzer returns normalized JSON containing:

- Review summary
- Pros and cons
- Aspect-level sentiment
- Buy / don't-buy recommendation
- Confidence explanation
- Summary of complaints in 1–3 star reviews

### 5. Deterministic confidence

The confidence score is normalized to `[0, 1]` and calculated as:

`confidence = 0.50 × review_count_factor + 0.30 × rating_spread_factor + 0.20 × text_quality_factor`

This score measures the strength of the available review evidence, not the probability that a product is objectively good.

## Technology Stack

| Layer | Technology | Role |
|---|---|---|
| Language | **Python 3.11+** | Application and analysis pipeline |
| API | **FastAPI, Pydantic, Uvicorn** | Typed request validation, JSON endpoints, and OpenAPI docs |
| Language model | **GPT-5-nano, OpenAI Responses API** | Structured review synthesis and recommendation |
| Embeddings | **text-embedding-3-small** | Vector representation of review text |
| Semantic ranking | **NumPy, scikit-learn** | Centroid calculation and cosine similarity |
| Retrieval | **ScraperAPI, Requests** | Live Amazon page acquisition |
| Parsing | **Beautiful Soup** | Review and product-metadata extraction |
| Cache | **Redis** | Raw-review and final-analysis caches with 24-hour TTL |
| Frontend | **HTML, CSS, JavaScript** | Responsive, framework-free browser interface |
| Infrastructure | **Docker, Azure Container Apps, Azure Container Registry** | Containerization and cloud deployment |
| Quality | **pytest, pytest-cov, Ruff, pre-commit** | Tests, coverage tooling, linting, and formatting |

## API

### `POST /api/analyze`

<details>
<summary><strong>View request and response example</strong></summary>
<br>

Request:

```json
{
  "amazon_url": "https://www.amazon.com/dp/B08N5WRWNW",
  "max_reviews": 100
}
```

Example response shape:

```json
{
  "product_title": "Example product",
  "amazon_rating": 4.2,
  "total_review_count": 1552,
  "summary_text": "Customers generally praise...",
  "recommendation": "Recommended",
  "confidence_score": 0.82,
  "confidence_explanation": "Confidence is supported by...",
  "pros": ["Strong performance", "Good value"],
  "cons": ["Limited customization"],
  "negative_summary": "Lower-rated reviews most often mention...",
  "total_reviews_analyzed": 100
}
```

</details>

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/` | Browser interface |
| `GET` | `/health` | Docker and Azure liveness check |
| `POST` | `/api/analyze` | Product-review analysis |
| `GET` | `/docs` | Interactive OpenAPI documentation |

## Run Locally

### Prerequisites

- Python 3.11+
- OpenAI API key for embeddings and LLM analysis
- ScraperAPI key for live Amazon review retrieval
- Redis, optional but recommended for caching

### Installation

```bash
git clone https://github.com/LironTal01/Product-Review-Analysis-System.git
cd Product-Review-Analysis-System

python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Copy the versioned environment template, then add your credentials:

```bash
cp .env.example .env
```

`.env` is ignored by Git. Keep `ALLOW_MOCK_FALLBACK=false` when working with live Amazon data.

Run the application:

```bash
uvicorn src.main:app --reload
```

Open [http://localhost:8000](http://localhost:8000) for the application or [http://localhost:8000/docs](http://localhost:8000/docs) for the API explorer.

For a local demonstration without live Amazon retrieval, set `ALLOW_MOCK_FALLBACK=true`. Mock fallback is disabled by default so unavailable live data is not silently presented as scraped data.

### Docker Compose

The local stack starts PRAS, password-protected Redis, and RedisInsight:

```bash
cp .env.example .env
# Add OPENAI_API_KEY and SCRAPER_API_KEY to .env
docker compose up --build
```

Open the app at [http://localhost:8000](http://localhost:8000), the API explorer at [http://localhost:8000/docs](http://localhost:8000/docs), or RedisInsight at [http://localhost:5540](http://localhost:5540).

To run only the application container:

```bash
docker build -t pras .
docker run --rm -p 8000:8000 --env-file .env pras
```

## Deploy to Azure

The deployment script builds the image in Azure Container Registry and creates or updates an Azure Container App. API credentials and an optional managed Redis URL are stored as Container App secrets rather than plain environment values.

```bash
export ACR_NAME=yourgloballyuniqueacrname
export OPENAI_API_KEY=your_openai_api_key
export SCRAPER_API_KEY=your_scraperapi_key
# Optional: export REDIS_URL=your_managed_redis_url

./scripts/azure_deploy.sh
```

`ACR_NAME` is explicit so repeated deployments update the same registry instead of creating randomly named resources. The script validates required configuration and prints the deployed application and health-check URLs.

## Testing and Quality

The current suite defines 64 test functions across seven modules, covering URL parsing, review cleaning, statistics, confidence scoring, Redis behavior, API validation, cache flow, and the complete analysis pipeline. External network services are mocked in automated tests.

```bash
pytest
pytest --cov=src --cov-report=term-missing
ruff check .
ruff format --check .
```

Test-driven development was used for the URL parser and statistics calculator, with additional tests-first work around review cleaning and confidence scoring.

<details>
<summary><strong>View repository structure</strong></summary>
<br>

```text
src/
├── analysis/       # Embeddings, semantic ranking, LLM analysis, confidence
├── core/           # End-to-end pipeline orchestration
├── data/           # Amazon scraping and optional mock data
├── db/             # Redis cache helpers
├── models/         # Typed domain and response models
├── processing/     # Review cleaning and statistics
├── static/         # Browser interface
├── utils/          # Configuration, logging, and URL parsing
└── main.py         # FastAPI application

tests/              # Unit, integration, API, and cache tests
scripts/            # Azure deployment and teardown
```

</details>

## Transparency and Limitations

- Live retrieval depends on Amazon page structure, regional availability, and ScraperAPI responses, so the number of accessible reviews can be lower than requested.
- Centroid-based selection prioritizes representative reviews; minority opinions may receive less weight and are partially preserved through rating statistics and the separate low-rated-review analysis.
- LLM-generated wording can vary. Statistics and the confidence score are calculated deterministically by the application.
- PRAS is an independent academic project and is not affiliated with or endorsed by Amazon, OpenAI, ScraperAPI, or Microsoft.

## Authors

Developed as a two-person academic project by **Liron Tal** and **Shani Rahamim**.

- **Liron Tal** — originated the product concept and led the architecture and primary end-to-end implementation.
- **Shani Rahamim** — contributed to infrastructure, deployment, testing, and interface refinement.

