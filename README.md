# ASSIGNMENT4B
# RAG Pipeline with Airflow

## Project Overview
This project implements a complete Retrieval-Augmented Generation (RAG) pipeline using Apache Airflow to process NVIDIA quarterly reports. The system enables users to query information across multiple documents with support for different chunking strategies and vector database options.

## Project Links and Resources

- **Codelabs Documentation**: [Codelabs Guide](https://codelabs-preview.appspot.com/?file_id=1XLlDWm32yy7p39wwPVNNOp8ka6qVwBJG0jEmVNScp-k/edit?tab=t.5cpih9qtxm58#0)  
- **Project Submission Video (5 Minutes)**: [View on Google Drive](https://drive.google.com/drive/u/1/folders/1898HGutXjQIxwx3OVnr_Yvx9Uq_SKAE1)  
- **Hosted Application Links**:  
  - **Frontend (Streamlit)**: [165.22.179.171:8501](http://165.22.179.171:8501/)  
  - **Backend (FastAPI)**: [165.22.179.171:8000](http://165.22.179.171:8000/)

## Features

- **Document Processing**: Support for recursive, character, and token-based chunking
- **Vector Database Integration**: ChromaDB, FAISS, and Pinecone support
- **Airflow Orchestration**: Automated pipeline for document processing
- **Query Interface**: FastAPI and Streamlit components for user interaction

## Hosted Lines:
- **FASTAPI & Frontend** : http://165.22.179.171:8501/
- **Airflow** : http://67.205.150.201:8080/home
- **ChromaDB**: http://159.223.100.38:8000/api/v1/heartbeat
- **DATA-Parser** http://68.183.17.115/
 
## Architecture

![rag_pipeline_with_airflow](https://github.com/user-attachments/assets/c69400c5-6b46-4031-9b00-f9ae76c0d46e)


## Setup Instructions

### Prerequisites
- Docker and Docker Compose
- Git
- AWS credentials (for S3 access)
- Pinecone API key

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/DAMG7245/Assignment4B.git
   cd Assignment4B
   ```

2. Create a `.env` file with the following variables:
   ```
   AIRFLOW_UID=50000
   AWS_ACCESS_KEY_ID=your_aws_access_key
   AWS_SECRET_ACCESS_KEY=your_aws_secret_key
   AWS_DEFAULT_REGION=your_aws_region
   LANGSMITH_API_KEY=your_langsmith_api_key
   PINECONE_API_KEY=your_pinecone_api_key
   ```

3. Build and start the Airflow services:
   ```bash
   docker-compose up -d
   ```

4. Access the Airflow web UI at `http://localhost:8080` (username/password: airflow/airflow)

## Using the Pipeline

### Triggering the Document Processing DAG

Use the Airflow UI or API to trigger the document processing pipeline:

```bash
curl -X POST \
  http://localhost:8080/api/v1/dags/document_chunking_pipeline/dagRuns \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Basic YWlyZmxvdzphaXJmbG93' \
  -d '{
    "conf": {
      "s3_bucket": "your-bucket-name",
      "s3_key": "path/to/your/document.pdf",
      "chunking_strategy": "recursive",
      "vectordb": "chromadb",
      "collection_name": "your_collection_name"
    }
  }'
```

### Configuration Parameters
- `s3_bucket`: S3 bucket containing the document
- `s3_key`: Path to the document in S3
- `chunking_strategy`: Chunking method (recursive, character, token)
- `vectordb`: Vector database (chromadb, faiss, pinecone)
- `collection_name`: Name for storing document chunks

## Project Structure

```
.
├── dags/                   # Airflow DAG definitions
│   └── main_dag.py        # Main document processing DAG
├── rag/                    # RAG components
│   └── chunking/          # Document chunking strategies
│       └── chunking.py    # Chunking implementation
├── vectordb/              # Vector database integrations
│   ├── chromadb/         # ChromaDB implementation
│   ├── nonvector/        # FAISS implementation
│   └── pinecone/         # Pinecone implementation
├── Dockerfile             # Airflow Docker configuration
├── docker-compose.yaml    # Docker Compose configuration
└── .env                   # Environment variables
```

## Troubleshooting

### Common Issues

1. **Docker Container Problems**:
   - Check Docker logs: `docker-compose logs`
   - Verify environment variables in `.env`

2. **Vector Database Connection Issues**:
   - Ensure API keys are correctly set
   - Check network connectivity to external services

3. **S3 Access Errors**:
   - Verify AWS credentials and permissions
   - Confirm S3 bucket and object permissions

## Contributors
Sai Srunith Silvery: 50 1/2% - Airflow pipeline , pinecone, Mistral OCR
Vishal Prasanna: 50 1/2% - Chroma Db, Streamlit, Doculing, Integration
