# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies
# tesseract-ocr: for OCR functionality
# libgl1-mesa-glx, libglib2.0-0: for OpenCV
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    libgl1 \
    libglib2.0-0 \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy the dependencies file to the working directory
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
# Using --no-cache-dir to keep the image small
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Expose ports for both applications (pemilih 8000, admin 8001)
EXPOSE 8000
EXPOSE 8001

# Default command: server pemilih via gunicorn (dapat di-override, mis. admin).
CMD ["gunicorn", "wsgi_user:app", "-b", "0.0.0.0:8000"]
