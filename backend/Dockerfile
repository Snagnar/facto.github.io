FROM python:3.11-slim

WORKDIR /app

# Install factompile (adjust based on your installation method)
RUN pip install --no-cache-dir factompile

# Copy backend files
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create non-root user for security
RUN useradd -m -u 1000 compiler
USER compiler

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
