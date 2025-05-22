# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
# Set Flask environment variables, useful if using "flask run",
# and good practice even if using "python web/app.py" directly
# as they can be picked up by Flask extensions or for consistency.
ENV FLASK_APP=web/app.py
ENV FLASK_RUN_HOST=0.0.0.0
# FLASK_RUN_PORT is 5000 by default, which matches our app.py and EXPOSE

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
# This includes the 'web' directory, 'daemon', 'config', etc.
COPY . .

# Make port 5000 available to the world outside this container
# This should match the port Flask is running on
EXPOSE 5000

# Run app.py when the container launches, as specified in the subtask.
# The app.py itself is configured to run on host 0.0.0.0 and port 5000.
CMD ["python", "./web/app.py"]
