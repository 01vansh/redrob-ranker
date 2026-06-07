FROM python:3.12-slim

WORKDIR /code

# Install system dependencies if any
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Expose the default Streamlit port (7860 is required by Hugging Face)
EXPOSE 7860

# Command to run the Streamlit app
CMD ["streamlit", "run", "app.py", "--server.port", "7860", "--server.address", "0.0.0.0"]
