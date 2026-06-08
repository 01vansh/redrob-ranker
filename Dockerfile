FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set up a new user named "user" with UID 1000
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

WORKDIR $HOME/app

# Copy requirements and install
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Copy the rest of the application files
COPY --chown=user . .

# Expose the default Streamlit port (7860 is required by Hugging Face)
EXPOSE 7860

# Command to run the Streamlit app with CORS/XSRF disabled for iframe compatibility
CMD ["streamlit", "run", "app.py", "--server.port", "7860", "--server.address", "0.0.0.0", "--server.enableCORS=false", "--server.enableXsrfProtection=false"]
