FROM apache/airflow:2.10.5

USER root

# Install system dependencies for building Python packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    git \
    swig \
    python3-dev && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install Python packages as root
COPY requirements.txt /requirements.txt
# Switch back to airflow user for security
USER airflow
RUN pip install --no-cache-dir -r /requirements.txt

