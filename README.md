# TRACE – AI Memory Engine

**A Persistent and Selective Memory Layer for Large Language Models**

TRACE is an external memory-management system designed to provide persistent memory and conversational continuity to Large Language Models (LLMs).

It captures conversational experiences, identifies potentially valuable information, organizes it into structured memories and retrieves relevant context when needed. Instead of storing every conversation indiscriminately, TRACE uses selective memory formation, relevance-based retrieval and memory governance to manage information over time.

TRACE works alongside an external LLM. It manages memory and contextual information, while the connected LLM generates natural-language responses.

---

## Key Features

### 1. Selective Memory Formation
Identifies potentially useful information from conversations instead of treating every interaction as a permanent memory.

### 2. Structured Memory Management
Organizes stored information into structured memory records with associated evidence, categories and metadata.

### 3. Memory Retrieval
Retrieves relevant information using a combination of:
- Structured matching.
- Lexical overlap.
- Semantic similarity.
- Relevance and influence scoring.

### 4. Memory Governance
Uses three governance decisions to control how retrieved memories influence the LLM context:

- **USE:** Allows relevant memories to influence the generated context.
- **LIMIT:** Restricts memory influence.
- **BLOCK:** Prevents unsuitable memories from influencing the context.

### 5. Memory Lifecycle Management
Manages memory states and relevance over time through:
- Freshness.
- Activation.
- Dormancy.
- Reactivation.
- Staleness.

### 6. Context Construction
Builds contextual information using approved memories and permitted recent conversation history before sending requests to the external LLM.

### 7. Memory Dashboard
Provides an interface for inspecting stored memories and their associated information.

### 8. Memory Graph Visualization
Visualizes relationships and associations between memory records.

### 9. External LLM Integration
Connects to an external LLM provider through an OpenAI-compatible API.

---

## System Architecture

TRACE operates through two interconnected workflows.

### Memory Formation Workflow

```text
User Interaction
       |
       v
Experience Capture
       |
       v
Candidate Identification
       |
       v
Memory Analysis
       |
       v
Evidence Association
       |
       v
Deduplication and Versioning
       |
       v
Retention Classification
       |
       v
Persistent Memory Storage
```

### Memory Retrieval and Response Workflow

```text
New User Query
       |
       v
Query Understanding
       |
       v
Memory Retrieval
       |
       v
Relevance and Influence Scoring
       |
       v
Memory Governance
       |
       v
Context Construction
       |
       v
External LLM
       |
       v
Response to User
```

---

## Technology Stack

| Component | Technology |
|---|---|
| Programming Language | Python |
| Backend Framework | FastAPI |
| Frontend | HTML, CSS, JavaScript |
| Primary Database | SQLite |
| Optional Vector Storage | ChromaDB |
| Semantic Encoder | all-MiniLM-L6-v2 |
| Model Runtime | ONNX Runtime |
| Graph Visualization | Cytoscape.js |
| LLM Provider | OpenRouter |
| Configured Testing Model | openai/gpt-4o-mini |

---

## Core Components

| Component | Responsibility |
|---|---|
| Experience Capture | Captures conversational interactions |
| Memory Formation | Identifies and organizes useful information |
| Memory Retrieval | Finds relevant stored memories |
| Query Understanding | Analyses incoming user queries |
| Memory Governance | Controls memory influence |
| Memory Lifecycle | Manages memory freshness and activation |
| Context Builder | Constructs contextual information for the LLM |
| LLM Provider | Communicates with the external LLM |
| Memory Dashboard | Displays stored memory records |
| Memory Graph | Visualizes memory relationships |

---

## Installation and Setup

### Prerequisites

- Python 3.10 or a compatible version supported by the project dependencies.
- pip.
- A modern web browser.
- Internet connection for dependency installation and external LLM API requests.
- An OpenRouter API key.

### 1. Clone the Repository

```bash
git clone https://github.com/YOUR_USERNAME/trace-ai-memory-engine.git
cd trace-ai-memory-engine
```

### 2. Create a Virtual Environment

```bash
python -m venv venv
```

Activate the environment.

**Windows:**

```bash
venv\Scripts\activate
```

**Linux/macOS:**

```bash
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure the LLM Provider

Configure your OpenRouter API key using the application's supported configuration mechanism.

Example:

```env
OPENROUTER_API_KEY=your_api_key_here
```

Replace the example with your own key locally. Never commit your actual API key to GitHub.

### 5. Start the Application

If the FastAPI application is exposed as `app` inside `main.py`, the startup command is:

```bash
uvicorn main:app --reload
```

Open the local address displayed in the terminal using your web browser.

*Note: Confirm the actual startup command and environment-variable names against the final source code.*

---

## Current Implementation

TRACE currently provides a functional local prototype incorporating:

- Conversational experience capture.
- Selective memory formation.
- Structured memory storage.
- Structured, lexical and semantic retrieval.
- Memory relevance and governance mechanisms.
- Memory lifecycle management.
- Context construction.
- External LLM integration.
- Memory inspection and visualization.

The application is designed primarily for local, single-user use.

---

## Limitations

- Memory formation and query understanding rely substantially on rule-based processing.
- Retrieval and governance use heuristic scoring mechanisms.
- Ambiguous memory updates and conflict resolution require further improvement.
- The semantic encoder is English-oriented.
- More comprehensive lifecycle evaluation is required.
- Large-scale performance and concurrent-user testing remain future work.
- The application is not yet a production-scale multi-user service.

---

## Future Enhancements

- Improved memory extraction and understanding.
- More reliable memory updating and conflict resolution.
- Enhanced retrieval ranking.
- Multilingual memory support.
- More comprehensive lifecycle evaluation.
- Multi-user support and deployment.
- Improved privacy and security controls.
- Additional LLM provider integrations.
- Quantitative retrieval and performance evaluation.

---

## Authors

- Atharva Pawar
- Aditya Jadhav
- Anirudh Bohra
- Dev Pratap Singh Rajawat

**Institution:** MIT Art, Design and Technology University, Pune, Maharashtra, India.

**Department:** Computer Science and Engineering

---

## Disclaimer

TRACE is an academic software prototype exploring persistent memory management for conversational AI applications. Its memory formation, retrieval, lifecycle and governance mechanisms use computational heuristics and should not be considered guarantees of factual correctness or production-level reliability.
